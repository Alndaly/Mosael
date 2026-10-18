"""把一个模型下到这台 ComfyUI 上(ADR 0034 §3,2026-10-06 的后续调了 2、3 的先后)。按优先级,前一条走不通才试下一条:

1. ComfyUI 自己的下载接口 —— 0.38.0 没有(`/api/assets` 默认关着,里面也没有下载;官方前端缺模型时只是在浏览器里
   打开链接),今天不去探测不存在的接口;
2. **ComfyUI 和 Mosael 在同一台机器上**:它报的模型目录在本机存在、且本机的文件和它报的一致 → 直接写进去。先写
   `<名字>.mosael-part`,**旁边放 `<名字>.mosael-part.json`(sidecar:源 URL、总大小、ETag / Last-Modified、声明的
   SHA256)**;下完用硬链接挂上正式的名字(目标已存在就失败,不覆盖);按字节报进度;开始前查剩余空间。装了 Manager
   也走这条:它看得到进度、停得下、令牌走请求头(不拼进地址、不留在 Manager 的任务记录里),Manager 那条路一样都
   做不到(沙盒实测:本机 ComfyUI 装着 Manager,下载走了 Manager,没有进度 —— 和指南、下载框说的「这台电脑上的
   看得到进度」对不上)。
   **断点续传**(维护者 2026-10-19 定,取代此前「取消/失败就删半截」):取消 / 失败 / 后端重启都**留着** `.part` 和
   sidecar,下次带着 `Range: bytes=<已下>-` 接着下;服务端回 206 就接着写,回 200(不支持 Range,或 `If-Range`
   对不上)就**截断重下**,416(Range 越界)能按声明的 SHA256 校验就留下、不能就删了重下。续传前核对
   URL + 校验器 + 总大小,不一致就重下 —— 绝不把两个不同的文件接在一起。取消 / 失败不再删;只有用户明确点
   「删除没下完的部分」(`discard_partial`)才删。超过 `PART_MAX_AGE_DAYS` 天的孤儿 `.part` 在开始下一次本机
   下载时顺手扫掉(正在续的那一份除外)。
3. **ComfyUI-Manager** 的装模型接口(`/v2/manager/version` 回 V4 时,ComfyUI 在另一台机器上):那台机器自己去下。不报
   字节进度,也没有停下单个任务的接口;它的安全策略只在 ComfyUI 监听回环地址、或 `network_mode = personal_cloud` 时
   才放行 —— 被拒时历史里只记一个 failed,原因在日志里(`/internal/logs/raw`),这里把它找出来说人话,并记下来;
4. 都走不通:如实说明,并给出能做的那一步。

    {"op": "download", "url", "folder", "filename", "sha256"?} → 流式:进度行;结果 {folder, name, size, route, page}
    {"op": "partial", "folder", "filename", "url"?, "sha256"?, "delete"?} → {partial, resumable, downloaded_bytes,
    total_bytes, updated_at, removed}:没下完的那一半还有多少 / 删掉它(「继续下载」「删除没下完的部分」)。

    进度有两行:`{"event": "progress", progress, message, ...}` 是给人看的总进度;`{"event": "step", "step":
    "download", downloaded_bytes, total_bytes, speed_bps}` 是**结构化字节**(未知总数是 null 不是 0)。宿主把后者
    记进任务详情,界面据此显示百分比 / 速度 /「从 3.2 GB 继续」,不解析人话。

`sha256`(可选)是从「确认是同一个文件」的来源下载时那个文件的 SHA256:本机那条路边下边算,对上了才挂正式的名字,
对不上就把半截文件删掉、说清;经 ComfyUI-Manager 那条路是那台机器自己下,Mosael 核对不了 —— 带了 `sha256` 就不走那条,
宁可不下也不装一个没核对过的。

下成了就记下这个文件的来源(见 provenance):模型库的「原链接」、Civitai 的 NSFW 标记和示例图都从这里来。
"""

from __future__ import annotations

import hashlib
import http.client
import os
import re
import shutil
import time
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable
from urllib import parse

import provenance
import shared_models
import sources
from comfy_http import Comfy
from lines import ComfyError, say
from model_files import data_file, files_in, folder_info, load_json, names_in, norm, plain, save_json

Emit = Callable[[dict[str, Any]], None]

#: 提交给 Manager 的任务带的 client_id(它按这个分开各家的任务)。
MANAGER_CLIENT = "mosael"
#: 隔多久问一次 Manager 的历史。
MANAGER_POLL_SECONDS = 2.0
#: Manager 的历史里一直没有这个任务、队列也不在跑:多久之后判它丢了。
MANAGER_LOST_SECONDS = 120.0
#: Mosael 只认这个大版本起的 Manager(`/v2/manager/version` 回 `V4.2.1` 这样)。更老的不支持(维护者 2026-10-06 定)。
MANAGER_MAJOR_SUPPORTED = 4
_MANAGER_MAJOR = re.compile(r"^[Vv](\d+)(?:\.|$)")
#: 剩余空间要比文件多留多少(文件系统的元数据、别的程序同时在写)。
DISK_MARGIN = 256 * 1024 * 1024
#: 进度多久报一次。
PROGRESS_SECONDS = 0.5
CHUNK = 1024 * 1024
#: 没下完的半截:`<名字>.mosael-part`;旁边 `<名字>.mosael-part.json` 记着续传要核对的东西。
PART_SUFFIX = ".mosael-part"
#: 半截旁边的 sidecar 后缀(拼在 PART_SUFFIX 后面)。
PART_SIDECAR_SUFFIX = ".mosael-part.json"
#: 超过这么多天的孤儿 `.part` 才在下次本机下载开始时扫掉。定 7 天:几十 GB 的模型在慢线路上跨几个晚上下完是常事,
#: 一两天就清会把「明天接着下」的人也清掉;而一周没动过的半截基本不会再被认领,几个文件就能白占几十 GB。
PART_MAX_AGE_DAYS = 7
#: 同一台机器的判定:最多比对几个文件、翻几个目录。
SAME_MACHINE_FILES = 6
SAME_MACHINE_FOLDERS = 8
#: 先翻这几个目录(多半不空)。
_LIKELY_FOLDERS = ("checkpoints", "loras", "vae", "diffusion_models", "text_encoders", "upscale_models", "controlnet",
                   "embeddings", "clip_vision")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _cancelled() -> bool:
    path = os.environ.get("MOSAEL_PLUGIN_CANCEL_FILE", "")
    return bool(path) and os.path.exists(path)


