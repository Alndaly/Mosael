"""模型库的预览图(ADR 0034 §1、ADR 0038 §9):一个模型文件在 Mosael 里显示哪一张、从哪儿取、记在哪儿。

一个文件的预览图有两处来,先后试:

1. **那台服务器上的**:插件给的地址(ComfyUI 的预览接口),连同取它要带的头;再是插件列的「旁边的文件」(和模型同名的
   `.mp4` / `.webm` 预览视频,文件名带 `[ ]`、ComfyUI 的预览接口按通配符找不到的那几张图),按名字直接读;
2. **别处的示例图**:插件在 Civitai 上对上了这个文件的版本时,交来几张示例图的地址(示例只有视频的就是视频)。那台服务器上
   没有预览图,Mosael 就用其中一张(怎么挑见 `pick`),界面角上标「来自 Civitai」;用户点「存为预览图」才写回那台服务器。

**预览视频**:取回来就用 ffmpeg 转成一段宽不超过 512、静音、最长十秒的 mp4 记在缓存里(Civitai 没转好时给的是原片,十来
MB、带声音);卡片上的缩略图是它的第一帧,悬停时播的、详情里播的、写回那台服务器的都是这一段。

那台服务器上有没有,**取了才知道**(新版 ComfyUI 给每个文件都报一个预览地址,没有就 404)。取过的结果记在磁盘上
(`<数据目录>/model-previews/<连接>/server-previews.json`):宿主重启之后,模型库照样知道哪几个该显示别处的那张;
说没有的,十分钟之内不再去问(作者随时可能补一张同名图进去)。

取回来的都按地址记在磁盘缓存里(同一个目录,文件名是地址的哈希),缩略图由原图缩出来记在旁边 —— 换了服务器、换了文件、
换了一张示例图都是另一个地址、另一份缓存。**这里不认识 ComfyUI,也不认识 Civitai**:地址、头、哪张是哪种都是插件给的。
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import shutil
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx
from PIL import Image

from app.core.child_process import run_logged
from app.core.config import settings
from app.domain.plugins import egress as plugin_egress
from app.media.thumbnails import THUMBNAIL_MEDIA_TYPE, write_thumbnail

logger = logging.getLogger(__name__)

#: 一张预览图最大多少。ComfyUI 给的是转好的 webp,几十 KB;Civitai 的示例图要的是 512 宽的那一份,一两百 KB。
PREVIEW_MAX_BYTES = 8 * 1024 * 1024
#: 一段预览视频取回来最大多少:Civitai 转好的 512 宽一般几百 KB 到几 MB;它没转好时给的是原片,十来 MB。
VIDEO_MAX_BYTES = 64 * 1024 * 1024
#: 缓存(和写回)的预览视频:宽不超过这么多、最长几秒、静音 —— 卡片上循环播的,不是看片。
VIDEO_EDGE = 512
VIDEO_SECONDS = 10
#: 那台服务器上没有预览图的,记多久不再去问(作者随时可能补一张同名图进去)。
NO_PREVIEW_SECONDS = 600
#: 卡片、列表行、生成表单下拉里那一枚用的缩略图:长边不超过这么多像素。卡片最宽两百来点,高清屏上翻倍也够清楚;
#: 解码一张是原图(常见 1200×1800、1800×2300)的十几分之一 —— 网格一屏几十张全解原图,滚动和悬停都卡。
THUMBNAIL_EDGE = 512
#: 同一个连接同时去那台服务器取几张预览图。ComfyUI 是在它唯一的事件循环里把预览图现转成 WebP 的,一次只转一张:
#: 多发的请求只是在它那边排队,还把它别的回答(队列、进度)压在后面。
SERVER_FETCHES = 2
#: 同时去别处(Civitai 的图床)取几张。全进程一份:那是别人的站,别一口气几十个。
ELSEWHERE_FETCHES = 3
#: 挑哪一张别处的示例图:`safest` 分级最低的(缺省),`cover` 作者排在最前的那张。
PICKS = ("safest", "cover")
#: 排队等取图名额时,隔多久问一次要图的人还在不在。
_WANTED_POLL_SECONDS = 0.25

_lock = threading.Lock()
#: (连接, 地址) 一把:同一张图同时被要好几次时只去取一次(缩略图也只缩一次),别的等它落盘再读。
_fetch_locks: dict[tuple[str, str], threading.Lock] = {}
#: 取图名额:一个连接一份(那台服务器),别处全进程一份。
_slots: dict[str, threading.BoundedSemaphore] = {}
#: 每个连接「那台服务器上谁有预览图」的索引(读过一次留在内存里,改了就写回磁盘)。
_indexes: dict[str, dict[str, dict[str, Any]]] = {}


class PreviewNotNow(Exception):
    """这次没取到(那台机器回 5xx、连接断了、超时)—— 不是「没有预览图」,下次照常去取。"""


def preview_dir(instance_id: str) -> Path:
    return settings.data_dir / "model-previews" / instance_id


def forget(instance_id: str | None = None) -> None:
    """忘掉内存里记着的(一个连接,或全部):锁、名额、索引的内存那一份(磁盘上的索引留着,下次用到再读)。"""
    with _lock:
        if instance_id is None:
            _fetch_locks.clear()
            _slots.clear()
            _indexes.clear()
            return
        _slots.pop(f"server:{instance_id}", None)
        _indexes.pop(instance_id, None)
        for key in [key for key in _fetch_locks if key[0] == instance_id]:
            _fetch_locks.pop(key, None)


def drop_cache(instance_id: str) -> None:
    """连接删掉了:内存里的和磁盘上的预览图、索引一起清掉。"""
    forget(instance_id)
    shutil.rmtree(preview_dir(instance_id), ignore_errors=True)


# --- 别处的示例图 -------------------------------------------------------------------

@dataclass(frozen=True)
class Elsewhere:
    """插件交来的一张别处的示例图(或一段示例视频):地址、种类、是哪个站的、那个站给它的分级,以及插件说它算不算 NSFW。"""

    url: str
    kind: str
    site: str
    level: int
    nsfw: bool


def elsewhere(value: Any) -> list[Elsewhere]:
    """插件报的 `remote_previews` 规整成一种形状。只认 http(s) 的地址(和那台服务器上的预览地址同一条);种类是
    image / video。"""
    out: list[Elsewhere] = []
    for raw in value if isinstance(value, list) else []:
        if not isinstance(raw, dict) or not isinstance(raw.get("url"), str):
            continue
        url = raw["url"].strip()[:2000]
        parts = urlsplit(url)
        kind = str(raw.get("kind") or "")
        if parts.scheme not in ("http", "https") or not parts.hostname or kind not in ("image", "video"):
            continue
        level = raw.get("level")
        out.append(Elsewhere(url, kind, str(raw.get("site") or "")[:40],
                             int(level) if isinstance(level, int) and not isinstance(level, bool) else 0,
                             bool(raw.get("nsfw"))))
    return out[:12]


def pick(choices: list[Elsewhere], how: str) -> Elsewhere | None:
    """挑哪一张当 Mosael 里显示的预览图(界面按「NSFW 预览」那组设置要:照常要 `cover`,别的要 `safest`):
    `cover` 是作者排在最前的那张;`safest` 是分级最低的那张,一样低取靠前的。有图就在图里挑,示例只有视频的才用视频。"""
    pool = [one for one in choices if one.kind == "image"] or [one for one in choices if one.kind == "video"]
    if not pool:
        return None
    if how == "cover":
        return pool[0]
    return min(pool, key=lambda one: (one.level or 99, pool.index(one)))


# --- 那台服务器上谁有预览图 --------------------------------------------------------

def _index_path(instance_id: str) -> Path:
    return preview_dir(instance_id) / "server-previews.json"


def _index(instance_id: str) -> dict[str, dict[str, Any]]:
    """拿着 `_lock` 调。"""
    found = _indexes.get(instance_id)
    if found is None:
        try:
            loaded = json.loads(_index_path(instance_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            loaded = {}
        found = {key: value for key, value in loaded.items() if isinstance(value, dict)} if isinstance(loaded, dict) else {}
        _indexes[instance_id] = found
    return found


def _key(folder: str, name: str) -> str:
    return f"{folder}\n{name.replace(chr(92), '/')}"


def server_status(instance_id: str, folder: str, name: str) -> str:
    """那台服务器上有没有这个文件的预览图:`found` / `absent` / ``(还没取过)。"""
    with _lock:
        entry = _index(instance_id).get(_key(folder, name)) or {}
    return str(entry.get("status") or "")


def server_kind(instance_id: str, folder: str, name: str) -> str:
    """那台服务器上那张预览是图还是视频(`image` / `video`);没取到过是空串。"""
    with _lock:
        entry = _index(instance_id).get(_key(folder, name)) or {}
    return str(entry.get("kind") or "")


def note_server(instance_id: str, folder: str, name: str, status: str, kind: str = "") -> None:
    """记下那台服务器上有没有(`found` / `absent`;空串是忘掉,下次重新去问),有的话是图还是视频。"""
    with _lock:
        index = _index(instance_id)
        key = _key(folder, name)
        if status:
            index[key] = {"status": status, "at": time.time(), **({"kind": kind} if kind else {})}
        else:
            index.pop(key, None)
        snapshot = json.dumps(index, ensure_ascii=False)
    try:
        _write(_index_path(instance_id), snapshot.encode("utf-8"))
    except OSError:
        logger.info("模型预览图的索引没写下(连接 %s)", instance_id)


def _recently_absent(instance_id: str, folder: str, name: str) -> bool:
    with _lock:
        entry = _index(instance_id).get(_key(folder, name)) or {}
    return entry.get("status") == "absent" and time.time() - float(entry.get("at") or 0) < NO_PREVIEW_SECONDS


# --- 磁盘缓存 -----------------------------------------------------------------------

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
        target = preview_dir(instance_id) / hashlib.sha1(url.encode("utf-8")).hexdigest()
        return cls(target, target.with_name(f"{target.name}.type"), target.with_name(f"{target.name}.thumbnail.webp"))

    def read_original(self) -> tuple[bytes, str] | None:
        if self.original.is_file() and self.kind.is_file():
            return self.original.read_bytes(), self.kind.read_text(encoding="utf-8")
        return None

    def read_thumbnail(self) -> tuple[bytes, str] | None:
        return (self.thumbnail.read_bytes(), THUMBNAIL_MEDIA_TYPE) if self.thumbnail.is_file() else None


def cached_original(instance_id: str, urls: list[str]) -> tuple[Path, str] | None:
    """这几处(按先后)里头一个已经取回来的原样(文件、类型);都没有就是 None。本机识别按它记结果(见 model_nsfw_local)。"""
    for url in urls:
        cached = _Cached.of(instance_id, url)
        if cached.original.is_file() and cached.kind.is_file():
            return cached.original, cached.kind.read_text(encoding="utf-8")
    return None


def _write(path: Path, content: bytes) -> None:
    """临时文件再换上去:读的人不会读到半截。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f"{path.name}.{uuid.uuid4().hex}.part")
    partial.write_bytes(content)
    partial.replace(path)


