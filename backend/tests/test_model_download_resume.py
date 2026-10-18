"""模型下载的断点续传:HTTP Range、`.mosael-part` + sidecar、206 / 200 / 416、孤儿清理。

这里钉的是插件自己的下载那一段(`plugins/bundled/comfyui/tools/install.py` 的 `via_local`),用的是**本机一个真的
HTTP 服务** —— 不是 monkeypatch 出来的响应:要断言的正是请求上带没带 `Range`/`If-Range`、服务端回 206 时接在哪、
回 200 时有没有把整包接在半截后面。

口径(维护者 2026-10-19 裁的,取代此前「取消/失败就删 `.part`」):

- 取消 / 失败 / 后端重启:`.part` **留着**,旁边有 `<名字>.mosael-part.json` 记着源 URL、总大小、ETag /
  Last-Modified、声明的 SHA256 —— 续传前核对,不一致就重下;
- 「继续下载」= 带着 `Range: bytes=<已下>-` 再下;服务端回 206 就接着写,回 200(不支持 Range)就**截断重下**,
  416(Range 越界)能校验就校验、不能就删了重下;
- 「删除没下完的部分」是**另一个明确的动作**(`discard_partial`),只有它删 `.part`;
- 超过 `PART_MAX_AGE_DAYS` 天的孤儿 `.part` 才在开始下一次本机下载时扫掉。

先红的证据:这一版(519303bf5)取消就删 `.part`、下次从 0 开始 —— 下面的 `test_中断后从已下字节继续` 会在
「第二次请求没有 Range」上失败,`test_取消后保留半截` 会在「目录里没有 .part」上失败。
"""

from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui" / "tools"
#: 插件模块名都是短名,和别的测试文件共用一个进程时要换进换出(见同目录别的插件测试)。
_MODULES = ("graph", "convert", "labels", "models", "run", "lines", "ws", "comfy_http", "main", "server", "service",
            "shared_models", "workflows", "tooling", "library", "sources", "install", "families", "weights",
            "model_files", "civitai", "nsfw", "provenance", "lookup", "previews")


@pytest.fixture
def install(monkeypatch: pytest.MonkeyPatch):
    saved = {name: sys.modules.pop(name) for name in _MODULES if name in sys.modules}
    sys.path.insert(0, str(TOOLS))
    try:
        import install as module

        yield module
    finally:
        sys.path.remove(str(TOOLS))
        for name in _MODULES:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