def _human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit in ("B", "KB") else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


# --- 走哪条路 -----------------------------------------------------------------

def manager_version(comfy: Comfy) -> str:
    """ComfyUI-Manager 的版本(`V4.2.1`)。**只认 V4 起**(pip 包 `comfyui_manager`,ComfyUI 0.4.0 起自带):没装、或者更老
    (克隆进 custom_nodes 的 3.x,不管它答不答 `/v2/manager/version`)→ 空串,当作没有 Mosael 能用的 Manager。"""
    try:
        found = (comfy.get_text("/v2/manager/version") or "").strip()
    except ComfyError:
        return ""
    major = _MANAGER_MAJOR.match(found)
    return found if major and int(major.group(1)) >= MANAGER_MAJOR_SUPPORTED else ""


def manager_needed(locale: str) -> str:
    """没有 Mosael 能用的 Manager 时那一句该做什么(下模型、装节点包、重启都说这一句)。"""
    return say(locale, "Mosael 要 ComfyUI-Manager V4(ComfyUI 0.4.0 起自带):在那台机器上 "
                       "pip install -r manager_requirements.txt,启动 ComfyUI 时加 --enable-manager",
               "Mosael needs ComfyUI-Manager V4 (built into ComfyUI 0.4.0 and later): on that machine run "
               "pip install -r manager_requirements.txt and start ComfyUI with --enable-manager")


def same_machine(comfy: Comfy, info: dict[str, list[str]] | None,
                 listing: dict[str, list[dict[str, Any]]] | None = None) -> bool:
    """ComfyUI 和 Mosael 在不在同一台机器上:它报的模型目录在本机存在、且本机的文件和它报的一致(名字、大小)。

    光路径存在不够:两台机器可能恰好有同一个路径。一个文件都没有可比的(全是空目录)时,只认回环地址。"""
    if not info:
        return False
    checked = 0
    order = [one for one in _LIKELY_FOLDERS if one in info] + [one for one in info if one not in _LIKELY_FOLDERS]
    for folder in order[:SAME_MACHINE_FOLDERS]:
        paths = info.get(folder) or []
        if not paths:
            continue
        items = listing.get(folder) if listing is not None and folder in listing else files_in(comfy, folder)
        for item in items[:3]:
            index = int(item.get("pathIndex") or 0)
            if index >= len(paths):
                continue
            local = Path(paths[index]).joinpath(*norm(str(item["name"])).split("/"))
            if not local.is_file():
                return False
            if isinstance(item.get("size"), int) and local.stat().st_size != item["size"]:
                return False
            checked += 1
        if checked >= SAME_MACHINE_FILES:
            break
    if checked:
        return True
    loopback = (parse.urlsplit(comfy.base).hostname or "") in ("127.0.0.1", "localhost", "::1")
    return loopback and any(Path(path).is_dir() for paths in info.values() for path in paths)


def _local_dir(info: dict[str, list[str]], folder: str) -> Path | None:
    """本机那条路写进哪个目录:那个模型目录报的第一处(不存在就在它的上一级存在时建出来)。**共用的模型文件夹不算**
    (ADR 0041 拍板 5:那是别处的,只读)—— 新下的文件落在这台 ComfyUI 自己的那一处;这个模型目录只在共用的那几处有,
    就不走本机这条路。"""
    shared = shared_models.shared_roots()
    paths = [path for path in info.get(folder) or [] if not shared_models.in_shared(path, shared)]
    for path in paths:
        if Path(path).is_dir():
            return Path(path)
    if paths and Path(paths[0]).parent.is_dir():
        return Path(paths[0])
    return None


def _refusal(comfy: Comfy) -> dict[str, Any]:
    return load_json(data_file(comfy, "manager-refused"))


def _policy_steps(locale: str, url: str = "", folder: str = "", filename: str = "") -> str:
    manual = say(locale, f"也可以手动把 {url} 下到那台机器的 models/{folder}/{filename}",
                 f"Or download {url} yourself into models/{folder}/{filename} on that machine") if url else ""
    steps = say(
        locale,
        "这台 ComfyUI 的 ComfyUI-Manager 不让经网络装模型(它的安全策略:ComfyUI 监听的不是本机地址时,要 network_mode 是 "
        "personal_cloud 才放行)。要用这条路:在那台机器上打开 ComfyUI/user/__manager/config.ini(旧版在 "
        "ComfyUI/user/default/ComfyUI-Manager/config.ini),把 network_mode 改成 personal_cloud、security_level 保持 normal,"
        "然后重启 ComfyUI。",
        "This ComfyUI's ComfyUI-Manager won't install models over the network (its security policy: when ComfyUI listens on "
        "a non-local address, network_mode must be personal_cloud). To use it: on that machine open "
        "ComfyUI/user/__manager/config.ini (older versions: ComfyUI/user/default/ComfyUI-Manager/config.ini), set "
        "network_mode to personal_cloud, keep security_level at normal, and restart ComfyUI.",
    )
    return f"{steps}{manual}"


