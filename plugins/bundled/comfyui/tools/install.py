"""把一个模型下到这台 ComfyUI 上(ADR 0034 §3,2026-10-06 的后续调了 2、3 的先后)。按优先级,前一条走不通才试下一条:

1. ComfyUI 自己的下载接口 —— 0.38.0 没有(`/api/assets` 默认关着,里面也没有下载;官方前端缺模型时只是在浏览器里
   打开链接),今天不去探测不存在的接口;
2. **ComfyUI 和 Mosael 在同一台机器上**:它报的模型目录在本机存在、且本机的文件和它报的一致 → 直接写进去。先写
   `<名字>.mosael-part`,下完用硬链接挂上正式的名字(目标已存在就失败,不覆盖);按字节报进度;取消时删掉**自己的**
   半截文件;开始前查剩余空间。装了 Manager 也走这条:它看得到进度、停得下、令牌走请求头(不拼进地址、不留在
   Manager 的任务记录里),Manager 那条路一样都做不到(沙盒实测:本机 ComfyUI 装着 Manager,下载走了 Manager,
   没有进度 —— 和指南、下载框说的「这台电脑上的看得到进度」对不上);
3. **ComfyUI-Manager** 的装模型接口(`/v2/manager/version` 回 V4 时,ComfyUI 在另一台机器上):那台机器自己去下。不报
   字节进度,也没有停下单个任务的接口;它的安全策略只在 ComfyUI 监听回环地址、或 `network_mode = personal_cloud` 时
   才放行 —— 被拒时历史里只记一个 failed,原因在日志里(`/internal/logs/raw`),这里把它找出来说人话,并记下来;
4. 都走不通:如实说明,并给出能做的那一步。

    {"op": "download", "url", "folder", "filename"} → 流式:进度行;结果 {folder, name, size, route, page}

下成了就记下这个文件的来源(见 provenance):模型库的「原链接」、Civitai 的 NSFW 标记和示例图都从这里来。
"""

from __future__ import annotations

import os
import re
import shutil
import time
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable
from urllib import parse

import provenance
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
    """本机那条路写进哪个目录:那个模型目录报的第一处(不存在就在它的上一级存在时建出来)。"""
    paths = info.get(folder) or []
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

def _open_download(url: str, locale: str):
    """开始下:跟着跳转,每一跳只带那一跳的站自己的令牌。返回 (响应, 最终地址)。"""
    current = url
    for _ in range(sources.MAX_HOPS):
        response = sources.open_url(current, headers=sources.auth_for(current), timeout=60)
        status = getattr(response, "status", None) or getattr(response, "code", 0)
        location = response.headers.get("Location")
        if status in (301, 302, 303, 307, 308) and location:
            response.close()
            current = parse.urljoin(current, location)
            continue
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


def via_local(directory: Path, url: str, folder: str, filename: str, locale: str, emit: Emit) -> dict[str, Any]:
    directory.mkdir(exist_ok=True)
    final = directory / filename
    part = directory / f"{filename}.mosael-part"
    if final.exists():
        raise ComfyError(_same_name(locale, folder, filename))
    response, _final_url = _open_download(url, locale)
    written = 0
    try:
        kind = response.headers.get("Content-Type", "").lower()
        if kind.startswith("text/html"):
            raise ComfyError(say(locale, "下载地址回的是一个网页,不是模型文件(多半要登录:在这个连接的凭据里填那个站的令牌)",
                                 "The download link returned a web page, not a model file (it probably needs a login: enter "
                                 "that site's token in this connection's credentials)"))
        raw = response.headers.get("Content-Length", "")
        total = int(raw) if raw.isdigit() else 0
        if total:
            free = shutil.disk_usage(directory).free
            if free < total + DISK_MARGIN:
                raise ComfyError(say(locale, f"空间不够:{directory} 所在的磁盘只剩 {_human(free)},这个文件要 {_human(total)}",
                                     f"Not enough space: the disk holding {directory} has {_human(free)} left and this file "
                                     f"needs {_human(total)}"))
        started = last = time.monotonic()
        with part.open("wb") as handle:
            while True:
                if _cancelled():
                    raise ComfyError(say(locale, "已取消", "Cancelled"))
                # read1:有多少拿多少,不等凑满一块 —— 慢的时候取消也能马上生效
                chunk = response.read1(CHUNK) if hasattr(response, "read1") else response.read(CHUNK)
                if not chunk:
                    break
                handle.write(chunk)
                written += len(chunk)
                now = time.monotonic()
                if now - last >= PROGRESS_SECONDS:
                    last = now
                    speed = written / max(now - started, 0.001)
                    emit({"event": "progress", "progress": min(0.99, written / total) if total else 0.0,
                          "message": say(locale, f"已下载 {_human(written)}" + (f" / {_human(total)}" if total else "")
                                         + f" · {_human(speed)}/s",
                                         f"{_human(written)}" + (f" of {_human(total)}" if total else "")
                                         + f" downloaded · {_human(speed)}/s")})
        if total and written != total:
            raise ComfyError(say(locale, f"下到一半断了({_human(written)} / {_human(total)}),再试一次",
                                 f"The download broke off ({_human(written)} of {_human(total)}); try again"))
        _publish(part, final, locale, folder, filename)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    finally:
        response.close()
    emit({"event": "progress", "progress": 1.0,
          "message": say(locale, f"已下载 {_human(written)}", f"{_human(written)} downloaded")})
    return {"folder": folder, "name": filename, "size": written, "route": "local"}


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
    origin = sources.provenance_of(url, locale)
    done = _download_by_route(comfy, info, direct, folder, filename, locale, emit)
    provenance.record(comfy, folder, str(done.get("name") or filename), done.get("size"), {"how": "download", **origin})
    return {**done, "page": origin.get("page", "")}


def _download_by_route(comfy: Comfy, info: dict[str, list[str]], direct: str, folder: str, filename: str, locale: str,
                       emit: Emit) -> dict[str, Any]:
    local = _local_dir(info, folder) if same_machine(comfy, info) else None
    if local is not None:
        return via_local(local, direct, folder, filename, locale, emit)
    if manager_version(comfy):
        return via_manager(comfy, info, direct, folder, filename, locale, emit)
    raise ComfyError(_none_steps(locale, direct, folder, filename))
