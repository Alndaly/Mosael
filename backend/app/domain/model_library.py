"""模型库(ADR 0034):认领 `model_library` 的连接上有哪些模型文件 —— 宿主这一侧。

插件回答四件事(`op`):列出全部模型文件、一个文件的完整元数据、一个链接指的是什么、把它下到那台服务器上。宿主做的是
插件做不了、也不该做的那几样:

- **规整**:插件报的每一条都过一遍(没有目录或名字的丢掉、长文本截断、只认 http(s) 的声明地址),界面拿到的形状只有一种;
- **预览图**:插件给的是那台服务器上的地址(连同取它要带的头)。宿主按这个连接的出站决定去取、记进磁盘缓存,再交给界面 ——
  和插件交回 `url` 的产出同一个规矩;那一头的地址和凭据不进给界面的回答;
- **下载**:一个后台任务(`model_download`),进度、取消走流式协议;下完让这个连接的目录重新拉一遍,生成表单里选模型的
  下拉马上有它。

**这里不认识 ComfyUI**:任何认领 `model_library` 的连接,插件页上都有一行「模型库」。列表不存库(每次现问插件,插件自己
记着逐个读的元数据);宿主只在内存里记着「哪个文件的预览图在哪」,重启后界面直接要预览图时先替它列一遍。
"""

from __future__ import annotations

import hashlib
import io
import logging
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit

import httpx
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.i18n import LocalizedError, fragment
from app.core.unit_of_work import unit_of_work
from app.db.models import Job, PluginInstance, User
from app.domain import capabilities
from app.domain.jobs import create_job, dispatch_job, emit_job_event, finish_job, run_job_guarded, say
from app.domain.permissions import ensure_workspace_perm
from app.domain.plugins import egress as plugin_egress
from app.domain.plugins import host_capabilities
from app.domain.plugins import instances as inst
from app.domain.plugins import tools
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.manifest import MODEL_LIBRARY
from app.domain.plugins.runtime import PluginRuntimeError, StreamHooks
from app.domain.plugins.tools import MAX_GENERATION_TIMEOUT_SECONDS
from app.media.thumbnails import THUMBNAIL_MEDIA_TYPE, write_thumbnail

logger = logging.getLogger(__name__)

#: 下载任务的种类(见 job_catalog)。
KIND = "model_download"
#: 列一遍最多等多久。第一次要逐个读文件头(530 个文件、一次约 40ms),插件记下之后第二次只读目录。
LIBRARY_TIMEOUT_SECONDS = 600
#: 读一个文件的元数据、解析一个链接:一两个请求的事。
QUICK_TIMEOUT_SECONDS = 120
#: 一张预览图最大多少。ComfyUI 给的是转好的 webp,几十 KB;再大就不是预览图了。
PREVIEW_MAX_BYTES = 8 * 1024 * 1024
#: 那台服务器上没有预览图的,记多久不再去问(作者随时可能补一张同名图进去)。
NO_PREVIEW_SECONDS = 600
#: 卡片、列表行、生成表单下拉里那一枚用的缩略图:长边不超过这么多像素。卡片最宽两百来点,高清屏上翻倍也够清楚;
#: 解码一张是原图(常见 1200×1800、1800×2300)的十几分之一 —— 网格一屏几十张全解原图,滚动和悬停都卡。
THUMBNAIL_EDGE = 512
#: 同一个连接同时去那台服务器取几张预览图。ComfyUI 是在它唯一的事件循环里把预览图现转成 WebP 的,一次只转一张:
#: 多发的请求只是在它那边排队,还把它别的回答(队列、进度)压在后面。
REMOTE_FETCHES = 2
#: 模型库里列出最近几条下载(在跑的总在里面)。
RECENT_DOWNLOADS = 10

_MAX_MODELS = 20000
_MAX_LIST = 50
_MAX_TRIGGERS = 30
_MAX_METADATA_KEYS = 400
_MAX_METADATA_VALUE = 4000
_MAX_TAGS = 100