def _none_steps(locale: str, url: str = "", folder: str = "", filename: str = "") -> str:
    manual = say(locale, f"或者手动把 {url} 下到那台机器的 models/{folder}/{filename}",
                 f"or download {url} yourself into models/{folder}/{filename} on that machine") if url else \
        say(locale, "或者手动把文件放进那台机器的 models/<目录>/", "or put the file into models/<folder>/ on that machine yourself")
    return say(
        locale,
        f"这台 ComfyUI 没有 Mosael 能用的 ComfyUI-Manager,ComfyUI 自己也没有下载接口,它又不在这台电脑上 —— Mosael 没法替它下。"
        f"{manager_needed(locale)};{manual}",
        f"This ComfyUI has no ComfyUI-Manager that Mosael can use, ComfyUI itself has no download API, and it isn't on this "
        f"computer, so Mosael can't download for it. {manager_needed(locale)}; {manual}",
    )


def describe(comfy: Comfy, info: dict[str, list[str]] | None, listing: dict[str, list[dict[str, Any]]],
             locale: str) -> dict[str, str]:
    """模型库里那一行「下载走哪条路」:`manager` / `local` / `none`,外加给人看的一句。"""
    if same_machine(comfy, info, listing):
        return {"route": "local", "note": say(
            locale, "ComfyUI 就在这台电脑上:直接写进它的 models 目录,看得到进度、能取消",
            "ComfyUI is on this computer: files go straight into its models folder, with progress and cancel")}
    version = manager_version(comfy)
    refused = _refusal(comfy)
    if version:
        note = say(locale, f"经 ComfyUI-Manager({version})下载:由那台机器自己去下",
                   f"Downloads go through ComfyUI-Manager ({version}): that machine downloads by itself")
        if refused:
            note = f"{note} · {say(locale, '上次被拒绝了:', 'Refused last time: ')}{_policy_steps(locale)}"
        return {"route": "manager", "note": note}
    return {"route": "none", "note": _none_steps(locale)}


# --- Manager ------------------------------------------------------------------

def _manager_save_path(info: dict[str, list[str]], folder: str) -> str:
    """Manager 的 `save_path` 是相对 ComfyUI 的 models 目录的路径:按这个目录报的第一处推(`unet_gguf` 实际在
    `models/unet`);推不出就用目录名。"""
    for raw in info.get(folder) or []:
        path = PureWindowsPath(raw) if "\\" in raw else PurePosixPath(raw)
        parts = [part for part in path.parts]
        lowered = [part.lower() for part in parts]
        if "models" in lowered:
            index = len(lowered) - 1 - lowered[::-1].index("models")
            rest = parts[index + 1:]
            if rest:
                return "/".join(rest)
    return folder


def _log_entries(comfy: Comfy) -> list[dict[str, Any]] | None:
    try:
        found = comfy.get("/internal/logs/raw")
    except ComfyError:
        return None
    entries = found.get("entries") if isinstance(found, dict) else None
    return [entry for entry in entries if isinstance(entry, dict)] if isinstance(entries, list) else None


def _log_cursor(comfy: Comfy) -> str | None:
    """提交前日志的最后一行是什么时候(那台机器的钟)。ComfyUI 只留最近 300 行:满了之后行数不变,只能按时间认新旧。
    读不到日志 → None。"""
    entries = _log_entries(comfy)
    if entries is None:
        return None
    return str(entries[-1].get("t") or "") if entries else ""


def _log_reason(comfy: Comfy, cursor: str | None) -> str:
    """提交之后的日志里 Manager 说了什么(它的历史里只记一个 failed)。"""
    if cursor is None:
        return ""
    entries = _log_entries(comfy) or []
    lines = [_ANSI.sub("", str(entry.get("m") or "")).strip() for entry in entries if str(entry.get("t") or "") > cursor]
    lines = [line for line in lines if line]
    policy = next((line for line in lines if "security_level" in line or "network_mode" in line), "")
    if policy:
        return policy
    return next((line for line in reversed(lines) if "Manager" in line or "ERROR" in line or "rror" in line), "")[:500]


