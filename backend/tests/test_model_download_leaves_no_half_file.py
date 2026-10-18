"""取消 / 中断模型下载:半截**留着**供续传,只有用户明确点「删除没下完的部分」才删。

口径在 2026-10-19 由维护者改成断点续传(取代此前「取消/失败就删 `.part`」):下载先写
`<名字>.mosael-part` + `<名字>.mosael-part.json`(sidecar:源 URL、总大小、ETag / Last-Modified、声明的
SHA256),核对通过才挂正式的名字(见 plugins/bundled/comfyui/tools/install.py)。

这里的证据都是**目录清单**:

- 取消:`.part` 和 sidecar 都还在,没有成品 —— 下次能从这儿接着下;
- `discard_partial`(界面上「删除没下完的部分」)之后:目录里既没有 `.part`,也没有成品、没有 sidecar;
- 上一次崩溃留下、但 sidecar 已经丢了(核对不了是不是同一个文件)的半截:下一次开始下载时清掉,从头下,
  下成了目录里只留成品。

续传本身(206 / 200 / 416、Request 上的 Range)钉在 tests/test_model_download_resume.py,那里用本机真 HTTP 服务。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui" / "tools"
#: 插件模块名都是短名(install、sources……),和别的测试文件共用一个进程时要像别处一样换进换出。
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


class _Body:
    """一个「正在下来的文件」:按块给字节。`on_read` 在第 n 次读时被叫到(用来模拟这时候来了取消)。"""

    def __init__(self, chunks: list[bytes], on_read: dict[int, Any] | None = None) -> None:
        self._chunks = list(chunks)
        self._on_read = on_read or {}
        self._reads = 0
        self.closed = False
        self.status = 200
        self.headers = {"Content-Type": "application/octet-stream",
                        "Content-Length": str(sum(len(chunk) for chunk in chunks))}

    def read1(self, _size: int) -> bytes:
        self._reads += 1
        hook = self._on_read.get(self._reads)
        if hook is not None:
            hook()
        return self._chunks.pop(0) if self._chunks else b""

    def close(self) -> None:
        self.closed = True


def _serve(install, response: _Body, url: str = "https://example.invalid/file.safetensors"):
    install._open_download = lambda _url, _locale: (response, url)  # noqa: SLF001 — 这里测的就是 via_local


def _names(directory: Path) -> list[str]:
    """目录清单。是证据本身。"""
    return sorted(one.name for one in directory.iterdir())


def test_下到一半取消_半截和sidecar都留着_可以接着下(install, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / "ComfyUI" / "models" / "loras"
    directory.mkdir(parents=True)
    (directory / "keep.safetensors").write_bytes(b"already here")
    cancel = tmp_path / "plugin.cancel"
    monkeypatch.setenv("MOSAEL_PLUGIN_CANCEL_FILE", str(cancel))
    #: 第二块读出来之前「用户按了取消」:插件的下一次检查就停在那一块
    body = _Body([b"\x01" * 1024, b"\x01" * 1024], on_read={2: lambda: cancel.write_text("1")})
    _serve(install, body)

    with pytest.raises(install.ComfyError, match="已取消"):
        install.via_local(directory, "https://example.invalid/big.safetensors", "loras", "big.safetensors", "zh",
                          lambda _event: None)

    assert (directory / "big.safetensors.mosael-part").is_file(), f"取消要留半截:{_names(directory)}"
    assert (directory / "big.safetensors.mosael-part.json").is_file(), f"取消要留 sidecar:{_names(directory)}"
    assert not (directory / "big.safetensors").exists(), "没下完不挂正式的名字"
    assert (directory / "keep.safetensors").exists(), "别的文件一个不动"
    assert body.closed, "连接也要关掉"


def test_删除没下完的部分_才删半截_成品也不碰(install, tmp_path: Path) -> None:
    directory = tmp_path / "ComfyUI" / "models" / "loras"
    directory.mkdir(parents=True)
    (directory / "big.safetensors.mosael-part").write_bytes(b"half")
    (directory / "big.safetensors.mosael-part.json").write_text('{"version": 1}', encoding="utf-8")
    (directory / "keep.safetensors").write_bytes(b"already here")

    assert install.discard_partial(directory, "big.safetensors") is True
    assert _names(directory) == ["keep.safetensors"], f"只删没下完的那一份:{_names(directory)}"
    assert install.discard_partial(directory, "big.safetensors") is False, "没有半截时是 false"


def test_上一次崩溃留下的半截_核对不了_下一次开始时清掉(install, tmp_path: Path) -> None:
    """进程被强杀 / 后端重启留下的 `.mosael-part`:sidecar 里的 URL 对不上,没法核对是不是同一个文件,不硬续。

    这一条此前是红的:重启后用户又点了一次同一个文件,而这次地址回 404(或干脆是取消),旧的半截
    就一直在目录里 —— 它既不会被下完、也没人认领。现在开始下载前先清掉核对不过的那一份,不再靠
    「拿到响应再截断」。"""
    directory = tmp_path / "ComfyUI" / "models" / "loras"
    directory.mkdir(parents=True)
    stale = directory / "big.safetensors.mosael-part"
    stale.write_bytes(b"half from the run that was killed")
    (directory / "big.safetensors.mosael-part.json").write_text(json.dumps({
        "version": 1, "url": "https://example.invalid/other.safetensors", "filename": "big.safetensors",
        "total_bytes": 1000, "etag": '"v1"', "sha256": "", "updated_at": 0,
    }), encoding="utf-8")

    def refuse(_url: str, _locale: str):
        raise install.ComfyError("下载地址回了 HTTP 404")

    install._open_download = refuse  # noqa: SLF001 — 这一条不碰网络:一开始就被拒

    with pytest.raises(install.ComfyError, match="404"):
        install.via_local(directory, "https://example.invalid/big.safetensors", "loras", "big.safetensors", "zh",
                          lambda _event: None)

    assert _names(directory) == [], f"核对不过的半截和 sidecar 都清掉:{_names(directory)}"


def test_老半截还在时下成了_目录里只留成品(install, tmp_path: Path) -> None:
    directory = tmp_path / "ComfyUI" / "models" / "loras"
    directory.mkdir(parents=True)
    (directory / "big.safetensors.mosael-part").write_bytes(b"stale bytes from before")
    body = b"\x02" * 5000
    _serve(install, _Body([body]))

    out = install.via_local(directory, "https://example.invalid/big.safetensors", "loras", "big.safetensors", "zh",
                            lambda _event: None)

    assert out == {"folder": "loras", "name": "big.safetensors", "size": len(body), "route": "local"}
    assert (directory / "big.safetensors").read_bytes() == body
    assert _names(directory) == ["big.safetensors"], f"半截被清掉、只留成品:{_names(directory)}"