class ModelLibraryError(LocalizedError, ValueError):
    """模型库这一侧说不行(这个连接不提供模型库、文件名不对、链接不是 http(s))。带文案 key(`modelLibErr_*`)。"""


@dataclass
class _Snapshot:
    """最近一次列出来的:每个文件的预览图在那台服务器上的哪儿、取它要带的头。只在内存里。"""

    previews: dict[tuple[str, str], str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)


_lock = threading.Lock()
_snapshots: dict[str, _Snapshot] = {}
#: 一个连接一把:记着的地址没了时,同时到的几十个预览请求只让插件列一遍,别的等它列完。
_listing_locks: dict[str, threading.Lock] = {}
#: (连接, 预览地址) → 到这个时刻之前不再去问(那边说没有)。
_absent: dict[tuple[str, str], float] = {}
#: (连接, 预览地址) 一把:同一张图同时被要好几次时只去取一次(缩略图也只缩一次),别的等它落盘再读。
_fetch_locks: dict[tuple[str, str], threading.Lock] = {}
#: 一个连接一个:同时去那台服务器取的预览图不超过 REMOTE_FETCHES 张。
_remote_slots: dict[str, threading.BoundedSemaphore] = {}
#: 排队等取图名额时,隔多久问一次要图的人还在不在。
_WANTED_POLL_SECONDS = 0.25


class _PreviewNotNow(Exception):
    """这次没取到(那台机器回 5xx、连接断了、超时)—— 不是「没有预览图」,下次照常去取。"""


def forget(instance_id: str | None = None) -> None:
    """忘掉记着的预览图地址(一个连接,或全部)。连接变了(换了服务器)时调;测试用它模拟重启。"""
    with _lock:
        if instance_id is None:
            _snapshots.clear()
            _absent.clear()
            _fetch_locks.clear()
            _remote_slots.clear()
            return
        _snapshots.pop(instance_id, None)
        _remote_slots.pop(instance_id, None)
        for key in [key for key in _absent if key[0] == instance_id]:
            _absent.pop(key, None)
        for key in [key for key in _fetch_locks if key[0] == instance_id]:
            _fetch_locks.pop(key, None)


def drop_cache(instance_id: str) -> None:
    """连接删掉了:记着的地址和磁盘上的预览图一起清掉。"""
    forget(instance_id)
    shutil.rmtree(_preview_dir(instance_id), ignore_errors=True)


def _require(db: Session, instance: PluginInstance) -> None:
    if MODEL_LIBRARY not in inst.manifest_for(db, instance).provides:
        raise ModelLibraryError("modelLibErr_notProvided", name=instance.name)


def _text(value: Any, limit: int = 500) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _http(url: Any) -> str:
    """只认 http(s) 的地址;别的(`file://`、相对路径)当没给。"""
    text = _text(url, 4000)
    return text if urlsplit(text).scheme in ("http", "https") and urlsplit(text).hostname else ""


def _refs(value: Any) -> list[dict[str, str]]:
    """「哪几张工作流」:`[{id, label}]`。"""
    out: list[dict[str, str]] = []
    for one in value if isinstance(value, list) else []:
        if isinstance(one, dict) and _text(one.get("id")):
            out.append({"id": _text(one.get("id")), "label": _text(one.get("label")) or _text(one.get("id"))})
    return out[:_MAX_LIST]


def _model(raw: Any, base: str = "") -> tuple[dict[str, Any], str] | None:
    """插件报的一条模型文件 → 给界面的那一份,外加它的预览图地址(不交给界面)。"""
    if not isinstance(raw, dict):
        return None
    folder, name = _text(raw.get("folder"), 200), _text(raw.get("name"), 1000)
    if not folder or not name:
        return None
    size = _number(raw.get("size"))
    triggers = [_text(one, 200) for one in raw.get("triggers") or [] if _text(one, 200)][:_MAX_TRIGGERS]
    # 预览地址可以是相对 `preview_base` 的一段(几千个文件时省下回答的体积,插件的一次回答有上限)。
    preview = _http(urljoin(base, raw["preview"]) if base and isinstance(raw.get("preview"), str) else raw.get("preview"))
    return {
        "folder": folder,
        "name": name,
        "size": int(size) if size is not None else None,
        "modified": _number(raw.get("modified")),
        "family": _text(raw.get("family"), 80),
        "family_source": _text(raw.get("family_source"), 40),
        "triggers": triggers,
        "triggers_source": _text(raw.get("triggers_source"), 40) if triggers else "",
        "title": _text(raw.get("title"), 300),
        "has_preview": bool(preview),
        "used_by": _refs(raw.get("used_by")),
    }, preview