def via_manager(comfy: Comfy, info: dict[str, list[str]], url: str, folder: str, filename: str, locale: str,
                emit: Emit) -> dict[str, Any]:
    ui_id = f"mosael-{uuid.uuid4().hex[:8]}"
    # Manager 不收请求头:Civitai 的令牌只能拼进地址(会留在那台机器的 Manager 历史里,见 ADR 0034 §5)
    token = sources.token_for(url) if sources._host(url) in sources.CIVITAI_HOSTS else ""  # noqa: SLF001
    sent_url = f"{url}{'&' if '?' in url else '?'}token={parse.quote(token)}" if token else url
    cursor = _log_cursor(comfy)
    comfy.post("/v2/manager/queue/install_model", {
        "client_id": MANAGER_CLIENT, "ui_id": ui_id, "name": filename, "type": folder, "base": "",
        "save_path": _manager_save_path(info, folder), "url": sent_url, "filename": filename,
    })
    comfy.post("/v2/manager/queue/start", {})
    started = time.monotonic()
    emit({"event": "progress", "progress": 0.02,
          "message": say(locale, f"ComfyUI-Manager 正在下载 {filename}(那台机器自己下,看不到字节进度)",
                         f"ComfyUI-Manager is downloading {filename} (that machine downloads it; no byte progress)")})
    last_said = started
    while True:
        found = comfy.get("/v2/manager/queue/history", {"ui_id": ui_id})
        entry = found.get("history") if isinstance(found, dict) else None
        if isinstance(entry, dict) and entry.get("result"):
            break
        if _cancelled():
            raise ComfyError(say(locale, "已停止等待。ComfyUI-Manager 没有停下单个下载的接口,那台机器上的下载还会继续;下完刷新模型库就看得到",
                                 "Stopped waiting. ComfyUI-Manager can't stop a single download, so it keeps going on that "
                                 "machine; refresh the model library once it's done"))
        waited = time.monotonic() - started
        if waited > MANAGER_LOST_SECONDS:
            status = comfy.get("/v2/manager/queue/status") or {}
            if not status.get("is_processing") and not status.get("pending_count"):
                raise ComfyError(say(locale, "ComfyUI-Manager 的队列里找不到这个下载了(它可能重启过):刷新模型库看看文件到了没有",
                                     "ComfyUI-Manager no longer has this download (it may have restarted). Refresh the model "
                                     "library to see whether the file arrived"))
        if time.monotonic() - last_said >= 10:
            last_said = time.monotonic()
            emit({"event": "progress", "progress": 0.02,
                  "message": say(locale, f"ComfyUI-Manager 正在下载 {filename} · 已等 {int(waited)} 秒",
                                 f"ComfyUI-Manager is downloading {filename} · {int(waited)} s so far")})
        time.sleep(MANAGER_POLL_SECONDS)
    if entry.get("result") == "success" or (entry.get("status") or {}).get("status_str") == "success":
        if norm(filename) not in names_in(comfy, folder):
            raise ComfyError(say(locale, f"ComfyUI-Manager 说下好了,可 {folder} 里没有 {filename}:去那台机器的 Manager 里看看",
                                 f"ComfyUI-Manager says it's done, but {folder} has no {filename}; check the Manager on that machine"))
        if _refusal(comfy):
            save_json(data_file(comfy, "manager-refused"), {})  # 这次放行了:配置改过了,不再提醒
        emit({"event": "progress", "progress": 1.0, "message": say(locale, f"{filename} 已下好", f"{filename} downloaded")})
        sizes = {norm(str(item["name"])): item.get("size") for item in files_in(comfy, folder)}
        return {"folder": folder, "name": filename, "size": sizes.get(norm(filename)), "route": "manager"}
    reason = _log_reason(comfy, cursor)
    if "security_level" in reason or "network_mode" in reason:
        save_json(data_file(comfy, "manager-refused"), {"at": time.time()})
        raise ComfyError(_policy_steps(locale, url, folder, filename))
    detail = reason or "; ".join(str(one) for one in (entry.get("status") or {}).get("messages") or []) or "failed"
    raise ComfyError(say(locale, f"ComfyUI-Manager 没下成:{_scrub(detail, token)}",
                         f"ComfyUI-Manager didn't download it: {_scrub(detail, token)}"))


def _scrub(text: str, *secrets: str) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


# --- 同一台机器:直接写 ---------------------------------------------------------

def _open_download(url: str, locale: str, headers: dict[str, str] | None = None):
    """开始下:带着这次请求自己的头(续传的 `Range` / `If-Range`),跟着跳转,每一跳只带那一跳的站自己的令牌。
    返回 (响应, 最终地址)。**416 原样交回** —— 对续传来说它不是「出错」,是「这个范围没有东西」,由调用方判定。"""
    current = url
    extra = dict(headers or {})
    for _ in range(sources.MAX_HOPS):
        response = sources.open_url(current, headers={**sources.auth_for(current), **extra}, timeout=60)
        status = getattr(response, "status", None) or getattr(response, "code", 0)
        location = response.headers.get("Location")
        if status in (301, 302, 303, 307, 308) and location:
            response.close()
            current = parse.urljoin(current, location)
            continue
        if status == 416 and extra.get("Range"):
            return response, current
        if status >= 400:
            response.close()
            if status in (401, 403):
                raise ComfyError(say(locale, f"{sources._host(current)} 不让下(HTTP {status}):要登录的,在这个连接的凭据里填"  # noqa: SLF001
                                             "那个站的令牌(HuggingFace / Civitai / ModelScope)",
                                     f"{sources._host(current)} refused the download (HTTP {status}). If it needs a login, "  # noqa: SLF001
                                     "enter that site's token (HuggingFace / Civitai / ModelScope) in this connection's "
                                     "credentials"))
            raise ComfyError(say(locale, f"下载地址回了 HTTP {status}", f"The download link answered HTTP {status}"))
        return response, current
    raise ComfyError(say(locale, "下载地址跳转太多次", "The download link redirected too many times"))


def _status(response: Any) -> int:
    return int(getattr(response, "status", None) or getattr(response, "code", 0) or 0)


def _content_length(response: Any) -> int | None:
    raw = response.headers.get("Content-Length", "")
    return int(raw) if str(raw).isdigit() else None


_CONTENT_RANGE = re.compile(r"bytes\s+(\d+)-(\d+)/(\d+|\*)")


