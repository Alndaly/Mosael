"""取消 / 中断模型下载,模型目录里不留半成品。

下载先写 `<名字>.mosael-part`,核对通过才挂正式的名字(见 plugins/bundled/comfyui/tools/install.py)。
两条路会留下它:

- 取消、失败:`via_local` 的 `except BaseException` 删掉自己那半截 —— 这一条一直有;
- **进程被强杀 / 后端重启**:走不到那个 except。此时半截会留在模型目录里,直到下一次
  **同一个文件**开始下载。以前靠「打开时 `wb` 截断」,可那要等真的拿到响应才发生:这一次
  404、要登录、或者又取消了,半截就一直没人认领。所以开始下载前要先删掉旧的那一份。

这里的证据都是**目录清单**:取消之后既没有 `.mosael-part`,也没有成品。
"""

from __future__ import annotations

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
    """目录清单。是证据本身:取消之后这里应当只剩原来就有的文件。"""
    return sorted(one.name for one in directory.iterdir())


def test_下到一半取消_目录里既没有半截也没有成品(install, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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

    assert _names(directory) == ["keep.safetensors"], f"取消后不能留下半截或成品:{_names(directory)}"
    assert body.closed, "连接也要关掉"


def test_上一次崩溃留下的半截_下一次同一个文件开始下载时先删(install, tmp_path: Path) -> None:
    """进程被强杀 / 后端重启留下的 `.mosael-part`:下一次同一个文件开始时先删,不靠「拿到响应再截断」。

    这一条此前是红的:重启后用户又点了一次同一个文件,而这次地址回 404(或干脆是取消),旧的半截
    就一直在目录里 —— 它既不会被下完、也没人认领。"""
    directory = tmp_path / "ComfyUI" / "models" / "loras"
    directory.mkdir(parents=True)
    stale = directory / "big.safetensors.mosael-part"
    stale.write_bytes(b"half from the run that was killed")

    def refuse(_url: str, _locale: str):
        raise install.ComfyError("下载地址回了 HTTP 404")

    install._open_download = refuse  # noqa: SLF001 — 这一条不碰网络:一开始就被拒

    with pytest.raises(install.ComfyError, match="404"):
        install.via_local(directory, "https://example.invalid/big.safetensors", "loras", "big.safetensors", "zh",
                          lambda _event: None)

    assert _names(directory) == [], f"开始下一次之前先把旧的半截删掉:{_names(directory)}"


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