def library(db: Session, instance: PluginInstance) -> dict[str, Any]:
    """现问插件:这个连接上的全部模型文件,规整好交给界面;顺手记下每个文件的预览图在哪。"""
    _require(db, instance)
    # 不留调用记录:打开模型库、下完一个文件都会列一遍,每次一行会把插件页真正的调用淹掉(和目录指纹同一个理由)。
    output = tools.invoke_host(db, instance.id, MODEL_LIBRARY, {"op": "library"},
                               timeout=LIBRARY_TIMEOUT_SECONDS, record=False)
    models: list[dict[str, Any]] = []
    snapshot = _Snapshot(headers={str(k): str(v) for k, v in (output.get("preview_headers") or {}).items()})
    for raw in (output.get("models") or [])[:_MAX_MODELS]:
        found = _model(raw, _http(output.get("preview_base")))
        if found is None:
            continue
        model, preview = found
        models.append(model)
        if preview:
            snapshot.previews[(model["folder"], model["name"])] = preview
    with _lock:
        _snapshots[instance.id] = snapshot
    folders = [
        {"name": _text(one.get("name"), 200), "count": int(_number(one.get("count")) or 0)}
        for one in output.get("folders") or [] if isinstance(one, dict) and _text(one.get("name"), 200)
    ]
    missing = [
        {"folder": _text(one.get("folder"), 200), "name": _text(one.get("name"), 1000), "url": _http(one.get("url")),
         "workflows": _refs(one.get("workflows"))}
        for one in output.get("missing") or [] if isinstance(one, dict)
    ]
    route = output.get("download") if isinstance(output.get("download"), dict) else {}
    return {
        "folders": folders,
        "models": models,
        "missing": [one for one in missing if one["folder"] and one["name"] and one["url"]][:_MAX_LIST * 4],
        "download": {"route": _text(route.get("route"), 40) or "none", "note": _text(route.get("note"), 2000)},
        "downloads": downloads(db, instance),
    }


def _preview_dir(instance_id: str) -> Path:
    return settings.data_dir / "model-previews" / instance_id


@dataclass(frozen=True)
class _Cached:
    """一张预览图在磁盘上的那几个文件。按地址记:换了服务器、换了文件(ComfyUI 的地址里带着目录序号和名字)就是另一张。

    原图(`<key>`)和它的类型(`<key>.type`)是取回来的原样,详情页的大图用它;缩略图(`<key>.thumbnail.webp`)
    由原图缩出来,卡片、列表行、下拉用它。"""

    original: Path
    kind: Path
    thumbnail: Path

    @classmethod
    def of(cls, instance_id: str, url: str) -> _Cached:
        target = _preview_dir(instance_id) / hashlib.sha1(url.encode("utf-8")).hexdigest()
        return cls(target, target.with_name(f"{target.name}.type"), target.with_name(f"{target.name}.thumbnail.webp"))

    def read_original(self) -> tuple[bytes, str] | None:
        if self.original.is_file() and self.kind.is_file():
            return self.original.read_bytes(), self.kind.read_text(encoding="utf-8")
        return None

    def read_thumbnail(self) -> tuple[bytes, str] | None:
        return (self.thumbnail.read_bytes(), THUMBNAIL_MEDIA_TYPE) if self.thumbnail.is_file() else None


