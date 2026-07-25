"""字幕/花字的「按预览 CSS 渲染成透明 PNG」烧字方案。

libass 和浏览器对同一字体的字号/排版解释不同(见 render_executor._ASS_FONTSIZE_SCALE 的历史),
字幕背景框的圆角、内边距、投影 ASS 也画不出来——导出永远和预览对不齐。这里改用无头 Chromium
(Playwright)**复用预览那一整套 CSS 和字体**把每条文字渲染成透明 PNG,再由 ffmpeg 叠加,
从根上做到逐像素一致。动画(缩放/位移/旋转/透明度)不在 PNG 里,由 render_executor 的元素
变换管线施加,PNG 只承载「静态外观」。

字体是关键:app 自带 Inter Variable + 霞鹜文楷(打进 dist 的 @font-face 子集)。渲染页直接
加载 app 构建出的 CSS,字体环境与预览完全相同。
"""

from __future__ import annotations

import functools
import http.server
import socketserver
import threading
from pathlib import Path

from app.core.config import settings

# app 根字体(design/tokens.css 的 --font-sans):空 font_family 的花字继承它(霞鹜文楷/楷体)。
_APP_FONT_STACK = (
    '"Inter Variable", "LXGW WenKai Screen", "LXGW WenKai", -apple-system, '
    'BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", "Segoe UI", system-ui, sans-serif'
)
# 字幕默认字体栈(前端 subtitleStyle.ts 的 SYSTEM_FONT_STACK):空 font_family 的字幕用系统黑体,
# 和花字继承的 --font-sans(楷体)不同——不能混用,否则字幕字体和预览对不上。
_SUBTITLE_FONT_STACK = (
    'system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", "Helvetica Neue", sans-serif'
)


def find_frontend_dist() -> Path | None:
    """定位构建好的前端 dist(含 index-*.css 里的 @font-face)。

    MIBU_FRONTEND_DIST 覆盖;否则从后端相对仓库结构里找。打包版由 Electron 侧注入该路径。"""
    override = getattr(settings, "frontend_dist", "") or ""
    candidates = [Path(override)] if override else []
    here = Path(__file__).resolve()
    # backend/app/media/text_render.py → 仓库根/frontend/dist
    candidates.append(here.parents[3] / "frontend" / "dist")
    for cand in candidates:
        if cand and (cand / "index.html").is_file() and any(cand.glob("assets/*.css")):
            return cand
    return None


def _app_css_href(dist: Path) -> str:
    css = next(iter(sorted(dist.glob("assets/*.css"))), None)
    return f"assets/{css.name}" if css else ""


def _huazi_style_css(style, frame_w: int) -> tuple[str, int]:
    """花字元素的内联样式(不含位置/变换/透明度——那些交给 ffmpeg)。返回 (css, padding)。"""
    fs = float(style.font_size)
    sw = float(style.stroke_width)
    sh = float(style.shadow)
    pad = max(int(round(sh * 3)), int(round(sw)), 6)  # 给描边/投影留出溢出空间(对称,文字仍居中)
    parts = [
        "position:absolute", "left:0", "top:0", "display:inline-block",
        f"font-size:{fs:g}px",
        f"color:{style.color}",
        f"font-weight:{700 if style.bold else 400}",
        f"font-style:{'italic' if style.italic else 'normal'}",
        f"text-align:{style.align}",
        f"font-family:{style.font_family or _APP_FONT_STACK}",
        "line-height:1.2", "white-space:pre",
        f"padding:{pad}px",
    ]
    if sw > 0:
        parts.append(f"-webkit-text-stroke:{sw:g}px {style.stroke_color}")
    if sh > 0:
        parts.append(f"text-shadow:0 {sh:g}px {sh * 1.5:g}px rgba(0,0,0,0.65)")
    return ";".join(parts), pad


def _subtitle_style_css(style, frame_w: int) -> str:
    """字幕盒子的内联样式(前端固定 className + subtitleCss 的合并结果)。"""
    if style.bg_opacity > 0:
        h = style.bg_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        bg = f"rgba({r},{g},{b},{style.bg_opacity:g})"
    else:
        bg = "transparent"
    parts = [
        "display:inline-block", f"max-width:{int(frame_w * 0.86)}px", "white-space:pre-wrap",
        "border-radius:6px", "padding:3px 10px", "text-align:center", "line-height:1.45",
        f"font-size:{float(style.font_size):g}px",
        f"color:{style.color}",
        f"font-weight:{700 if style.bold else 400}",
        f"font-family:{style.font_family or _SUBTITLE_FONT_STACK}",
        f"background:{bg}",
        "text-shadow:0 1px 2px rgba(0,0,0,0.7)",
    ]
    return ";".join(parts)


class TextRasterizer:
    """一次导出复用一个 Chromium + dist 静态服务:把每条字幕/花字渲染成透明 PNG。

    用法(在渲染 worker 线程里,非 asyncio):
        with TextRasterizer(frame_w, frame_h) as tr:
            png_bytes = tr.render_huazi(text, style)
    """

    def __init__(self, frame_w: int, frame_h: int) -> None:
        self.frame_w = frame_w
        self.frame_h = frame_h
        self._dist = find_frontend_dist()
        self._httpd: socketserver.TCPServer | None = None
        self._thread: threading.Thread | None = None
        self._pw = None
        self._browser = None
        self._page = None

    def available(self) -> bool:
        return self._dist is not None

    def __enter__(self) -> "TextRasterizer":
        if self._dist is None:
            raise RuntimeError("frontend dist not found; cannot rasterize text")
        # 静态服务 dist,让 @font-face 的相对 URL(assets/*.woff2)解析得到
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(self._dist))
        handler.log_message = lambda *a, **k: None  # 静音
        self._httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        port = self._httpd.server_address[1]

        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(args=["--force-color-profile=srgb"])
        self._page = self._browser.new_page(
            viewport={"width": self.frame_w, "height": self.frame_h}, device_scale_factor=1
        )
        css = _app_css_href(self._dist)
        self._page.set_content(
            f'<!doctype html><html><head><meta charset="utf-8">'
            f'<base href="http://127.0.0.1:{port}/">'
            f'<link rel="stylesheet" href="{css}">'
            f'<style>html,body{{margin:0;padding:0;background:transparent}}</style></head>'
            f'<body></body></html>',
            wait_until="load",
        )
        return self

    def __exit__(self, *exc) -> None:
        try:
            if self._browser:
                self._browser.close()
        finally:
            if self._pw:
                self._pw.stop()
            if self._httpd:
                self._httpd.shutdown()

    def _screenshot(self, css: str, text: str) -> bytes:
        # 用 JS 直接设 cssText + textContent,而不是拼进 HTML 的 style="…" 属性——字体栈里的
        # 双引号(如 "Inter Variable")会提前闭合属性,把 background 等后续声明整段吞掉。
        page = self._page
        page.evaluate(
            "([css, text]) => { const el = document.createElement('div'); el.id = 'el';"
            " el.style.cssText = css; el.textContent = text; document.body.replaceChildren(el); }",
            [css, text],
        )
        page.evaluate("async () => { await document.fonts.ready; }")  # 等字体就绪,否则尺寸会错
        return page.query_selector("#el").screenshot(omit_background=True)

    def render_huazi(self, text: str, style) -> bytes:
        css, _pad = _huazi_style_css(style, self.frame_w)
        return self._screenshot(css, text)

    def render_subtitle(self, text: str, style) -> bytes:
        return self._screenshot(_subtitle_style_css(style, self.frame_w), text)