def _content_range(response: Any) -> tuple[int, int, int | None] | None:
    """`Content-Range: bytes <起>-<止>/<总>` → (起, 止, 总);总写成 `*` 时是 None。"""
    found = _CONTENT_RANGE.fullmatch(str(response.headers.get("Content-Range") or "").strip())
    if found is None:
        return None
    return int(found.group(1)), int(found.group(2)), (None if found.group(3) == "*" else int(found.group(3)))


def _file_digest(part: Path) -> "hashlib._Hash":
    """把一个已有的半截读完再接着算 SHA256(续传时最终哈希要覆盖**整个文件**,不只是新下的那段)。"""
    digest = hashlib.sha256()
    with part.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest


def _sidecar_data(sidecar: Path) -> dict[str, Any]:
    data = load_json(sidecar)
    return data if data.get("version") == 1 else {}


def _write_sidecar(sidecar: Path, *, url: str, final_url: str, filename: str, total: int | None,
                   etag: str, last_modified: str, sha256: str) -> None:
    save_json(sidecar, {
        "version": 1,
        "url": url,
        "final_url": final_url,
        "filename": filename,
        "total_bytes": total if isinstance(total, int) and total > 0 else None,
        "etag": etag or "",
        "last_modified": last_modified or "",
        "sha256": (sha256 or "").lower(),
        "updated_at": time.time(),
    })


def _part_paths(directory: Path, filename: str) -> tuple[Path, Path]:
    return directory / f"{filename}{PART_SUFFIX}", directory / f"{filename}{PART_SIDECAR_SUFFIX}"


def _remove_partial(part: Path, sidecar: Path) -> None:
    part.unlink(missing_ok=True)
    sidecar.unlink(missing_ok=True)


def _clean_orphan_parts(directory: Path, *, keep: str = "", now: float | None = None) -> list[str]:
    """把超过 `PART_MAX_AGE_DAYS` 天没动过的孤儿 `.part`(连同 sidecar)扫掉。返回扫掉的模型名。

    **只有开始下一次本机下载时才扫**(不另起定时任务):`.part` 就在模型目录里,那时正好知道这个目录在哪、能不能写。
    `keep` 是这一次要续的那一份 —— 用户刚点了「继续下载」,哪怕它放了很久也不再算孤儿。"""
    cutoff = (time.time() if now is None else now) - PART_MAX_AGE_DAYS * 86400
    removed: list[str] = []
    for path in list(directory.iterdir()):
        name = path.name
        if name.endswith(PART_SUFFIX):
            filename = name[: -len(PART_SUFFIX)]
            if filename == keep:
                continue
            try:
                changed = path.stat().st_mtime
            except OSError:
                continue
            if changed >= cutoff:
                continue
            path.unlink(missing_ok=True)
            (directory / f"{name}.json").unlink(missing_ok=True)
            removed.append(filename)
        elif name.endswith(PART_SIDECAR_SUFFIX):
            #: 半截已经没了、sidecar 还在:同样按时间扫,别让它跟着孤儿一起留下。
            if (directory / name[: -len(".json")]).exists():
                continue
            try:
                changed = path.stat().st_mtime
            except OSError:
                continue
            if changed < cutoff:
                path.unlink(missing_ok=True)
    return removed


def _resume_offset(part: Path, sidecar: Path, url: str, sha256: str) -> int:
    """这份半截能不能接着下;能就返回已下字节数,不能返回 0。

    核对的是**同一个文件**的三样:源 URL、声明的 SHA256、sidecar 里记的总大小 / 校验器。任何一样对不上都从头下 ——
    宁可多下一次,也不把两个不同的文件接在一起。"""
    if not part.is_file():
        if sidecar.exists():
            sidecar.unlink(missing_ok=True)
        return 0
    try:
        offset = part.stat().st_size
    except OSError:
        return 0
    data = _sidecar_data(sidecar)
    if offset <= 0 or not data:
        return 0
    if data.get("url") != url:
        return 0
    if (data.get("sha256") or "").lower() != (sha256 or "").lower():
        return 0
    total = data.get("total_bytes")
    if isinstance(total, int) and not isinstance(total, bool):
        if total <= 0 or offset > total:
            return 0
    elif not (data.get("etag") or data.get("last_modified")):
        #: 既没有总大小、也没有校验器:续下去没法核对是不是同一个文件,不硬续。
        return 0
    return offset


def _validators_changed(stored: dict[str, Any], response: Any) -> bool:
    """206 也不能全信:文件在两次下载之间被重新发布时,有的服务端照样按 Range 回 206。ETag / Last-Modified 变了就重下。"""
    etag = response.headers.get("ETag")
    if stored.get("etag") and etag and etag != stored["etag"]:
        return True
    if not stored.get("etag") and stored.get("last_modified"):
        modified = response.headers.get("Last-Modified")
        if modified and modified != stored["last_modified"]:
            return True
    return False