def _always() -> bool:
    return True


# --- 一个文件的预览图 -----------------------------------------------------------------

@dataclass(frozen=True)
class Media:
    """一个能取的地址:取它要带的头;`server` 是那台服务器上的(取不到要在索引里记一笔),否则是别处的(不带那台服务器的头)。"""

    url: str
    headers: dict[str, str]
    server: bool


@dataclass(frozen=True)
class PreviewSource:
    """一个文件的预览图从哪儿取:先那台服务器上的、再别处的那张(`candidates`),走这个连接的出站。

    缓存里没有时要排队(这张图的锁、取图名额)、等对方 —— 第一次打开模型库时一屏的请求同时到,滚一下又是一屏(滚出去的
    那些浏览器掐了,线程还在排队)。此前每个都攥着一条数据库连接排着,连接池很快就空了;现在等的这一段手里没有会话
    (路由先拿到它、交还连接,再来取)。"""

    instance_id: str
    folder: str
    name: str
    candidates: tuple[Media, ...]
    route: plugin_egress.Egress
    #: 卡片第一次露面(缩略图刚缩出来)时告诉谁:(原样文件、它的类型、是不是那台服务器上的)。本机识别据此排队,不等下一次
    #: 列 —— 这里不认识本机识别,由组装它的模型库接上(见 model_library.preview_source)
    on_thumbnail: Callable[[Path, str, bool], None] | None = None

    def _live(self) -> list[Media]:
        """这一次要试的:那台服务器上的刚说过没有(十分钟内),就跳过它。"""
        skip = _recently_absent(self.instance_id, self.folder, self.name)
        return [one for one in self.candidates if not (one.server and skip)]

    def original(self, wanted: Callable[[], bool] = _always) -> tuple[bytes, str] | None:
        """原图(字节、类型),详情页的大图(视频就是那段视频);没有就是 None。取回来的记在磁盘上,同一个地址第二次不再
        去取。`wanted`:要它的人还在不在(见 `_fetch`)。"""
        return self._first(wanted, thumbnail=False)

    def thumbnail(self, wanted: Callable[[], bool] = _always) -> tuple[bytes, str] | None:
        """缩略图(长边不超过 THUMBNAIL_EDGE 的 WebP,透明照留;视频是它的第一帧),卡片、列表和选模型的下拉用;没有
        预览图就是 None。

        第一次要的时候取原图(已经取过就用磁盘上那份)、缩一次,记在原图旁边;之后都从磁盘给。缩不出来(Pillow 不认识
        这种图)就给原图 —— 浏览器认得的话卡片照样有图,只是大一些。`wanted` 同上。"""
        return self._first(wanted, thumbnail=True)

    def _first(self, wanted: Callable[[], bool], *, thumbnail: bool) -> tuple[bytes, str] | None:
        """按先后试每一处,头一个有的就是它。那台服务器上的几处(预览接口、旁边的文件)都明说没有,才在索引里记一笔
        「没有」;这次没取到(忙、断了)的不记。"""
        live = self._live()
        #: 那台服务器上的几处是不是都明说了没有(这次没取到的、缓存里有的不算)
        missing_on_server = any(one.server for one in live)
        noted = False
        for media in live:
            if not media.server and missing_on_server and not noted:
                # 轮到别处的了:那台服务器上的都问过、都说没有 —— 先记下,列表据此说「来自 Civitai」
                note_server(self.instance_id, self.folder, self.name, "absent")
                noted = True
            cached = _Cached.of(self.instance_id, media.url)
            hit = cached.read_thumbnail() if thumbnail else cached.read_original()
            if hit is not None:
                return hit
            with self._gate(media):
                # 等锁的这段时间里,先到的那个可能已经取回、缩好了。
                hit = cached.read_thumbnail() if thumbnail else cached.read_original()
                if hit is not None:
                    return hit
                original, definitely_missing = self._fetch(media, wanted)
                if media.server and not definitely_missing:
                    missing_on_server = False
                if original is None:
                    continue
                if media.server:
                    note_server(self.instance_id, self.folder, self.name, "found",
                                "video" if original[1].startswith("video/") else "image")
                if not thumbnail:
                    return original
                shrunk = _shrink(self.instance_id, cached, original)
                if self.on_thumbnail is not None:
                    self.on_thumbnail(cached.original, original[1], media.server)
                return shrunk
        if missing_on_server and not noted:
            note_server(self.instance_id, self.folder, self.name, "absent")
        return None

    def _gate(self, media: Media) -> threading.Lock:
        """一个地址一把锁:同时被要好几次时只去取一次、只缩一次,别的等它落盘再读。"""
        with _lock:
            return _fetch_locks.setdefault((self.instance_id, media.url), threading.Lock())

    def _fetch(self, media: Media, wanted: Callable[[], bool]) -> tuple[tuple[bytes, str] | None, bool]:
        """磁盘上的原图;没有就去取一次、落盘(视频先转成缓存的那一段)。拿着这个地址的锁调。回 (取到的, 对方是不是明说
        没有)。

        去取要排队(取图名额)。排着的时候、排到的时候都问 `wanted()`:人已经滚走了(浏览器掐了这个请求)就不取,也不记成
        「没有」—— 一路滚过去几百张卡,每张都发过一个请求;挨个去取的话,眼前这几张要排在它们后面等上几十秒。"""
        cached = _Cached.of(self.instance_id, media.url)
        hit = cached.read_original()
        if hit is not None:
            return hit, False
        if media.server and _recently_absent(self.instance_id, self.folder, self.name):
            return None, True  # 等锁的这段时间里,先到的那个问出了「没有」
        slot = f"server:{self.instance_id}" if media.server else "elsewhere"
        with _lock:
            slots = _slots.setdefault(slot, threading.BoundedSemaphore(SERVER_FETCHES if media.server else ELSEWHERE_FETCHES))
        while not slots.acquire(timeout=_WANTED_POLL_SECONDS):
            if not wanted():
                return None, False
        try:
            if not wanted():
                return None, False
            fetched = fetch_media(self.instance_id, self.route, media.url, media.headers)
        except PreviewNotNow:
            return None, False
        finally:
            slots.release()
        if fetched is None:
            return None, True
        data, kind = fetched
        if kind.startswith("video/"):
            data, kind = _cacheable_video(data) or (data, kind)
        # 类型先落,读的人见到图就有类型。
        _write(cached.kind, kind.encode("utf-8"))
        _write(cached.original, data)
        return (data, kind), False