def _write(path: Path, content: bytes) -> None:
    """临时文件再换上去:读的人不会读到半截。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f"{path.name}.{uuid.uuid4().hex}.part")
    partial.write_bytes(content)
    partial.replace(path)


def _always() -> bool:
    return True


def preview_source(db: Session, instance: PluginInstance, folder: str, name: str) -> PreviewSource | None:
    """这个文件的预览图从哪儿取、记在哪儿;插件没给预览地址就是 None。**读库的只有这一步**:拿到它之后取图、缩图都不碰
    数据库 —— 调用方(路由)接着就把连接交还,再去等(见 PreviewSource)。"""
    _require(db, instance)
    snapshot = _snapshot_for(db, instance)
    url = snapshot.previews.get((folder, name)) if snapshot else None
    if not snapshot or not url:
        return None
    route = plugin_egress.resolve(db, instance, inst.manifest_for(db, instance))
    return PreviewSource(instance.id, url, dict(snapshot.headers), route, _Cached.of(instance.id, url))


@dataclass(frozen=True)
class PreviewSource:
    """一张预览图:那台服务器上的地址、取它要带的头、走哪条出站,磁盘上记在哪。

    缓存里没有时要排队(这张图的锁、这个连接的取图名额)、等那台服务器 —— 第一次打开模型库时一屏的请求同时到,滚一下
    又是一屏(滚出去的那些浏览器掐了,线程还在排队)。此前每个都攥着一条数据库连接排着,连接池(5 + 10)很快就空了,
    详情、任务列表这些请求要等满 30 秒才报错;现在等的这一段手里没有会话。"""

    instance_id: str
    url: str
    headers: dict[str, str]
    route: plugin_egress.Egress
    cached: _Cached

    def original(self, wanted: Callable[[], bool] = _always) -> tuple[bytes, str] | None:
        """原图(字节、类型),详情页的大图;没有就是 None。取回来的记在磁盘上,同一个地址第二次不再去取。
        `wanted`:要它的人还在不在(见 `_fetch`)。"""
        hit = self.cached.read_original()
        if hit is not None:
            return hit
        with self._gate():
            return self._fetch(wanted)

    def thumbnail(self, wanted: Callable[[], bool] = _always) -> tuple[bytes, str] | None:
        """缩略图(长边不超过 THUMBNAIL_EDGE 的 WebP,透明照留),卡片、列表和选模型的下拉用;没有预览图就是 None。

        第一次要的时候取原图(已经取过就用磁盘上那份)、缩一次,记在原图旁边;之后都从磁盘给。缩不出来(Pillow 不认识
        这种图)就给原图 —— 浏览器认得的话卡片照样有图,只是大一些。`wanted` 同上。"""
        hit = self.cached.read_thumbnail()
        if hit is not None:
            return hit
        with self._gate():
            # 等锁的这段时间里,先到的那个可能已经缩好了。
            hit = self.cached.read_thumbnail()
            if hit is not None:
                return hit
            original = self._fetch(wanted)
            if original is None:
                return None
            try:
                with Image.open(io.BytesIO(original[0])) as image:
                    buffer = io.BytesIO()
                    write_thumbnail(image, buffer, width=THUMBNAIL_EDGE, height=THUMBNAIL_EDGE)
            except (OSError, ValueError, Image.DecompressionBombError) as exc:
                logger.info("模型预览图缩不出缩略图(连接 %s),给原图:%s", self.instance_id, exc)
                return original
            _write(self.cached.thumbnail, buffer.getvalue())
            return buffer.getvalue(), THUMBNAIL_MEDIA_TYPE

    def _gate(self) -> threading.Lock:
        """这张图一把锁:同时被要好几次时只去取一次、只缩一次,别的等它落盘再读。"""
        with _lock:
            return _fetch_locks.setdefault((self.instance_id, self.url), threading.Lock())

    def _fetch(self, wanted: Callable[[], bool]) -> tuple[bytes, str] | None:
        """磁盘上的原图;没有就去那台服务器取一次、落盘。拿着这张图的锁调。

        去取要排队(一个连接同时取 REMOTE_FETCHES 张)。排着的时候、排到的时候都问 `wanted()`:人已经滚走了(浏览器掐了
        这个请求)就不取,也不记成「没有」—— 一路滚过去几百张卡,每张都发过一个请求;挨个去取的话,眼前这几张要排在它们
        后面等上几十秒。"""
        # 等锁的这段时间里,先到的那个可能已经取回落盘,或者问出了「没有」。
        hit = self.cached.read_original()
        if hit is not None:
            return hit
        key = (self.instance_id, self.url)
        with _lock:
            until = _absent.get(key, 0.0)
            slots = _remote_slots.setdefault(self.instance_id, threading.BoundedSemaphore(REMOTE_FETCHES))
        if until > time.monotonic():
            return None
        while not slots.acquire(timeout=_WANTED_POLL_SECONDS):
            if not wanted():
                return None
        try:
            if not wanted():
                return None
            fetched = _fetch_preview(self.instance_id, self.route, self.url, self.headers)
        except _PreviewNotNow:
            return None
        finally:
            slots.release()
        if fetched is None:
            with _lock:
                _absent[key] = time.monotonic() + NO_PREVIEW_SECONDS
            return None
        data, kind = fetched
        # 类型先落,读的人见到图就有类型。
        _write(self.cached.kind, kind.encode("utf-8"))
        _write(self.cached.original, data)
        return data, kind


def _snapshot_for(db: Session, instance: PluginInstance) -> _Snapshot | None:
    """记着的预览图地址;没有(重启了)就先列一遍。一屏的预览请求是同时到的:只有第一个去列,别的等它。"""
    with _lock:
        snapshot = _snapshots.get(instance.id)
        gate = _listing_locks.setdefault(instance.id, threading.Lock())
    if snapshot is not None:
        return snapshot
    with gate:
        with _lock:
            snapshot = _snapshots.get(instance.id)
        if snapshot is None:
            library(db, instance)
            with _lock:
                snapshot = _snapshots.get(instance.id)
    return snapshot


def _fetch_preview(
    instance_id: str, route: plugin_egress.Egress, url: str, headers: dict[str, str]
) -> tuple[bytes, str] | None:
    """按这个连接的出站决定(`route`)去取(和插件交回 `url` 的产出同一条路)。

    那边明确说没有(404 这类)、不是图、太大 → None,记成没有;那边一时出错(5xx、连接断了、超时)→ 抛
    _PreviewNotNow,这次不给、也不记成没有,下次照常去取。"""
    try:
        with httpx.Client(timeout=30, headers=headers, follow_redirects=True, **route.httpx_options(url)) as client:
            with client.stream("GET", url) as response:
                if response.status_code >= 500 or response.status_code == 429:
                    raise _PreviewNotNow(f"HTTP {response.status_code}")
                if response.status_code != 200:
                    return None
                kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if not kind.startswith("image/"):
                    return None
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > PREVIEW_MAX_BYTES:
                        return None
                    chunks.append(chunk)
                return b"".join(chunks), kind
    except httpx.HTTPError as exc:
        logger.info("模型预览图这次没取到(连接 %s):%s", instance_id, exc)
        raise _PreviewNotNow(str(exc)) from exc


def detail(db: Session, instance: PluginInstance, folder: str, name: str) -> dict[str, Any]:
    """一个文件的完整元数据:文件头里的全部标量(值截断)和训练标签(按出现次数)。"""
    _require(db, instance)
    output = tools.invoke_host(db, instance.id, MODEL_LIBRARY, {"op": "detail", "folder": folder, "name": name},
                               timeout=QUICK_TIMEOUT_SECONDS, record=False)
    raw = output.get("metadata") if isinstance(output.get("metadata"), dict) else {}
    metadata = {
        str(key)[:200]: (value if isinstance(value, str) else str(value))[:_MAX_METADATA_VALUE]
        for key, value in list(raw.items())[:_MAX_METADATA_KEYS]
        if isinstance(value, (str, int, float, bool))
    }
    tags = [
        {"tag": _text(one.get("tag"), 200), "count": int(_number(one.get("count")) or 0)}
        for one in output.get("tags") or [] if isinstance(one, dict) and _text(one.get("tag"), 200)
    ][:_MAX_TAGS]
    return {"folder": folder, "name": name, "metadata": metadata, "tags": tags}


def resolve(db: Session, instance: PluginInstance, url: str) -> dict[str, Any]:
    """一个链接指的是什么:直链、文件名、大小、建议的目录、同名文件在不在。认不出的由插件说原因。"""
    _require(db, instance)
    if not _http(url):
        raise ModelLibraryError("modelLibErr_badUrl")
    output = tools.invoke_host(db, instance.id, MODEL_LIBRARY, {"op": "resolve", "url": url.strip()},
                               timeout=QUICK_TIMEOUT_SECONDS)
    size = _number(output.get("size"))
    return {
        "source": _text(output.get("source"), 40),
        "url": _http(output.get("url")) or url.strip(),
        "page": _http(output.get("page")),
        "filename": _text(output.get("filename"), 300),
        "size": int(size) if size is not None else None,
        "folder": _text(output.get("folder"), 200),
        "family": _text(output.get("family"), 80),
        "triggers": [_text(one, 200) for one in output.get("triggers") or [] if _text(one, 200)][:_MAX_TRIGGERS],
        "title": _text(output.get("title"), 300),
        "exists": bool(output.get("exists")),
        "uses_token": bool(output.get("uses_token")),
        "note": _text(output.get("note"), 2000),
    }


def _plain_name(value: str, *, key: str) -> str:
    """文件名、目录名只能是一段:不带路径分隔符、不是 `.` / `..`、没有控制字符。"""
    text = (value or "").strip()
    if not text or text in (".", "..") or any(mark in text for mark in ("/", "\\", ":", "\x00")) or \
            any(ord(char) < 32 for char in text):
        raise ModelLibraryError(key, name=text)
    return text


def start_download(
    db: Session, user: User, instance: PluginInstance, *, workspace_id: str, url: str, folder: str, filename: str
) -> Job:
    """把一个模型下到这个连接的那台服务器上:一个后台任务。名字、目录、链接在这里先过一遍,不交给插件猜。"""
    _require(db, instance)
    if not _http(url):
        raise ModelLibraryError("modelLibErr_badUrl")
    folder = _plain_name(folder, key="modelLibErr_badFolder")
    filename = _plain_name(filename, key="modelLibErr_badFilename")
    ensure_workspace_perm(db, user, workspace_id, "edit")
    blocked = inst.blocked_reason(db, instance)
    if blocked:
        raise PluginDomainError("pluginErr_unavailable", name=instance.name, reason=blocked)
    job = create_job(
        db,
        workspace_id=workspace_id,
        kind="model_download",  # 和 KIND 同一个;任务目录的测试按字面量扫
        created_by=user.id,
        payload={"instance_id": instance.id, "url": url.strip(), "folder": folder, "filename": filename,
                 "subject": filename},
        message="jobMsg_modelDownloadQueued",
        message_params={"name": filename},
    )
    job_id = job.id
    dispatch_job(db, job, lambda: run_job_guarded(job_id, lambda: _download(job_id), what="模型下载"))
    return job


def _cancelled(job_id: str) -> bool:
    from app.core.db import SessionLocal
    from app.domain.jobs import was_cancelled

    #: 取消的任务在库里是 failed + jobErr_cancelled(见 jobs.was_cancelled)。
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        return job is None or was_cancelled(job) or job.status not in ("queued", "running")


def _download(job_id: str) -> None:
    """下载任务的身子。每一步一个短的 unit_of_work(在跑、每次进度、失败、刷新目录、成功):下载要跑几分钟到几小时,
    不攥着一个事务;状态都经 finish_job 写,中途的取消不会被盖掉。"""
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        payload = dict(job.payload or {})
        instance = db.get(PluginInstance, str(payload.get("instance_id") or ""))
        if instance is None:
            if finish_job(db, job, status="failed", error="", error_key="modelLibErr_instanceGone", error_params={}):
                say(job, "jobMsg_modelDownloadFailed", name=payload.get("filename", ""))
            return
        if not finish_job(db, job, status="running", progress=0.01):
            return
        say(job, "jobMsg_modelDownloadRunning", name=payload.get("filename", ""))
        emit_job_event(db, job.id, "job.running", {})
        instance_id = instance.id

    def on_progress(fraction: float, message: str) -> None:
        with unit_of_work() as db:
            job = db.get(Job, job_id)
            if job is None or not finish_job(db, job, status="running"):
                return
            job.progress = min(0.99, max(float(job.progress or 0.0), float(fraction)))
            if message:
                say(job, message[:200])

    hooks = StreamHooks(on_progress=on_progress, on_task=lambda _receipt: None, is_cancelled=lambda: _cancelled(job_id))
    request = {"op": "download", "url": payload["url"], "folder": payload["folder"], "filename": payload["filename"]}
    try:
        with unit_of_work() as db:
            output = tools.invoke_host(db, instance_id, MODEL_LIBRARY, request, hooks=hooks,
                                       timeout=MAX_GENERATION_TIMEOUT_SECONDS)
    except (PluginDomainError, PluginRuntimeError) as exc:
        from app.domain.jobs import blame

        with unit_of_work() as db:
            job = db.get(Job, job_id)
            if job is not None and finish_job(db, job, status="failed", **blame(exc)):
                say(job, "jobMsg_modelDownloadFailed", name=payload["filename"])
                emit_job_event(db, job.id, "job.failed", {})
        return
    size = _number(output.get("size"))
    result = {
        "folder": _text(output.get("folder"), 200) or payload["folder"],
        "name": _text(output.get("name"), 1000) or payload["filename"],
        "size": int(size) if size is not None else None,
        "route": _text(output.get("route"), 40),
    }
    # 先让这个连接的目录(模型、工具)重新问一遍插件,再说「下完了」:任务说能选的时候,生成表单的下拉里就该有它。
    # 刷新失败只记在目录自己的状态里(插件页看得到),不把一次下成了的下载判失败。
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        if job is None or not finish_job(db, job, status="running"):
            return
        say(job, "jobMsg_modelDownloadRefreshing", name=result["name"])
    with unit_of_work() as db:
        instance = db.get(PluginInstance, instance_id)
        if instance is not None:
            host_capabilities.notify(db, instance, refresh=True)
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        if job is not None and finish_job(db, job, status="succeeded", progress=1.0, result=result):
            say(job, "jobMsg_modelDownloadDone", name=result["name"], folder=result["folder"])
            emit_job_event(db, job.id, "job.succeeded", dict(result))


def downloads(db: Session, instance: PluginInstance) -> list[Job]:
    """这个连接最近的下载任务(在跑的总在里面),新的在前。"""
    rows = db.scalars(select(Job).where(Job.kind == KIND).order_by(Job.created_at.desc()).limit(200))
    mine = [job for job in rows if (job.payload or {}).get("instance_id") == instance.id]
    active = [job for job in mine if job.status in ("queued", "running")]
    finished = [job for job in mine if job.status not in ("queued", "running")]
    return active + finished[: max(0, RECENT_DOWNLOADS - len(active))]


def _on_instance_change(_db: Session, instance: PluginInstance, refresh: bool) -> None:
    """连接变了(换了服务器、刷新):记着的预览图地址作废,下一次列的时候重记。磁盘缓存按地址记,不用清。"""
    if refresh:
        forget(instance.id)


#: 能力表里的 `model_library`(ADR 0034):不走能力表的挑法(每个连接各有各的模型文件),登记它是为了叫得出名字、
#: 说得出用在哪,连接变了时作废记着的预览图地址。
CAPABILITY = capabilities.Capability(
    name=MODEL_LIBRARY,
    label_key="capability_model_library",
    description_key="capability_model_library",
    pickable=False,
    on_instance_change=_on_instance_change,
)


def register_uses() -> None:
    capabilities.register_use(capabilities.Use(MODEL_LIBRARY, "app", fragment("capUse_modelLibrary")))


__all__ = [
    "CAPABILITY",
    "KIND",
    "ModelLibraryError",
    "PreviewSource",
    "detail",
    "downloads",
    "drop_cache",
    "forget",
    "library",
    "preview_source",
    "register_uses",
    "resolve",
    "start_download",
]