def _bytes_progress(emit: Emit, locale: str, downloaded: int, total: int | None, speed: float,
                    *, message: str = "") -> None:
    """报一次进度。**字节是结构化的**(`downloaded_bytes` / `total_bytes`,未知是 null 不是 0),速度也是从字节和
    时间算出来的 —— 界面不解析人话。`progress` 行给任务的总进度,`step` 行把字节交给宿主记进任务(见
    domain/model_library._download 的 on_step)。"""
    known_total = total if isinstance(total, int) and total > 0 else None
    fraction = min(0.99, downloaded / known_total) if known_total else 0.0
    said = message or say(
        locale,
        f"已下载 {_human(downloaded)}" + (f" / {_human(known_total)}" if known_total else "")
        + (f" · {_human(speed)}/s" if speed > 0 else ""),
        f"{_human(downloaded)}" + (f" of {_human(known_total)}" if known_total else "")
        + (f" downloaded · {_human(speed)}/s" if speed > 0 else ""),
    )
    payload = {"downloaded_bytes": int(downloaded), "total_bytes": known_total,
               "speed_bps": round(float(speed)) if speed > 0 else None}
    emit({"event": "progress", "progress": fraction, "message": said, **payload})
    emit({"event": "step", "step": "download", **payload})


def _download_finished(emit: Emit, locale: str, written: int, total: int | None, speed: float) -> None:
    known_total = total if isinstance(total, int) and total > 0 else None
    payload = {"downloaded_bytes": int(written), "total_bytes": known_total,
               "speed_bps": round(float(speed)) if speed > 0 else None}
    emit({"event": "progress", "progress": 1.0,
          "message": say(locale, f"已下载 {_human(written)}", f"{_human(written)} downloaded"), **payload})
    emit({"event": "step", "step": "download", **payload})


def via_local(directory: Path, url: str, folder: str, filename: str, locale: str, emit: Emit, *, sha256: str = "") -> dict[str, Any]:
    directory.mkdir(exist_ok=True)
    final = directory / filename
    part, sidecar = _part_paths(directory, filename)
    if final.exists():
        raise ComfyError(_same_name(locale, folder, filename))
    #: 先扫这个目录里**别人**留下的、超过 N 天的孤儿半截;要续的这一份(同名)不算孤儿。
    _clean_orphan_parts(directory, keep=filename)
    offset = _resume_offset(part, sidecar, url, sha256)
    if offset <= 0:
        #: 半截在、但核对不过(sidecar 没了、URL / 哈希 / 大小变了):不硬续,删掉从头下。
        _remove_partial(part, sidecar)
        offset = 0
    stored = _sidecar_data(sidecar)
    digest = _file_digest(part) if (offset and sha256) else hashlib.sha256()
    restarted = False
    while True:
        headers: dict[str, str] = {}
        if offset:
            #: 续传必须让服务端别压缩(否则 Range 的字节数和文件对不上),也让跳转后的每一跳都带着它。
            headers["Accept-Encoding"] = "identity"
            headers["Range"] = f"bytes={offset}-"
            validator = stored.get("etag") or stored.get("last_modified")
            if validator:
                headers["If-Range"] = str(validator)
        response, landed = _open_download(url, locale, headers=headers) if headers else _open_download(url, locale)
        try:
            status = _status(response)
            if status == 416:
                #: Range 越界:本地这份可能已经下完了。**能按声明的 SHA256 校验就留下**,校验不了(没有哈希、
                #: 或对不上)就删掉重下 —— 不把一个没核对过的文件挂上正式的名字。
                response.close()
                if sha256 and offset > 0 and _file_digest(part).hexdigest() == sha256:
                    _publish(part, final, locale, folder, filename)
                    sidecar.unlink(missing_ok=True)
                    total_known = stored.get("total_bytes") if isinstance(stored.get("total_bytes"), int) else offset
                    _download_finished(emit, locale, offset, total_known, 0.0)
                    return {"folder": folder, "name": filename, "size": offset, "route": "local"}
                _remove_partial(part, sidecar)
                if restarted:
                    raise ComfyError(say(locale, "服务端说这个范围没有东西,本地这一份也核对不过:删掉重下一次",
                                         "The server says that range has nothing, and the local copy doesn't verify: "
                                         "it was deleted; download again"))
                offset, digest, stored, restarted = 0, hashlib.sha256(), {}, True
                continue
            kind = response.headers.get("Content-Type", "").lower()
            if kind.startswith("text/html"):
                raise ComfyError(say(locale, "下载地址回的是一个网页,不是模型文件(多半要登录:在这个连接的凭据里填那个站的令牌)",
                                     "The download link returned a web page, not a model file (it probably needs a login: enter "
                                     "that site's token in this connection's credentials)"))
            if status == 206 and offset:
                found = _content_range(response)
                known = stored.get("total_bytes")
                if (found is None or found[0] != offset
                        or (found[2] is not None and isinstance(known, int) and found[2] != known)
                        or _validators_changed(stored, response)):
                    #: 服务端回的 206 接不上(起点不对),或者文件已经换了一份:不能把两段接在一起。
                    response.close()
                    _remove_partial(part, sidecar)
                    if restarted:
                        raise ComfyError(say(locale, "服务端给的续传范围接不上,重下一次也不行;再试一次",
                                             "The server's resume range doesn't line up; it failed twice. Try again"))
                    offset, digest, stored, restarted = 0, hashlib.sha256(), {}, True
                    continue
                total = found[2] if found[2] is not None else (
                    known if isinstance(known, int) else None)
                mode = "ab"
            elif status == 200:
                #: 不支持 Range(或 If-Range 对不上):整包从 0 开始,`wb` 截断旧半截 —— 绝不接在后面。
                if offset:
                    offset = 0
                    digest = hashlib.sha256()
                total = _content_length(response)
                mode = "wb"
            else:
                raise ComfyError(say(locale, f"下载地址回了 HTTP {status}", f"The download link answered HTTP {status}"))
            if total:
                free = shutil.disk_usage(directory).free
                need = max(0, total - offset)
                if free < need + DISK_MARGIN:
                    raise ComfyError(say(locale, f"空间不够:{directory} 所在的磁盘只剩 {_human(free)},这个文件还要 {_human(need)}",
                                         f"Not enough space: the disk holding {directory} has {_human(free)} left and this "
                                         f"file still needs {_human(need)}"))
            _write_sidecar(sidecar, url=url, final_url=landed or _final_url(response, url), filename=filename, total=total,
                           etag=response.headers.get("ETag") or (stored.get("etag", "") if mode == "ab" else ""),
                           last_modified=response.headers.get("Last-Modified")
                           or (stored.get("last_modified", "") if mode == "ab" else ""), sha256=sha256)
            started = last = time.monotonic()
            new_written = 0
            if mode == "ab" and offset:
                _bytes_progress(emit, locale, offset, total, 0.0,
                                message=say(locale, f"从已下载的 {_human(offset)} 继续"
                                                    + (f"(共 {_human(total)})" if total else ""),
                                            f"Resuming from {_human(offset)}" + (f" of {_human(total)}" if total else "")))
            with part.open(mode) as handle:
                while True:
                    if _cancelled():
                        #: 取消**不删**半截:下一次「继续下载」从这儿接着下。
                        raise ComfyError(say(locale, "已取消", "Cancelled"))
                    # read1:有多少拿多少,不等凑满一块 —— 慢的时候取消也能马上生效
                    try:
                        chunk = response.read1(CHUNK) if hasattr(response, "read1") else response.read(CHUNK)
                    except (OSError, http.client.HTTPException) as exc:
                        raise ComfyError(say(locale, f"下载连接断了(已下 {_human(offset + new_written)}):再试一次会接着下",
                                             f"The download connection broke off ({_human(offset + new_written)} so far); "
                                             f"try again and it will resume")) from exc
                    if not chunk:
                        break
                    handle.write(chunk)
                    if sha256:
                        digest.update(chunk)
                    new_written += len(chunk)
                    now = time.monotonic()
                    if now - last >= PROGRESS_SECONDS:
                        last = now
                        speed = new_written / max(now - started, 0.001)
                        _bytes_progress(emit, locale, offset + new_written, total, speed)
            written = offset + new_written
            if total and written != total:
                #: 断了:半截和 sidecar 留着,下一次接着下。
                raise ComfyError(say(locale, f"下到一半断了({_human(written)} / {_human(total)}),再试一次",
                                     f"The download broke off ({_human(written)} of {_human(total)}); try again"))
            if sha256:
                got = digest.hexdigest()
                if got != sha256:
                    #: 这份不是确认过的那个文件:半截没有续传价值,删掉;正式的名字一次都不挂。
                    _remove_partial(part, sidecar)
                    raise ComfyError(say(locale, f"下到的文件和确认过的那个不是同一个(SHA256 {got[:12]}…,应为 "
                                                   f"{sha256[:12]}…):已经删掉,没放进 {folder}",
                                         f"The downloaded file isn't the confirmed one (SHA256 {got[:12]}…, expected "
                                         f"{sha256[:12]}…): it was deleted and not put into {folder}"))
            _publish(part, final, locale, folder, filename)
            sidecar.unlink(missing_ok=True)
            speed = new_written / max(time.monotonic() - started, 0.001)
            _download_finished(emit, locale, written, total, speed)
            return {"folder": folder, "name": filename, "size": written, "route": "local"}
        finally:
            response.close()


