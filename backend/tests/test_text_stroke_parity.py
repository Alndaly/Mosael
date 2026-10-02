"""花字描边契约的后端一侧:跑 contracts/text-stroke-cases.json,再真渲两条导出路径量像素。

前端 `textStroke.parity.test.ts` 跑**同一份语料**。

为什么需要契约:描边有三条路径 —— 预览(DOM 上的 `-webkit-text-stroke`)、导出 PNG(无头
Chromium 跑同一套 CSS)、libass 回落(`\\bord`)。修复前三者语义各不相同:CSS 是**居中**描边,
一半压进字里,霞鹜文楷这类细笔画字体的白芯几乎被吃光;libass 的 `\\bord` 是**纯外**描边,
同一个数值画出来的外圈是 PNG 路径的两倍。三份实现各自自洽,互不相识。

现在统一成「外描边」:外圈宽度 = 存储值的一半(恰好是居中描边向外伸出的那一半,已有花字的
外轮廓不变),按字号封顶。语料钉住解析结果;下面的真渲用例钉住**像素**:字芯还在、外轮廓
没动、libass 与 PNG 的外圈一样宽。只看 CSS 字符串是验不出「字芯被吃掉」的 —— 那是浏览器
画出来才有的事。

**改语义时**:先改 contracts/text-stroke-cases.json,看着两侧一起红,再改实现。
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.core.config import settings
from app.media.render_executor import _build_ass, _text_style_tags
from app.media.render_plan import TEXT_STROKE_MAX_OUTER_RATIO, TextStyleSpec, build_render_plan
from app.media.text_render import TextRasterizer, _huazi_style_css

_REPO = Path(__file__).resolve().parents[2]
_CONTRACT = _REPO / "contracts" / "text-stroke-cases.json"
#: 真渲用的字体:app 自带的霞鹜文楷(frontend 依赖)。它是这次 bug 最显眼的那种细笔画字体。
_WENKAI = _REPO / "frontend" / "node_modules" / "lxgw-wenkai-screen-webfont"
_WENKAI_FAMILY = '"LXGW WenKai Screen"'


def _load() -> dict:
    return json.loads(_CONTRACT.read_text(encoding="utf-8"))


def _cases() -> list[dict]:
    return _load()["cases"]


def _ids() -> list[str]:
    return [case["name"] for case in _cases()]


def _declarations(css: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in css.split(";"):
        if ":" in part:
            name, _, value = part.partition(":")
            out[name.strip()] = value.strip()
    return out


def test_contract_file_is_present_and_versioned() -> None:
    """语料找不到就静默跳过是最坏的结果 —— 那样两侧都「通过」,而契约根本没跑。"""
    assert _CONTRACT.is_file(), f"描边契约语料缺失: {_CONTRACT}"
    data = _load()
    assert data["contract"] == "text-stroke"
    assert isinstance(data["version"], int)
    assert data["cases"], "语料为空 = 没有任何一致性保护"


def test_cap_ratio_matches_contract() -> None:
    assert TEXT_STROKE_MAX_OUTER_RATIO == _load()["max_outer_ratio"]


@pytest.mark.parametrize("case", _cases(), ids=_ids())
def test_outer_stroke_resolves_per_contract(case: dict) -> None:
    style = TextStyleSpec(**case["style"])
    assert style.outer_stroke_px == pytest.approx(case["expected"]["outer_px"], abs=1e-6)


@pytest.mark.parametrize("case", _cases(), ids=_ids())
def test_export_png_css_paints_stroke_under_fill(case: dict) -> None:
    """导出 PNG 的 CSS:描边先画、填充后画盖住向内那一半,线宽 = 外圈 × 2。"""
    css, _pad = _huazi_style_css(TextStyleSpec(**case["style"]), 1920)
    decl = _declarations(css)
    want = case["expected"]["css_stroke_width_px"]
    if want == 0:
        assert "-webkit-text-stroke" not in decl and "paint-order" not in decl
        return
    assert decl["paint-order"] == "stroke fill"
    width, _, color = decl["-webkit-text-stroke"].partition(" ")
    assert width.endswith("px") and float(width[:-2]) == pytest.approx(want, abs=1e-6)
    assert color == "#000000"


@pytest.mark.parametrize("case", _cases(), ids=_ids())
def test_libass_bord_is_the_outer_width(case: dict) -> None:
    tags = "".join(_text_style_tags(TextStyleSpec(**case["style"])))
    want = case["expected"]["ass_bord"]
    if want == 0:
        assert "\\bord0" in tags
        return
    bord = tags.split("\\bord", 1)[1].split("\\", 1)[0]
    assert float(bord) == pytest.approx(want, abs=1e-6)


def test_ass_border_is_in_frame_pixels() -> None:
    """\\bord 的单位要是画面像素才能直接写外圈宽度:ScaledBorderAndShadow 打开、PlayRes = 输出画幅。"""
    plan = build_render_plan(
        sequence_id="s", revision=1, width=1280, height=720, fps=30,
        clips=[{"id": "c", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 2}],
        assets={"a": {"file_key": "/x.png"}},
        text_overlays=[{"id": "t", "timeline_start": 0, "src_in": 0, "src_out": 2, "text_override": "字",
                        "effects": {"text_style": {"stroke_width": 4}}}],
    )
    ass = _build_ass(plan)
    assert "PlayResX: 1280\n" in ass and "PlayResY: 720\n" in ass
    assert "ScaledBorderAndShadow: yes\n" in ass


# ───────────────────────────── 真渲:像素层面的断言 ─────────────────────────────


def _rgba(png: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGBA")).astype(int)


def _bbox(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(mask)
    assert len(xs), "这张图里什么都没画出来"
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def _size(mask: np.ndarray) -> tuple[int, int]:
    x0, y0, x1, y1 = _bbox(mask)
    return x1 - x0 + 1, y1 - y0 + 1


def _outer_ring(stroked_ink: np.ndarray, plain_ink: np.ndarray) -> tuple[float, float]:
    """外圈宽度(横、竖)=(描边后的墨迹包围盒 − 不描边时的字形包围盒)/ 2。

    用全块字符 █ 量:四边都是直边,斜接(Chromium)与圆角(libass)两种拐角在包围盒上没有
    差别,量到的就是外圈本身。**不能拿描边后的白芯当基准** —— 修复前白芯自己就被吃小了一圈,
    那样量出来的是「外圈 + 被吃掉的那圈」,两条路径会碰巧相等,而外轮廓其实差一倍。"""
    (sw, sh), (pw, ph) = _size(stroked_ink), _size(plain_ink)
    return (sw - pw) / 2, (sh - ph) / 2


def _png_ink(png: bytes) -> np.ndarray:
    """透明底 PNG 的墨迹:覆盖过半。"""
    return _rgba(png)[..., 3] >= 128


def _bright(png: bytes) -> int:
    """白芯像素:几乎不透明且接近纯白。"""
    a = _rgba(png)
    return int(((a[..., 3] > 200) & (a[..., :3].min(axis=-1) > 200)).sum())


def _chromium_ready() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            return Path(pw.chromium.executable_path).is_file()
    except Exception:
        return False


@pytest.fixture(scope="module")
def rasterizer(tmp_path_factory: pytest.TempPathFactory):
    """真起导出用的那个 TextRasterizer。dist 用一份只装霞鹜文楷 @font-face 的最小目录顶上 ——
    TextRasterizer 只要求 dist 里有 index.html 和 assets/*.css,字体按相对 URL 取。"""
    if not (_WENKAI / "lxgwwenkaiscreen.css").is_file():
        pytest.skip("frontend 依赖没装(缺霞鹜文楷 webfont),先 pnpm install")
    if not _chromium_ready():
        pytest.skip("Playwright Chromium 没装(uv run playwright install chromium)")
    dist = tmp_path_factory.mktemp("dist")
    (dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (dist / "assets").mkdir()
    shutil.copy(_WENKAI / "lxgwwenkaiscreen.css", dist / "assets" / "app.css")
    (dist / "assets" / "files").symlink_to(_WENKAI / "files", target_is_directory=True)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "frontend_dist", str(dist))
        with TextRasterizer(1920, 1080) as tr:
            yield tr


def _wenkai(**over) -> TextStyleSpec:
    return TextStyleSpec(**{"font_size": 48.0, "color": "#ffffff", "stroke_color": "#000000",
                            "bold": False, "font_family": _WENKAI_FAMILY, **over})


_SAMPLE = "霞鹜文楷 花字描边"


def _pre_fix_render(tr: TextRasterizer, style: TextStyleSpec) -> bytes:
    """修复前的画法:同样的线宽,不带 paint-order —— 描边居中、盖在填充上面。"""
    css, _pad = _huazi_style_css(style, tr.frame_w)
    return tr._screenshot(css.replace("paint-order:stroke fill", "paint-order:normal"), _SAMPLE)


def test_export_png_keeps_white_core_of_thin_font(rasterizer: TextRasterizer) -> None:
    """白字黑描边(「综艺」预设的 6),霞鹜文楷常规体:描边后的白芯像素 ≈ 不描边时的字形像素。
    修复前同一段字只剩不到 1% 的白 —— 字整个变成黑的。"""
    plain = _bright(rasterizer.render_huazi(_SAMPLE, _wenkai(stroke_width=0)))
    stroked = _bright(rasterizer.render_huazi(_SAMPLE, _wenkai(stroke_width=6)))
    before = _bright(_pre_fix_render(rasterizer, _wenkai(stroke_width=6)))
    assert before < plain * 0.5, "对照组没有复现字芯被吃掉 —— 这条用例没有测到问题"
    assert stroked >= plain * 0.97, f"白芯只剩 {stroked}/{plain}"


@pytest.mark.parametrize("stroke_width", [2, 4, 6, 7])
def test_export_png_outer_contour_is_unchanged(rasterizer: TextRasterizer, stroke_width: float) -> None:
    """外轮廓与修复前一致:墨迹包围盒逐边差 ≤ 1px。已有花字的版式因此一个像素都不动。"""
    style = _wenkai(stroke_width=stroke_width)
    after = rasterizer.render_huazi(_SAMPLE, style)
    before = _pre_fix_render(rasterizer, style)
    assert Image.open(io.BytesIO(after)).size == Image.open(io.BytesIO(before)).size
    assert max(abs(a - b) for a, b in zip(_bbox(_png_ink(after)), _bbox(_png_ink(before)))) <= 1


#: 量外圈用的样式:全块字符、字号 100、存储线宽 12 → 外圈 6px(未封顶)。
_BLOCK = "█"
_BLOCK_STYLE = {"font_size": 100.0, "stroke_width": 12.0}
_BLOCK_OUTER = 6.0


def _png_ring(tr: TextRasterizer, style: dict) -> tuple[float, float]:
    stroked = _png_ink(tr.render_huazi(_BLOCK, _wenkai(**style)))
    plain = _png_ink(tr.render_huazi(_BLOCK, _wenkai(**{**style, "stroke_width": 0.0})))
    return _outer_ring(stroked, plain)


def test_export_png_ring_is_the_outer_width(rasterizer: TextRasterizer) -> None:
    assert TextStyleSpec(**_BLOCK_STYLE).outer_stroke_px == _BLOCK_OUTER
    ring = _png_ring(rasterizer, _BLOCK_STYLE)
    assert all(abs(side - _BLOCK_OUTER) <= 1 for side in ring), ring


def test_export_png_caps_outer_ring_by_font_size(rasterizer: TextRasterizer) -> None:
    """存储线宽 40、字号 100:外圈封顶 15px,而不是 20px。"""
    ring = _png_ring(rasterizer, {"font_size": 100.0, "stroke_width": 40.0})
    assert all(abs(side - 100 * TEXT_STROKE_MAX_OUTER_RATIO) <= 1 for side in ring), ring


def _libass_ready() -> bool:
    try:
        out = subprocess.run([settings.ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return " subtitles " in out.stdout


needs_libass = pytest.mark.skipif(
    not _libass_ready(), reason="ffmpeg 没带 libass(没有 subtitles 滤镜);MOSAEL_FFMPEG 指向完整版"
)

#: 纯绿底:黑描边压低绿通道、白字抬高红通道 —— 两种墨迹都按「覆盖过半」认,与 PNG 那边同义。
_GREEN = "0x00ff00"


def _libass_ink(tmp_path: Path, text_style: dict, transform: dict | None = None, at: float = 0.0,
                w: int = 640, h: int = 360) -> np.ndarray:
    """走导出回落的真路径:时间线片段 → 渲染计划 → _build_ass → ffmpeg 的 subtitles(libass)。"""
    plan = build_render_plan(
        sequence_id="s", revision=1, width=w, height=h, fps=30,
        clips=[{"id": "c", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 2}],
        assets={"a": {"file_key": "/x.png"}},
        text_overlays=[{"id": "t", "timeline_start": 0, "src_in": 0, "src_out": 2, "text_override": _BLOCK,
                        "effects": {"text_style": text_style}, "transform": transform or {}}],
    )
    ass = tmp_path / "t.ass"
    ass.write_text(_build_ass(plan), encoding="utf-8")
    out = tmp_path / "f.png"
    subprocess.run(
        [settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={_GREEN}:s={w}x{h}:d=3",
         "-vf", f"format=rgb24,subtitles=filename={ass}", "-ss", f"{at:.3f}", "-frames:v", "1", str(out)],
        check=True, timeout=60,
    )
    frame = np.asarray(Image.open(out).convert("RGB")).astype(int)
    return (frame[..., 0] >= 128) | (frame[..., 1] < 128)


def _libass_ring(tmp_path: Path, text_style: dict, transform: dict | None = None,
                 at: float = 0.0) -> tuple[float, float]:
    stroked = _libass_ink(tmp_path, text_style, transform, at)
    plain = _libass_ink(tmp_path, {**text_style, "stroke_width": 0}, transform, at)
    return _outer_ring(stroked, plain)


@needs_libass
def test_libass_ring_is_the_outer_width(tmp_path: Path) -> None:
    """修复前 \\bord 写的是整个存储值,这里量出来是 12 而不是 6。"""
    ring = _libass_ring(tmp_path, _BLOCK_STYLE)
    assert all(abs(side - _BLOCK_OUTER) <= 1 for side in ring), ring


@needs_libass
def test_libass_ring_matches_export_png(rasterizer: TextRasterizer, tmp_path: Path) -> None:
    """同一份样式,两条导出路径量出来的外圈差 ≤ 1px。修复前 libass 这边是两倍宽。"""
    libass = _libass_ring(tmp_path, _BLOCK_STYLE)
    png = _png_ring(rasterizer, _BLOCK_STYLE)
    assert max(abs(a - b) for a, b in zip(libass, png)) <= 1, (libass, png)


#: 缩放用例的字小一号:放大两倍后整块字仍落在 640×360 画面里。外圈同样是 6px(未封顶)。
_SMALL_BLOCK = {"font_size": 50.0, "stroke_width": 12.0}


@needs_libass
def test_libass_ring_grows_with_title_scale(tmp_path: Path) -> None:
    """花字放大 2 倍:预览与 PNG 路径是整张放大,描边跟着变粗到 12px;libass 的 \\bord 却不跟
    \\fscx 走 —— 不把缩放乘进去,回落导出里的外圈还停在 6px。"""
    ring = _libass_ring(tmp_path, _SMALL_BLOCK, {"scale": 2})
    assert all(abs(side - 2 * _BLOCK_OUTER) <= 1 for side in ring), ring


@needs_libass
def test_libass_ring_follows_scale_keyframes(tmp_path: Path) -> None:
    """缩放打了关键帧(1 → 2,片长 2 秒):\\bord 随 \\t 一起渐变。取 1.9 秒那一帧,缩放 1.95。"""
    keyframes = {"keyframes": [{"t": 0, "scale": 1}, {"t": 1, "scale": 2}]}
    ring = _libass_ring(tmp_path, _SMALL_BLOCK, keyframes, at=1.9)
    assert all(abs(side - 1.95 * _BLOCK_OUTER) <= 1 for side in ring), ring