class _Site:
    """本机一个真的模型站。

    - `cut_at`:第一次回答只发这么多字节就断开(模拟网络断了 / 进程被强杀);
    - `ignore_range`:永远回 200 整包(服务端不支持 Range);
    - `honor_if_range`:回 206 前先看 `If-Range`;关掉它就能模拟「回了 206,但文件其实已经换了」的坏服务端;
    - `always_416`:对带 Range 的请求回 416;
    - `etag` / `last_modified`:校验器,可以在两次下载之间改(模拟文件被重新发布)。
    """

    def __init__(self, body: bytes, *, etag: str = '"v1"', last_modified: str = "Wed, 01 Oct 2025 00:00:00 GMT",
                 cut_at: int | None = None, ignore_range: bool = False, honor_if_range: bool = True,
                 always_416: bool = False, slow: bool = False) -> None:
        self.body = body
        self.etag = etag
        self.last_modified = last_modified
        self.cut_at = cut_at
        self.ignore_range = ignore_range
        self.honor_if_range = honor_if_range
        self.always_416 = always_416
        self.slow = slow
        self.requests: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:  # noqa: N802
                outer._serve(self)

            def log_message(self, *_args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/file.safetensors"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self._thread.join(timeout=30)

    def _serve(self, handler: BaseHTTPRequestHandler) -> None:
        with self._lock:
            self.requests.append({"range": handler.headers.get("Range"),
                                  "if_range": handler.headers.get("If-Range"),
                                  "accept_encoding": handler.headers.get("Accept-Encoding")})
            body = self.body
            etag = self.etag
            last_modified = self.last_modified
            cut_at = self.cut_at
            #: 只断第一次:第二次(续传)要能下完,否则断言不了最终哈希。
            if cut_at is not None:
                self.cut_at = None
        range_header = handler.headers.get("Range")
        start = 0
        if range_header and range_header.startswith("bytes=") and range_header.endswith("-"):
            try:
                start = int(range_header[len("bytes="):-1])
            except ValueError:
                start = 0
        if range_header and (self.always_416 or start >= len(body)):
            handler.send_response(416)
            handler.send_header("Content-Range", f"bytes */{len(body)}")
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return
        if range_header and not self.ignore_range and start < len(body):
            if self.honor_if_range:
                if_range = handler.headers.get("If-Range")
                if if_range and if_range not in (etag, last_modified):
                    start = 0  # 校验器对不上:服务端自己回整包,客户端必须截断重下
            if start or range_header:
                handler.send_response(206)
                handler.send_header("Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}")
                handler.send_header("Content-Length", str(len(body) - start))
                handler.send_header("Content-Type", "application/octet-stream")
                handler.send_header("ETag", etag)
                handler.send_header("Last-Modified", last_modified)
                handler.end_headers()
                payload = body[start:]
                if cut_at is not None:
                    payload = payload[: max(0, cut_at - start)]
                    handler.close_connection = True
                self._write(handler, payload)
                return
        handler.send_response(200)
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Content-Type", "application/octet-stream")
        handler.send_header("ETag", etag)
        handler.send_header("Last-Modified", last_modified)
        handler.end_headers()
        payload = body[:cut_at] if cut_at is not None else body
        if cut_at is not None:
            handler.close_connection = True
        self._write(handler, payload)

    def _write(self, handler: BaseHTTPRequestHandler, payload: bytes) -> None:
        try:
            for offset in range(0, len(payload), 4096):
                handler.wfile.write(payload[offset:offset + 4096])
                handler.wfile.flush()
                if self.slow:
                    time.sleep(0.02)
        except (BrokenPipeError, ConnectionResetError):
            pass


@pytest.fixture
def sites():
    made: list[_Site] = []

    def make(body: bytes, **options: Any) -> _Site:
        site = _Site(body, **options)
        made.append(site)
        return site

    yield make
    for site in made:
        site.close()


def _events(install, site: _Site, directory: Path, filename: str = "big.safetensors", *, sha256: str = "",
            on_progress=None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    collected: list[dict[str, Any]] = []

    def emit(event: dict[str, Any]) -> None:
        collected.append(event)
        if on_progress is not None:
            on_progress(event)

    result = install.via_local(directory, site.url, "loras", filename, "zh", emit, sha256=sha256)
    return result, collected


def _part(directory: Path, filename: str = "big.safetensors") -> Path:
    return directory / f"{filename}.mosael-part"


def _sidecar(directory: Path, filename: str = "big.safetensors") -> Path:
    return directory / f"{filename}.mosael-part.json"


def _names(directory: Path) -> list[str]:
    return sorted(one.name for one in directory.iterdir())


# --- ① 中断后从已下字节继续 ---------------------------------------------------------

def test_中断后从已下字节继续_请求带Range_最终哈希对得上(install, sites, tmp_path: Path) -> None:
    body = bytes(range(256)) * 4000  # ~1 MB
    digest = hashlib.sha256(body).hexdigest()
    site = sites(body, cut_at=400_000)
    directory = tmp_path / "loras"
    directory.mkdir()
    #: 第一次:发到 400_000 字节就断(客户端看到「下到一半断了」,半截留在目录里)。
    with pytest.raises(install.ComfyError, match="再试一次|断了|下载"):
        _events(install, site, directory, sha256=digest)
    part = _part(directory)
    assert part.is_file(), f"取消/失败要把半截留着:{_names(directory)}"
    half = part.stat().st_size
    assert 0 < half < len(body), f"断了之后应当有半截:{half}"
    print(f"[目录 · 中断后] {half} 字节的半截 + sidecar:{_names(directory)}", flush=True)
    sidecar = json.loads(_sidecar(directory).read_text(encoding="utf-8"))
    assert sidecar["url"] == site.url
    assert sidecar["total_bytes"] == len(body)
    assert sidecar["etag"] == '"v1"'
    assert sidecar["sha256"] == digest

    #: 第二次:应当从 half 接着下,而不是从头。
    result, events = _events(install, site, directory, sha256=digest)
    assert result == {"folder": "loras", "name": "big.safetensors", "size": len(body), "route": "local"}
    assert (directory / "big.safetensors").read_bytes() == body
    assert hashlib.sha256((directory / "big.safetensors").read_bytes()).hexdigest() == digest
    assert len(site.requests) == 2, f"两次请求:{site.requests}"
    assert site.requests[0]["range"] is None, "第一次不知道从哪续,不该带 Range"
    assert site.requests[1]["range"] == f"bytes={half}-", f"第二次要从已下字节继续:{site.requests}"
    assert site.requests[1]["if_range"] == '"v1"', "带上上次记的 ETag:文件换了服务端就回整包"
    assert site.requests[1]["accept_encoding"] == "identity", "续传不要让服务端压缩(字节数对不上)"
    assert not _part(directory).exists() and not _sidecar(directory).exists(), "下完只留成品"
    print(f"[目录 · 续传完成后] {_names(directory)}(要求是 {len(body)} 字节)", flush=True)

    #: 进度从已下字节继续:第一条进度就不是 0。
    steps = [event for event in events if event.get("event") == "step" and event.get("step") == "download"]
    assert steps, f"要有结构化字节:{events}"
    assert steps[0]["downloaded_bytes"] >= half, f"续传的进度从已下字节开始:{steps[0]}"
    assert steps[0]["total_bytes"] == len(body)
    assert all(step["downloaded_bytes"] <= len(body) for step in steps)


# --- ② 服务端不支持 Range(回 200):从头下,半截被截断 ---------------------------------

def test_服务端回200_从头下_半截被截断而不是接在整包后面(install, sites, tmp_path: Path) -> None:
    body = bytes(range(256)) * 4000
    digest = hashlib.sha256(body).hexdigest()
    site = sites(body, cut_at=300_000, ignore_range=True)
    directory = tmp_path / "loras"
    directory.mkdir()
    with pytest.raises(install.ComfyError):
        _events(install, site, directory, sha256=digest)
    half = _part(directory).stat().st_size
    assert 0 < half < len(body)

    result, _events2 = _events(install, site, directory, sha256=digest)
    assert result["size"] == len(body)
    #: 200 的整包**覆盖**半截,不是接在它后面:否则文件会比 body 长。
    assert (directory / "big.safetensors").read_bytes() == body
    assert site.requests[1]["range"] == f"bytes={half}-", "先按 Range 试一次,服务端说 200"
    assert len(site.requests) == 2


# --- ③ 校验器不一致:重下,不硬续 ------------------------------------------------

def test_sidecar里的ETag与本次不同_服务端仍回206_也要从头重下(install, sites, tmp_path: Path) -> None:
    old = b"a" * 600_000
    new = b"b" * 700_000
    #: 这个服务端**不认 If-Range**:文件换了也照样按 Range 回 206 —— 客户端必须自己比 ETag。
    site = sites(old, cut_at=500_000, honor_if_range=False)
    directory = tmp_path / "loras"
    directory.mkdir()
    with pytest.raises(install.ComfyError):
        _events(install, site, directory)
    half = _part(directory).stat().st_size
    assert 0 < half < len(old)

    #: 同一个地址,文件被重新发布了(大小、ETag 都变了);这个服务端**不认 If-Range**,照样回 206。
    site.body = new
    site.etag = '"v2"'
    site.cut_at = None
    result, _events2 = _events(install, site, directory)
    assert result["size"] == len(new)
    assert (directory / "big.safetensors").read_bytes() == new
    assert site.requests[-1]["range"] is None, "发现校验器不一致之后要从头请求"
    assert len(site.requests) == 3, f"第一次断、第二次 Range 得到不一致的 206、第三次从头:{site.requests}"


def test_sidecar里记录的URL不是这个地址_不硬续(install, sites, tmp_path: Path) -> None:
    body = b"c" * 100_000
    directory = tmp_path / "loras"
    directory.mkdir()
    _part(directory).write_bytes(b"x" * 50_000)
    _sidecar(directory).write_text(json.dumps({
        "version": 1, "url": "https://example.invalid/other.safetensors", "filename": "big.safetensors",
        "total_bytes": 100_000, "etag": '"v1"', "sha256": "", "updated_at": time.time(),
    }), encoding="utf-8")
    site = sites(body)
    result, _events2 = _events(install, site, directory)
    assert result["size"] == len(body)
    assert (directory / "big.safetensors").read_bytes() == body
    assert site.requests[0]["range"] is None, "URL 对不上就不该发 Range"


# --- ④ 416:已下完或坏的 ------------------------------------------------------------

def test_416_已下字节等于总大小且SHA256对得上_直接留下(install, sites, tmp_path: Path) -> None:
    body = b"d" * 250_000
    digest = hashlib.sha256(body).hexdigest()
    directory = tmp_path / "loras"
    directory.mkdir()
    _part(directory).write_bytes(body)
    _sidecar(directory).write_text(json.dumps({
        "version": 1, "url": "", "filename": "big.safetensors", "total_bytes": len(body),
        "etag": '"v1"', "sha256": digest, "updated_at": time.time(),
    }), encoding="utf-8")
    site = sites(b"different", always_416=True)
    #: sidecar 里的 URL 换成这个站(上面的 URL 还没起)。
    sidecar = json.loads(_sidecar(directory).read_text(encoding="utf-8"))
    sidecar["url"] = site.url
    _sidecar(directory).write_text(json.dumps(sidecar), encoding="utf-8")

    result, _events2 = _events(install, site, directory, sha256=digest)
    assert result["size"] == len(body)
    assert (directory / "big.safetensors").read_bytes() == body
    assert site.requests[0]["range"] == f"bytes={len(body)}-"
    assert not _part(directory).exists()


def test_416_半截坏了_删掉重下(install, sites, tmp_path: Path) -> None:
    body = b"e" * 250_000
    digest = hashlib.sha256(body).hexdigest()
    directory = tmp_path / "loras"
    directory.mkdir()
    broken = bytearray(body)
    broken[0] = 0
    _part(directory).write_bytes(bytes(broken))
    site = sites(body)
    _sidecar(directory).write_text(json.dumps({
        "version": 1, "url": site.url, "filename": "big.safetensors", "total_bytes": len(body),
        "etag": '"v1"', "sha256": digest, "updated_at": time.time(),
    }), encoding="utf-8")
    result, _events2 = _events(install, site, directory, sha256=digest)
    assert result["size"] == len(body)
    assert (directory / "big.safetensors").read_bytes() == body
    assert site.requests[0]["range"] == f"bytes={len(body)}-", "先用 Range 问一次"
    assert site.requests[-1]["range"] is None, "校验不过 -> 从头"
    assert not _part(directory).exists()


# --- ⑤ 取消保留;显式删除才删；⑥ 孤儿清理 ------------------------------------------

def test_取消后保留半截和sidecar_显式删除才删(install, sites, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cancel = tmp_path / "cancel"
    monkeypatch.setenv("MOSAEL_PLUGIN_CANCEL_FILE", str(cancel))
    body = b"f" * 400_000
    site = sites(body, slow=True)
    directory = tmp_path / "loras"
    directory.mkdir()

    def stop_after_first_progress(event: dict[str, Any]) -> None:
        #: 第一条进度就按取消(新旧实现都会报 progress;这里不依赖新加的字节字段)。
        if event.get("event") == "progress" and (event.get("progress") or 0) > 0:
            cancel.write_text("1")

    with pytest.raises(install.ComfyError, match="已取消"):
        _events(install, site, directory, on_progress=stop_after_first_progress)
    assert (directory / "big.safetensors").exists() is False
    assert _part(directory).is_file(), f"取消要保留半截:{_names(directory)}"
    assert _sidecar(directory).is_file(), f"取消要保留 sidecar:{_names(directory)}"

    #: 「删除没下完的部分」是一个明确的动作:这时才删,成品也一个都不碰。
    assert install.discard_partial(directory, "big.safetensors") is True
    assert _names(directory) == [], f"删完目录里不该有半截/成品/sidecar:{_names(directory)}"
    print(f"[目录 · 点删除之后] {_names(directory)}", flush=True)


def test_孤儿part超过N天才清_新的和正在续的不动(install, sites, tmp_path: Path) -> None:
    directory = tmp_path / "loras"
    directory.mkdir()
    now = time.time()
    old = _part(directory, "old.safetensors")
    old.write_bytes(b"old")
    old_sidecar = _sidecar(directory, "old.safetensors")
    old_sidecar.write_text(json.dumps({"version": 1, "url": "https://example.invalid/old"}), encoding="utf-8")
    stale = now - (install.PART_MAX_AGE_DAYS + 1) * 86400
    import os
    os.utime(old, (stale, stale))
    os.utime(old_sidecar, (stale, stale))

    fresh = _part(directory, "fresh.safetensors")
    fresh.write_bytes(b"fresh")
    fresh_sidecar = _sidecar(directory, "fresh.safetensors")
    fresh_sidecar.write_text(json.dumps({"version": 1, "url": "https://example.invalid/fresh"}), encoding="utf-8")

    body = b"g" * 50_000
    site = sites(body)
    result, _events2 = _events(install, site, directory, filename="big.safetensors")
    assert result["size"] == len(body)
    assert (directory / "big.safetensors").read_bytes() == body
    assert not old.exists() and not old_sidecar.exists(), "超过 N 天的孤儿 .part 和 sidecar 要扫掉"
    assert fresh.exists() and fresh_sidecar.exists(), "没超过 N 天的、别的文件的半截不动"


def test_刚过N天但正在续传的那一份_不当作孤儿删掉(install, sites, tmp_path: Path) -> None:
    body = b"h" * 300_000
    digest = hashlib.sha256(body).hexdigest()
    directory = tmp_path / "loras"
    directory.mkdir()
    _part(directory).write_bytes(body[:120_000])
    site = sites(body)
    _sidecar(directory).write_text(json.dumps({
        "version": 1, "url": site.url, "filename": "big.safetensors", "total_bytes": len(body),
        "etag": '"v1"', "sha256": digest, "updated_at": time.time(),
    }), encoding="utf-8")
    import os
    stale = time.time() - (install.PART_MAX_AGE_DAYS + 1) * 86400
    os.utime(_part(directory), (stale, stale))
    os.utime(_sidecar(directory), (stale, stale))

    result, _events2 = _events(install, site, directory, sha256=digest)
    assert result["size"] == len(body)
    assert site.requests[0]["range"] == "bytes=120000-", "用户明确继续的那一份,不按孤儿删"
    assert (directory / "big.safetensors").read_bytes() == body


# --- 进度:结构化字节,未知总数用 null 不用 0 --------------------------------------------

class _Folders:
    """`partial` op 只要问目录:`folder_info` 是 `GET /experiment/models`。"""

    base = "http://127.0.0.1:1"

    def __init__(self, mapping: dict[str, list[str]]) -> None:
        self.mapping = mapping

    def get(self, path: str):
        if path == "/experiment/models":
            return [{"name": name, "folders": folders} for name, folders in self.mapping.items()]
        raise AssertionError(f"没料到这个请求:{path}")


def test_partial_op_给出已下字节和能否续传_删除才删(install, sites, tmp_path: Path) -> None:
    body = b"j" * 200_000
    digest = hashlib.sha256(body).hexdigest()
    directory = tmp_path / "loras"
    directory.mkdir()
    _part(directory).write_bytes(body[:80_000])
    site = sites(body)
    _sidecar(directory).write_text(json.dumps({
        "version": 1, "url": site.url, "filename": "big.safetensors", "total_bytes": len(body),
        "etag": '"v1"', "sha256": digest, "updated_at": time.time(),
    }), encoding="utf-8")
    comfy = _Folders({"loras": [str(directory)]})

    state = install.partial({"folder": "loras", "filename": "big.safetensors", "url": site.url,
                             "sha256": digest}, comfy, "zh")
    assert state["partial"] is True
    assert state["resumable"] is True
    assert state["downloaded_bytes"] == 80_000
    assert state["total_bytes"] == len(body)

    #: 地址变了就不算「能续」—— 界面不该给「继续下载」。
    other = install.partial({"folder": "loras", "filename": "big.safetensors",
                             "url": "https://example.invalid/other.safetensors", "sha256": digest}, comfy, "zh")
    assert other["resumable"] is False

    removed = install.partial({"folder": "loras", "filename": "big.safetensors", "delete": True}, comfy, "zh")
    assert removed["removed"] is True
    assert removed["downloaded_bytes"] is None and removed["total_bytes"] is None, "未知就是 null,不是 0"
    assert not _part(directory).exists() and not _sidecar(directory).exists()
    assert not (directory / "big.safetensors").exists(), "删除半截不会造出成品"


def test_进度里的字节是结构化的_总数未知是null不是0(install, sites, tmp_path: Path) -> None:
    body = b"i" * 120_000
    site = sites(body)
    directory = tmp_path / "loras"
    directory.mkdir()
    #: 让服务端不报 Content-Length:把这个站改成一个「分块」的站太难,这里只断言已有的两条:
    #: 已知总大小时 total_bytes 是数;progress 是从字节算出来的。
    _result, events = _events(install, site, directory)
    steps = [event for event in events if event.get("event") == "step" and event.get("step") == "download"]
    assert steps
    for step in steps:
        assert isinstance(step["downloaded_bytes"], int)
        assert step["downloaded_bytes"] <= len(body)
        assert step["total_bytes"] == len(body)
        assert isinstance(step.get("speed_bps"), (int, float))
    progress = [event for event in events if event.get("event") == "progress"]
    assert progress[-1]["progress"] == pytest.approx(1.0)


def test_进度_总数未知时是null不是0(install) -> None:
    """服务端没给总大小时,结构化字段是 null —— 不能写成 0,那在界面上是「一个 0 字节的文件」。"""
    events: list[dict[str, Any]] = []
    install._bytes_progress(events.append, "zh", 1234, None, 0.0)  # noqa: SLF001 — 钉的就是这条上报
    assert events[0]["downloaded_bytes"] == 1234
    assert events[0]["total_bytes"] is None
    assert events[0]["speed_bps"] is None
    assert events[1]["total_bytes"] is None, "step 行同样是 null"