def _ffmpeg(args: list[str], *, what: str) -> bool:
    try:
        run_logged([settings.ffmpeg, "-y", "-v", "error", *args], check=True, capture_output=True, timeout=120, what=what)
    except Exception as exc:  # noqa: BLE001 — ffmpeg 不在、片子坏了:这一段不转,照原样
        logger.info("模型预览视频%s没成:%s", what, exc)
        return False
    return True


def _cacheable_video(data: bytes) -> tuple[bytes, str] | None:
    """一段预览视频 → 缓存的那一段:宽不超过 VIDEO_EDGE、最长 VIDEO_SECONDS 秒、静音、H.264、moov 在前(边下边播)。
    转不了就是 None(照原样存)。"""
    with tempfile.TemporaryDirectory(prefix="mosael-model-preview-") as tmp:
        source, target = Path(tmp) / "in", Path(tmp) / "out.mp4"
        source.write_bytes(data)
        ok = _ffmpeg(["-i", str(source), "-t", str(VIDEO_SECONDS), "-an",
                      "-vf", f"scale='min({VIDEO_EDGE},iw)':-2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                      "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(target)], what="转码")
        return (target.read_bytes(), "video/mp4") if ok and target.is_file() and target.stat().st_size else None


def first_frame(data: bytes) -> Image.Image | None:
    """一段视频的第一帧(卡片上的缩略图、本机识别看的那一帧),无损解出来的。"""
    with tempfile.TemporaryDirectory(prefix="mosael-model-preview-") as tmp:
        source, frame = Path(tmp) / "in", Path(tmp) / "frame.png"
        source.write_bytes(data)
        if not _ffmpeg(["-i", str(source), "-frames:v", "1", str(frame)], what="取首帧") or not frame.is_file():
            return None
        with Image.open(frame) as image:
            image.load()
            return image.copy()