def _final_url(response: Any, fallback: str) -> str:
    """这一跳最后落在哪个地址(没有 `geturl` 就用一开始那个)。只记在 sidecar 里给人排查,不参与续传核对。"""
    getter = getattr(response, "geturl", None)
    try:
        return str(getter()) if callable(getter) else fallback
    except Exception:  # noqa: BLE001 — 记不下来不是下载的事
        return fallback


def discard_partial(directory: Path, filename: str) -> bool:
    """**用户明确点了「删除没下完的部分」**才走这里:删掉 `.part` 和 sidecar,成品一个都不碰。"""
    part, sidecar = _part_paths(directory, filename)
    existed = part.is_file() or sidecar.is_file()
    _remove_partial(part, sidecar)
    return existed


def partial(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    """问/删一个模型文件的半截(界面上的「继续下载」要知道从多少开始,「删除没下完的部分」要真的删掉)。

    `{"op": "partial", "folder", "filename", "url"?, "sha256"?, "delete"?}`。只在本机那条下载路上有意义:
    那台服务器在另一台机器上时(经 ComfyUI-Manager 下)Mosael 这边没有半截,`partial` 是 false。"""
    folder = str(payload.get("folder") or "").strip()
    filename = str(payload.get("filename") or "").strip()
    url = str(payload.get("url") or "").strip()
    sha256 = str(payload.get("sha256") or "").strip().lower()
    delete = payload.get("delete") is True
    if not plain(folder) or not plain(filename):
        raise ComfyError(say(locale, "目录和文件名都只能是一段名字,不能带路径",
                             "The folder and file name must be plain names, not paths"))
    info = folder_info(comfy)
    if info is None or folder not in info:
        raise ComfyError(say(locale, f"这台 ComfyUI 没有「{folder}」这个模型目录",
                             f"This ComfyUI has no model folder “{folder}”"))
    local = _local_dir(info, folder)
    empty = {"folder": folder, "name": filename, "partial": False, "resumable": False,
             "downloaded_bytes": None, "total_bytes": None, "updated_at": None, "removed": False}
    if local is None:
        return empty
    #: 问/删半截的时候也顺手扫一下这个目录的孤儿(同一套 N 天规则);要查的这份不算孤儿。
    _clean_orphan_parts(local, keep=filename)
    part, sidecar = _part_paths(local, filename)
    if delete:
        removed = discard_partial(local, filename)
        return {**empty, "removed": removed}
    if not part.is_file():
        if sidecar.exists():
            sidecar.unlink(missing_ok=True)
        return empty
    try:
        size = part.stat().st_size
        modified = part.stat().st_mtime
    except OSError:
        return empty
    stored = _sidecar_data(sidecar)
    known = stored.get("total_bytes")
    total = known if isinstance(known, int) and not isinstance(known, bool) and known > 0 else None
    return {"folder": folder, "name": filename, "partial": True,
            #: 能续的判据和真正续传时**同一条**(见 _resume_offset):URL / 声明的 SHA256 / 总大小 / 校验器。
            "resumable": bool(url) and _resume_offset(part, sidecar, url, sha256) > 0,
            "downloaded_bytes": size, "total_bytes": total, "updated_at": modified, "removed": False}


def _publish(part: Path, final: Path, locale: str, folder: str, filename: str) -> None:
    """半截文件挂上正式的名字,**不覆盖**:硬链接在目标已存在时失败,没有竞态窗口;文件系统不支持硬链接时退回改名
    (Windows 的改名本来就不覆盖,别处先查一遍)。"""
    try:
        os.link(part, final)
    except FileExistsError as exc:
        raise ComfyError(_same_name(locale, folder, filename)) from exc
    except OSError:
        if final.exists():
            raise ComfyError(_same_name(locale, folder, filename)) from None
        os.rename(part, final)
        return
    part.unlink(missing_ok=True)


def _same_name(locale: str, folder: str, filename: str) -> str:
    return say(locale, f"{folder} 里已经有同名文件 {filename},不覆盖:换一个名字再下",
               f"{folder} already has a file named {filename}; it won't be overwritten. Pick another name")


# --- op: download ---------------------------------------------------------------

def download(payload: dict[str, Any], comfy: Comfy, locale: str, emit: Emit) -> dict[str, Any]:
    url = str(payload.get("url") or "").strip()
    folder = str(payload.get("folder") or "").strip()
    filename = str(payload.get("filename") or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ComfyError(say(locale, "这不是一个能下载的链接:要以 http:// 或 https:// 开头",
                             "This is not a downloadable link: it must start with http:// or https://"))
    if not plain(folder) or not plain(filename):
        raise ComfyError(say(locale, "目录和文件名都只能是一段名字,不能带路径", "The folder and file name must be plain names, not paths"))
    sha256 = str(payload.get("sha256") or "").strip().lower()
    if sha256 and not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ComfyError(say(locale, "要核对的那个 SHA256 不是一个 64 位的十六进制数",
                             "The SHA256 to verify against isn't a 64-character hex string"))
    info = folder_info(comfy)
    if info is None:
        raise ComfyError(say(locale, "这台 ComfyUI 太旧,没有模型目录的接口(/experiment/models),Mosael 替它下不了:升级 ComfyUI",
                             "This ComfyUI is too old to have the model folder API (/experiment/models); update it to download through Mosael"))
    if folder not in info:
        raise ComfyError(say(locale, f"这台 ComfyUI 没有「{folder}」这个模型目录", f"This ComfyUI has no model folder “{folder}”"))
    if norm(filename) in names_in(comfy, folder):
        raise ComfyError(_same_name(locale, folder, filename))
    direct = sources.direct_url(url, locale, set(info))
    # 来源页在开始下之前就问好(Civitai 的要问一次版本信息):下完才问的话,那几秒里用户以为卡住了
    origin = provenance.provenance_of(url, locale)
    done = _download_by_route(comfy, info, direct, folder, filename, locale, emit, sha256=sha256)
    provenance.record(comfy, folder, str(done.get("name") or filename), done.get("size"), {"how": "download", **origin})
    return {**done, "page": origin.get("page", "")}


def _download_by_route(comfy: Comfy, info: dict[str, list[str]], direct: str, folder: str, filename: str, locale: str,
                       emit: Emit, *, sha256: str = "") -> dict[str, Any]:
    local = _local_dir(info, folder) if same_machine(comfy, info) else None
    if local is not None:
        return via_local(local, direct, folder, filename, locale, emit, sha256=sha256)
    if sha256 and manager_version(comfy):
        #: 那条路是那台机器自己下,Mosael 拿不到字节、算不了哈希:宁可不下,也不装一个没核对过的。
        raise ComfyError(say(locale, "这个来源要下完核对 SHA256,得 Mosael 自己把文件写进模型目录;这台服务器只能经 "
                                       "ComfyUI-Manager 下,Mosael 核对不了,所以没下。用工作流里写的那个地址,或者把 "
                                       "Mosael 和 ComfyUI 装在同一台机器上。",
                             "This source is downloaded with a SHA256 check, which needs Mosael to write the file into the "
                             "model folder itself. This server can only download through ComfyUI-Manager, where Mosael "
                             "can't verify it, so nothing was downloaded. Use the address the workflow declares, or run "
                             "Mosael and ComfyUI on the same machine."))
    if manager_version(comfy):
        return via_manager(comfy, info, direct, folder, filename, locale, emit)
    raise ComfyError(_none_steps(locale, direct, folder, filename))
