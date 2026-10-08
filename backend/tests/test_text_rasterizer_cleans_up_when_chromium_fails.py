"""文字栅格化器起到一半失败(Chromium 起不来)时,已经起来的 Playwright 驱动、静态服务线程和监听端口都收掉(MED-9)。

`with TextRasterizer(...)` 的 `__enter__` 抛异常时 `__exit__` 不会被调用。此前调用方照常回落到 ASS 烧字,可每次导出 / 取帧都
留下一个 Playwright 驱动进程、一条 `serve_forever` 线程和一个监听端口;`__exit__` 自己也没 `server_close`。
"""

from __future__ import annotations

import socketserver
import sys
import types
from pathlib import Path

import pytest

from app.media import text_render


class _Recording(socketserver.TCPServer):
    made: list["_Recording"] = []

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        _Recording.made.append(self)


class _Playwright:
    def __init__(self, *, launches: bool) -> None:
        self.launches = launches
        self.stopped = 0
        self.chromium = types.SimpleNamespace(launch=self._launch)

    def _launch(self, **_kwargs):
        if not self.launches:
            raise RuntimeError("Executable doesn't exist at .../chromium_headless_shell")
        page = types.SimpleNamespace(set_content=lambda *a, **kw: None)
        return types.SimpleNamespace(new_page=lambda **kw: page, close=lambda: None)

    def start(self) -> "_Playwright":
        return self

    def stop(self) -> None:
        self.stopped += 1


@pytest.fixture
def rigged(monkeypatch, tmp_path: Path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "assets" / "index-abc.css").write_text("body{}", encoding="utf-8")
    (dist / "index.html").write_text('<link rel="stylesheet" href="/assets/index-abc.css">', encoding="utf-8")
    monkeypatch.setattr(text_render, "find_frontend_dist", lambda: dist)
    monkeypatch.setattr(text_render.socketserver, "TCPServer", _Recording)
    _Recording.made.clear()

    def install(*, launches: bool) -> _Playwright:
        driver = _Playwright(launches=launches)
        monkeypatch.setitem(sys.modules, "playwright.sync_api", types.SimpleNamespace(sync_playwright=lambda: driver))
        return driver

    return install


def _released(server: socketserver.TCPServer) -> bool:
    return server.socket.fileno() == -1


def test_Chromium起不来_驱动停掉_端口还回去(rigged) -> None:
    driver = rigged(launches=False)

    with pytest.raises(RuntimeError, match="Executable"):
        with text_render.TextRasterizer(320, 180):
            pass

    assert driver.stopped == 1, "Playwright 驱动进程留下了"
    [server] = _Recording.made
    assert _released(server), "监听端口没还回去"


def test_正常用完_端口也还回去(rigged) -> None:
    driver = rigged(launches=True)

    with text_render.TextRasterizer(320, 180):
        pass

    assert driver.stopped == 1
    [server] = _Recording.made
    assert _released(server), "此前 __exit__ 只 shutdown、不 server_close"