def _shrink(instance_id: str, cached: _Cached, original: tuple[bytes, str]) -> tuple[bytes, str]:
    try:
        if original[1].startswith("video/"):
            image = first_frame(original[0])
            if image is None:
                return original
        else:
            image = Image.open(io.BytesIO(original[0]))
        with image:
            buffer = io.BytesIO()
            write_thumbnail(image, buffer, width=THUMBNAIL_EDGE, height=THUMBNAIL_EDGE)
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        logger.info("模型预览图缩不出缩略图(连接 %s),给原图:%s", instance_id, exc)
        return original
    _write(cached.thumbnail, buffer.getvalue())
    return buffer.getvalue(), THUMBNAIL_MEDIA_TYPE


def fetch_media(instance_id: str, route: plugin_egress.Egress, url: str, headers: dict[str, str]) -> tuple[bytes, str] | None:
    """按这个连接的出站决定(`route`)去取(和插件交回 `url` 的产出同一条路)。

    那边明确说没有(404 这类)、不是图、太大 → None,记成没有;那边一时出错(5xx、限流、连接断了、超时)→ 抛
    PreviewNotNow,这次不给、也不记成没有,下次照常去取。"""
    try:
        with httpx.Client(timeout=30, headers=headers, follow_redirects=True, **route.httpx_options(url)) as client:
            with client.stream("GET", url) as response:
                if response.status_code >= 500 or response.status_code == 429:
                    raise PreviewNotNow(f"HTTP {response.status_code}")
                if response.status_code != 200:
                    return None
                kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if not kind.startswith(("image/", "video/")):
                    return None
                limit = VIDEO_MAX_BYTES if kind.startswith("video/") else PREVIEW_MAX_BYTES
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > limit:
                        return None
                    chunks.append(chunk)
                return b"".join(chunks), kind
    except httpx.HTTPError as exc:
        logger.info("模型预览图这次没取到(连接 %s):%s", instance_id, exc)
        raise PreviewNotNow(str(exc)) from exc


def save_ready(source: tuple[bytes, str]) -> tuple[bytes, str]:
    """要写回那台服务器的那一份:图缩到 512 宽(示例图常是一两千像素的原图)存成 PNG —— ComfyUI 自己的列表、
    ComfyUI-Custom-Scripts 都认 PNG;视频就是缓存里那一段(512 宽、静音的 mp4),写成 `<模型名>.mp4`(维护者:「直接用
    视频当预览」,不另截一帧)。缩不了(不是图)就原样。回 (字节, 扩展名)。"""
    data, kind = source
    if kind.startswith("video/"):
        return data, ".mp4" if kind == "video/mp4" else ".webm" if kind == "video/webm" else ".mp4"
    try:
        with Image.open(io.BytesIO(data)) as image:
            image = image.convert("RGBA" if image.mode in ("RGBA", "LA", "P") else "RGB")
            if image.width > THUMBNAIL_EDGE:
                image = image.resize((THUMBNAIL_EDGE, max(1, round(image.height * THUMBNAIL_EDGE / image.width))),
                                     Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, "PNG", optimize=True)
            return buffer.getvalue(), ".png"
    except (OSError, ValueError, Image.DecompressionBombError):
        suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(kind, "")
        return data, suffix
