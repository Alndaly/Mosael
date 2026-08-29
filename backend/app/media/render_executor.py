from __future__ import annotations

import functools
import logging
import math
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from app.core.child_process import ChildProcess, popen_text, run_logged

from app.core.config import settings
from app.media.probe import guess_kind, probe_has_audio_many
from app.media.render_plan import FILTER_PRESETS, RenderPlan, TextOverlayItem, Transform

"""
RenderExecutor (plan §11): turns a RenderPlan into one FFmpeg invocation.
Every segment yields a normalized [vN][aN] pair (scaled/padded to the output
format, gaps as black + silence), concatenated and encoded to mp4.
"""

logger = logging.getLogger(__name__)

AUDIO_RATE = 48000
DUCK_GAIN = 0.3  # ≈ −10.5 dB: how far a ducked track drops under overlapping audio (闪避)


class RenderExecutionError(RuntimeError):
    def __init__(self, message: str, *, stderr_tail: str = "") -> None:
        super().__init__(message)
        self.stderr_tail = stderr_tail


# 渲染的阶段:准备(建命令/ffmpeg 初始化,进度停在 0)→ 编码(逐帧,有 speed/ETA)→
# 封装(ffmpeg 收到 progress=end 后重写 moov/faststart,常见"卡在 99%")→
# fallback(硬件编码失败,转软件重来)。上层据此给出更可感知的中文提示。
PHASE_PREPARE = "prepare"
PHASE_ENCODE = "encode"
PHASE_FINALIZE = "finalize"
PHASE_FALLBACK = "fallback"


class RenderProgress(NamedTuple):
    """一次进度回调携带的信息:进度分数 + 实时速度/帧率 + 预计剩余秒数。"""

    fraction: float
    speed: float | None  # 相对实时的倍率,ffmpeg 的 speed=12.3x
    fps: float | None
    eta_seconds: float | None


def _parse_ffmpeg_speed(value: str) -> float | None:
    """ffmpeg 的 speed 字段形如 '12.3x' / 'N/A';取不到返回 None。"""
    value = value.strip().rstrip("x")
    if not value or value == "N/A":
        return None
    try:
        speed = float(value)
    except ValueError:
        return None
    return speed if speed > 0 else None


def _progress_from_block(block: dict[str, str], total_us: float) -> RenderProgress:
    """把一整块 ffmpeg -progress 输出解析成 RenderProgress。ETA = 剩余时间线时长 / 速度。"""
    try:
        out_us = int(block.get("out_time_us", "0"))
    except ValueError:
        out_us = 0
    fraction = min(1.0, max(0.0, out_us / total_us)) if total_us > 0 else 0.0
    speed = _parse_ffmpeg_speed(block.get("speed", ""))
    try:
        fps = float(block["fps"]) if block.get("fps") not in (None, "", "N/A") else None
    except ValueError:
        fps = None
    eta: float | None = None
    if speed and total_us > 0:
        remaining_media_s = max(0.0, (total_us - out_us) / 1_000_000)
        eta = remaining_media_s / speed
    return RenderProgress(fraction=fraction, speed=speed, fps=fps, eta_seconds=eta)


def _atempo_chain(speed: float) -> str:
    """atempo filters covering speed, chained because one instance is limited to [0.5, 2]."""
    if speed == 1.0:
        return ""
    parts: list[str] = []
    remaining = speed
    while remaining > 2.0:
        parts.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining /= 0.5
    parts.append(f"atempo={remaining}")
    return ",".join(parts) + ","


def _grade_filter(
    grade: dict[str, float],
    curves: tuple[tuple[str, str], ...] = (),
    lut_path: str = "",
) -> str:
    """Full manual grade → FFmpeg chain, ported from the predecessor project's color_vf.

    Values arrive normalized to [-1, 1]; formulas below convert them back to
    the old panel's native ranges (100-based percentages, ±100 offsets, 0..100
    amounts) so exports look identical to the old app. lut_path, when set, is an
    already-escaped .cube path burned in with lut3d after the primary grade."""
    if not grade and not curves and not lut_path:
        return ""
    value = lambda key: float(grade.get(key, 0.0))  # noqa: E731
    parts: list[str] = []

    # eq: contrast/brightness(+exposure)/saturation/gamma
    contrast = 1 + value("contrast")
    bright_factor = (1 + value("brightness")) * (1 + value("exposure") / 2)
    saturation = 1 + value("saturation")
    gamma = 1 + value("gamma")
    eq_terms = []
    if abs(contrast - 1) > 0.005:
        eq_terms.append(f"contrast={contrast:.3f}")
    if abs(bright_factor - 1) > 0.005:
        eq_terms.append(f"brightness={max(-1.0, min(1.0, bright_factor - 1)):.3f}")
    if abs(saturation - 1) > 0.005:
        eq_terms.append(f"saturation={max(0.0, min(3.0, saturation)):.3f}")
    if abs(gamma - 1) > 0.005:
        eq_terms.append(f"gamma={max(0.1, min(10.0, gamma)):.3f}")
    if eq_terms:
        parts.append("eq=" + ":".join(eq_terms))

    # Tone curve: highlights/shadows/whites/blacks/fade (old-panel ±100 → v*100)
    highlights, shadows = value("highlights") * 100, value("shadows") * 100
    whites, blacks = value("whites") * 100, value("blacks") * 100
    fade = max(0.0, value("fade")) * 100
    if any(abs(v) > 0.5 for v in (highlights, shadows, whites, blacks, fade)):
        y0 = max(0.0, min(0.30, (blacks + fade * 0.6) / 500.0))
        y1 = max(0.70, min(1.0, 1.0 + whites * 0.0015 - fade * 0.0008))
        y75 = max(0.45, min(y1 - 0.02, 0.75 + highlights * 0.0015 + whites * 0.0005 - fade * 0.0003))
        y25 = max(y0 + 0.02, min(y75 - 0.02, 0.25 + shadows * 0.0015 + blacks * 0.0005 + fade * 0.0003))
        parts.append(f"curves=master='0/{y0:.3f} 0.25/{y25:.3f} 0.75/{y75:.3f} 1/{y1:.3f}'")

    if abs(value("hue")) > 0.003:
        parts.append(f"hue=h={value('hue') * 180:.1f}")
    if abs(value("temperature")) > 0.005:
        kelvin = int(max(1000, min(40000, 6500 - value("temperature") * 2500)))
        parts.append(f"colortemperature=temperature={kelvin}")
    if abs(value("vibrance")) > 0.005:
        parts.append(f"vibrance=intensity={max(-2.0, min(2.0, value('vibrance') * 2)):.3f}")
    if abs(value("tint")) > 0.005:
        parts.append(f"colorbalance=gm={max(-1.0, min(1.0, -value('tint') * 0.2)):.3f}:pl=1")
    if value("sharpen") > 0.005:
        parts.append(f"unsharp=5:5:{max(0.0, min(1.5, value('sharpen') * 1.5)):.3f}:5:5:0")
    if value("vignette") > 0.005:
        denominator = max(4.0, 20.0 - 16.0 * min(1.0, value("vignette")))
        parts.append(f"vignette=angle=PI/{denominator:.3f}")
    # User Luma/R/G/B tone curves — a separate curves= filter after the slider-derived
    # tone adjust; ffmpeg composes master∘channel internally. Specs are pre-deduped by
    # the plan (near-dup x would reject the whole chain).
    if curves:
        parts.append("curves=" + ":".join(f"{key}='{spec}'" for key, spec in curves))
    # Creative 3D LUT sits last, on top of the primary correction.
    if lut_path:
        parts.append(f"lut3d=file='{lut_path}'")
    return ("," + ",".join(parts)) if parts else ""


def _even(value: float) -> int:
    """Round to the nearest even int — H.264 needs even dimensions."""
    rounded = int(round(value))
    return rounded if rounded % 2 == 0 else rounded + 1


def _kf_expr(points: tuple[tuple[float, float], ...], prog: str) -> str:
    """Piecewise-linear FFmpeg expression for a property's keyframes over normalized progress.

    `points` are sorted (t, value) with t∈[0,1]; `prog` is an expression giving the current
    normalized progress (e.g. "(t)/3.2"). Outside the first/last keyframe the value holds
    (no extrapolation), matching the frontend's sampleProp. One point → a constant."""
    if not points:
        return "0"
    if len(points) == 1:
        return f"{points[0][1]:.5f}"
    # 从最后一段往前包,让 if(lt(prog,t1),...) 的**最小边界在最外层**:prog 落进哪一段就用哪一段。
    # 若正序包,最外层会变成最大的 t1,任何早期 prog 都先命中最后一段(clip 夹成 0 → 恒取末值),
    # 3 个及以上关键帧的动画会整体卡死在末值(如缩放恒为 1.7,画面全程满屏、看不到放大)。
    expr = f"{points[-1][1]:.5f}"  # progress ≥ last t → last value
    for (t0, v0), (t1, v1) in reversed(list(zip(points, points[1:]))):
        span = t1 - t0
        if span > 1e-6:
            seg = f"({v0:.5f}+({v1 - v0:.5f})*(clip(({prog})-{t0:.6f},0,{span:.6f}))/{span:.6f})"
        else:
            seg = f"{v1:.5f}"
        expr = f"if(lt(({prog}),{t1:.6f}),{seg},{expr})"
    return f"if(lt(({prog}),{points[0][0]:.6f}),{points[0][1]:.5f},{expr})"


def _element_transform(
    in_label: str, tf: Transform, width: int, height: int, prefix: str, *, start: float = 0.0,
    duration: float = 1.0, element_sized: bool = False,
) -> tuple[list[str], str, str, str]:
    """Turn a frame-sized (WxH, cover-filled) element [in_label] into a scaled/rotated/faded
    element ready to overlay, matching the preview's ``translate(x·50%,y·50%) scale rotate`` +
    opacity. Returns (filters, out_label, overlay_x, overlay_y) — x/y are FFmpeg overlay-position
    strings (plain integers when the whole transform is static, time expressions when anything is
    keyframed).

    Every keyframable property compiles to a per-frame FFmpeg expression so the export tracks the
    preview's sampleTransform exactly: scale via ``scale=eval=frame`` (element size follows the
    curve), opacity via a ``geq`` on the alpha plane, rotation via a ``rotate`` angle expression,
    and position via the overlay offset. Filters that expose frame time as ``t`` (scale/rotate/
    overlay) use progress over ``t``; ``geq`` exposes it as ``T``, so opacity uses progress over
    ``T``. ``start``/``duration`` place that progress: the base element is reset to t=0 (start=0),
    an upper-track element keeps timeline time (start=its timeline start).

    When the element's size is animated (scale keyframes), centring can't use a fixed pixel size,
    so the overlay offset is written with overlay's own ``W/H`` (canvas) and ``w/h`` (element)
    variables — the element stays centred on its target as it grows/shrinks. The static, un-keyed
    case keeps the old fast path: a plain-integer overlay offset, no per-frame expression."""

    def prog(var: str) -> str:
        d = max(duration, 1e-6)
        return f"({var}-{start:.6f})/{d:.6f}" if start else f"({var})/{d:.6f}"

    prog_t = prog("t")  # scale / rotate / overlay expose frame time as `t`
    prog_T = prog("T")  # geq exposes it as `T`

    filters: list[str] = []
    scale_pts = tf.keyed("scale")
    animate_scale = len(scale_pts) >= 2
    if animate_scale:
        s_expr = _kf_expr(scale_pts, prog_t)
        # eval=frame re-evaluates w/h each frame; iw/ih are the cover-filled frame (WxH).
        filters.append(f"[{in_label}]scale=w='iw*({s_expr})':h='ih*({s_expr})':eval=frame[{prefix}s]")
    elif element_sized:
        # element_sized(如花字 PNG):元素本就是自然尺寸,按 iw/ih 缩放,而不是套画幅尺寸。
        filters.append(f"[{in_label}]scale=w='iw*{tf.scale:.5f}':h='ih*{tf.scale:.5f}'[{prefix}s]")
    else:
        scaled_w, scaled_h = max(2, _even(width * tf.scale)), max(2, _even(height * tf.scale))
        filters.append(f"[{in_label}]scale={scaled_w}:{scaled_h}[{prefix}s]")
    label = f"{prefix}s"

    op_pts = tf.keyed("opacity")
    animate_op = len(op_pts) >= 2
    rot_pts = tf.keyed("rotation")
    animate_rot = len(rot_pts) >= 2

    needs_alpha = tf.opacity < 1.0 or animate_op or tf.rotation != 0 or animate_rot
    if needs_alpha:
        filters.append(f"[{label}]format=yuva420p[{prefix}a]")
        label = f"{prefix}a"
    if animate_op:
        # Scale the source alpha by the opacity curve; luma/chroma pass through untouched.
        o_expr = _kf_expr(op_pts, prog_T)
        filters.append(
            f"[{label}]geq=lum='lum(X,Y)':cb='cb(X,Y)':cr='cr(X,Y)':a='alpha(X,Y)*clip(({o_expr}),0,1)'[{prefix}o]"
        )
        label = f"{prefix}o"
    elif tf.opacity < 1.0:
        filters.append(f"[{label}]colorchannelmixer=aa={tf.opacity:.4f}[{prefix}o]")
        label = f"{prefix}o"

    if tf.rotation != 0 or animate_rot:
        angle = f"(({_kf_expr(rot_pts, prog_t)})*PI/180)" if animate_rot else f"{math.radians(tf.rotation):.6f}"
        if animate_scale or element_sized:
            # Element size varies per frame (or is input-sized) → rotate onto a per-frame diagonal
            # square from iw/ih (rotate centres the input in the larger ow×oh canvas), no corner clip.
            filters.append(f"[{label}]rotate='{angle}':ow='hypot(iw,ih)':oh='hypot(iw,ih)':c=none[{prefix}r]")
        else:
            # Fixed size → pad to the diagonal square before rotating; box is angle-independent, so an
            # animated angle is just a time expression over the same box.
            scaled_w, scaled_h = max(2, _even(width * tf.scale)), max(2, _even(height * tf.scale))
            box = max(2, _even(math.hypot(scaled_w, scaled_h)))
            pad_x, pad_y = (box - scaled_w) // 2, (box - scaled_h) // 2
            filters.append(f"[{label}]pad={box}:{box}:{pad_x}:{pad_y}:color=black@0[{prefix}p]")
            filters.append(f"[{prefix}p]rotate='{angle}':ow={box}:oh={box}:c=none[{prefix}r]")
        label = f"{prefix}r"

    x_pts, y_pts = tf.keyed("x"), tf.keyed("y")
    animate_pos = len(x_pts) >= 2 or len(y_pts) >= 2
    if animate_pos or animate_scale or element_sized:
        # Centre in output px = frame centre + offset·half-frame; overlay origin = centre − element/2.
        # W/H are the canvas, w/h the (possibly animated) element size — so centring holds as it scales.
        x_expr = _kf_expr(x_pts, prog_t) if x_pts else f"{tf.x:.5f}"
        y_expr = _kf_expr(y_pts, prog_t) if y_pts else f"{tf.y:.5f}"
        ox = f"(0.5+({x_expr})*0.5)*W-w/2"
        oy = f"(0.5+({y_expr})*0.5)*H-h/2"
        return filters, label, ox, oy

    # Fully static position and size → plain-integer overlay offset (no per-frame expression).
    if tf.rotation != 0:
        scaled_w, scaled_h = max(2, _even(width * tf.scale)), max(2, _even(height * tf.scale))
        ow = oh = max(2, _even(math.hypot(scaled_w, scaled_h)))
    else:
        ow, oh = max(2, _even(width * tf.scale)), max(2, _even(height * tf.scale))
    cx = (0.5 + tf.x * 0.5) * width
    cy = (0.5 + tf.y * 0.5) * height
    return filters, label, str(int(round(cx - ow / 2))), str(int(round(cy - oh / 2)))


def _volume_expr(gain: float, keyframes: tuple[tuple[float, float], ...], duration: float) -> str:
    """音量 filter 片段(带尾逗号,可为空):≥2 个关键帧 → volume 时间表达式(段内进度,eval=frame),
    与视频关键帧同一插值内核;否则静态 volume(gain≈1 时省略)。音频经 asetpts 重置到 0,故进度为
    t/duration。"""
    if len(keyframes) >= 2:
        prog = f"(t)/{max(duration, 1e-6):.6f}"
        return f"volume='{_kf_expr(keyframes, prog)}':eval=frame,"
    if abs(gain - 1.0) > 0.001:
        return f"volume={gain},"
    return ""


def _fade_filters(fade_in: float, fade_out: float, duration: float, *, audio: bool) -> str:
    """Leading-comma filter suffix for edge fades in segment-local output time."""
    name = "afade" if audio else "fade"
    chunks: list[str] = []
    if fade_in > 0:
        chunks.append(f",{name}=t=in:st=0:d={fade_in}")
    if fade_out > 0:
        chunks.append(f",{name}=t=out:st={max(0.0, round(duration - fade_out, 6))}:d={fade_out}")
    return "".join(chunks)


def _ass_timestamp(seconds: float) -> str:
    total_cs = max(0, int(round(seconds * 100)))
    hours, rest = divmod(total_cs, 360_000)
    minutes, rest = divmod(rest, 6_000)
    secs, cs = divmod(rest, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _ass_color(hex_color: str, alpha: int = 0) -> str:
    """#RRGGBB → ASS &HAABBGGRR (alpha 0=opaque, 255=transparent)."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"&H{alpha & 0xFF:02X}{b:02X}{g:02X}{r:02X}"


def _ass_text(text: str) -> str:
    # ASS uses {} for override tags and \N for line breaks; neutralise stray braces.
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


_CSS_GENERIC_FONTS = frozenset(
    {"system-ui", "-apple-system", "ui-sans-serif", "ui-serif", "ui-monospace", "ui-rounded",
     "sans-serif", "serif", "monospace", "cursive", "fantasy"}
)


def _resolve_font_stack(font_family: str | None) -> str:
    """A CSS font stack → the one family name ASS can use.

    `Fontname:` takes a single name with no fallback chain, while the preview hands the whole
    stack to the browser. Taking the first entry loses the only resolvable family when the stack
    leads with a generic (`system-ui, ..., "PingFang SC"` → system-ui → a Latin-only default with
    no CJK glyphs), so skip generics and take the first concrete family.

    Newlines are stripped, not escaped: this value goes straight into the ASS `Style:` line, where
    a name carrying \n could inject further Style:/Dialogue: directives.
    """
    for raw in (font_family or "").split(","):
        name = raw.replace("\n", " ").replace("\r", " ").strip().strip("\"'").strip()
        if name and name.lower() not in _CSS_GENERIC_FONTS:
            return name
    return "Sans"


def _ass_bgr(hex_color: str) -> str:
    """#RRGGBB → ASS 覆盖标签用的 &HBBGGRR&(\\1c/\\3c 等,无 alpha)。"""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"&H{b:02X}{g:02X}{r:02X}&"


# libass 把 ASS Fontsize 映射成字形像素的方式和浏览器 CSS font-size 不一样:同一字体(如苹方),
# 浏览器渲染的字形墨迹约 0.93×em,libass 只有约 0.665×em——导出的字幕/花字比预览小约 30%。
# 实测把 Fontsize 乘 1.4,libass 渲染的中文墨迹正好和浏览器一致(200px→280 时墨迹 133→186,
# 与浏览器 CSS 200px 的 186 吻合)。以 CJK 系统字体(苹方/微软雅黑,本 app 默认)标定;纯拉丁
# 字体会略偏大,但本 app 以中文为主。前端字号是原生帧像素,乘这个系数即得视觉一致的 Fontsize。
_ASS_FONTSIZE_SCALE = 1.4


def _text_style_tags(st) -> list[str]:
    """花字外观标签(字号/颜色/描边/阴影/粗斜/字体),不含位置/缩放/旋转/透明度。"""
    tags = [f"\\fs{st.font_size * _ASS_FONTSIZE_SCALE:g}", f"\\1c{_ass_bgr(st.color)}"]
    if st.stroke_width > 0:
        tags.append(f"\\bord{st.stroke_width:g}\\3c{_ass_bgr(st.stroke_color)}")
    else:
        tags.append("\\bord0")
    if st.shadow > 0:
        tags.append(f"\\shad{st.shadow:g}")
    tags.append(f"\\b{1 if st.bold else 0}")
    if st.italic:
        tags.append("\\i1")
    if st.font_family:
        tags.append(f"\\fn{_resolve_font_stack(st.font_family)}")
    return tags


def _kf_sample(points: tuple[tuple[float, float], ...], base: float, t: float) -> float:
    """分段线性采样、端点保持——与前端 sampleProp 同语义(points 已按 t 排序)。"""
    if not points:
        return base
    if len(points) == 1:
        return points[0][1]
    if t <= points[0][0]:
        return points[0][1]
    if t >= points[-1][0]:
        return points[-1][1]
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        if t0 <= t <= t1:
            f = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            return v0 + (v1 - v0) * f
    return base


def _text_overlay_dialogues(item: "TextOverlayItem", w: int, h: int) -> list[str]:
    """一条花字 → 一条或多条 ASS Dialogue。静态时 \\an5+\\pos 单条;打了关键帧时按所有属性的
    关键帧时间点切段,每段一条:位置用 \\move 线性,缩放/旋转/透明度取段首值再用 \\t 渐变到段末,
    拼接成分段线性动画——与预览 sampleTransform(同为分段线性、端点保持)锁步一致。
    由 contracts/transform-cases.json 钉住,前端 transform.parity.test.ts 跑同一份语料。"""
    tf, st = item.transform, item.style
    x_pts, y_pts = tf.keyed("x"), tf.keyed("y")
    s_pts, r_pts, o_pts = tf.keyed("scale"), tf.keyed("rotation"), tf.keyed("opacity")
    base_tags = _text_style_tags(st)
    text = _ass_text(item.text)

    if not any(len(p) >= 2 for p in (x_pts, y_pts, s_pts, r_pts, o_pts)):
        cx, cy = (0.5 + tf.x * 0.5) * w, (0.5 + tf.y * 0.5) * h
        tags = ["\\an5", f"\\pos({cx:.1f},{cy:.1f})"]
        if abs(tf.rotation) > 0.01:
            tags.append(f"\\frz{-tf.rotation:.2f}")
        if abs(tf.scale - 1.0) > 0.001:
            tags.append(f"\\fscx{tf.scale * 100:.1f}\\fscy{tf.scale * 100:.1f}")
        if tf.opacity < 1.0:
            tags.append(f"\\alpha&H{round((1.0 - tf.opacity) * 255):02X}&")
        override = "{" + "".join(tags + base_tags) + "}"
        return [
            f"Dialogue: 0,{_ass_timestamp(item.start)},{_ass_timestamp(item.start + item.duration)},"
            f"Text,,0,0,0,,{override}{text}"
        ]

    stops = sorted({0.0, 1.0} | {p[0] for pts in (x_pts, y_pts, s_pts, r_pts, o_pts) for p in pts})
    lines: list[str] = []
    for a, b in zip(stops, stops[1:]):
        if b - a < 1e-6:
            continue
        cxa, cya = (0.5 + _kf_sample(x_pts, tf.x, a) * 0.5) * w, (0.5 + _kf_sample(y_pts, tf.y, a) * 0.5) * h
        cxb, cyb = (0.5 + _kf_sample(x_pts, tf.x, b) * 0.5) * w, (0.5 + _kf_sample(y_pts, tf.y, b) * 0.5) * h
        sa, sb = _kf_sample(s_pts, tf.scale, a), _kf_sample(s_pts, tf.scale, b)
        ra, rb = _kf_sample(r_pts, tf.rotation, a), _kf_sample(r_pts, tf.rotation, b)
        oa, ob = _kf_sample(o_pts, tf.opacity, a), _kf_sample(o_pts, tf.opacity, b)
        seg_ms = int(round((b - a) * item.duration * 1000))
        tags = [
            "\\an5",
            f"\\move({cxa:.1f},{cya:.1f},{cxb:.1f},{cyb:.1f})",
            f"\\fscx{sa * 100:.1f}\\fscy{sa * 100:.1f}",
            f"\\frz{-ra:.2f}",
            f"\\alpha&H{round((1.0 - oa) * 255):02X}&",
        ]
        parts: list[str] = []
        if abs(sb - sa) > 1e-4:
            parts.append(f"\\fscx{sb * 100:.1f}\\fscy{sb * 100:.1f}")
        if abs(rb - ra) > 1e-4:
            parts.append(f"\\frz{-rb:.2f}")
        if abs(ob - oa) > 1e-4:
            parts.append(f"\\alpha&H{round((1.0 - ob) * 255):02X}&")
        anim = f"\\t(0,{seg_ms},{''.join(parts)})" if parts else ""
        override = "{" + "".join(tags + base_tags) + anim + "}"
        seg_start, seg_end = item.start + a * item.duration, item.start + b * item.duration
        lines.append(
            f"Dialogue: 0,{_ass_timestamp(seg_start)},{_ass_timestamp(seg_end)},Text,,0,0,0,,{override}{text}"
        )
    return lines


def _build_ass(plan: RenderPlan) -> str:
    """A styled ASS subtitle file matching the preview's subtitle_style (font size in native
    frame pixels, text/box colour + box opacity, bold, position, vertical offset)."""
    style = plan.subtitle_style
    w, h = plan.output.width, plan.output.height
    align = {"bottom": 2, "center": 5, "top": 8}.get(style.position, 2)
    scaled_fs = style.font_size * _ASS_FONTSIZE_SCALE  # 见 _ASS_FONTSIZE_SCALE:对齐浏览器视觉字号
    box_alpha = round((1.0 - style.bg_opacity) * 255)
    has_box = style.bg_opacity > 0
    border_style = 3 if has_box else 1  # 3 = opaque box (BackColour), 1 = plain/outline
    outline = round(scaled_fs * 0.12) if has_box else 0  # box padding
    margin_v = 0 if style.position == "center" else round(style.offset / 100.0 * h)
    primary = _ass_color(style.color)
    back = _ass_color(style.bg_color, box_alpha)
    bold = -1 if style.bold else 0
    fontname = _resolve_font_stack(style.font_family)

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {w}\n"
        f"PlayResY: {h}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{fontname},{scaled_fs:g},{primary},&H000000FF,{back},{back},{bold},"
        f"0,0,0,100,100,0,0,{border_style},{outline},0,{align},40,40,{margin_v},1\n"
        # 花字专用样式:BorderStyle=1(仅描边/阴影,绝不画背景框)。花字自己没有背景,
        # 若沿用 Default 样式会连字幕的框一起继承(预览里没有),导出就凭空多一个黑框。
        # 字号/颜色/粗斜/描边/阴影/字体全部由每条 Dialogue 的 \\ 覆盖标签逐条给出;这里只定
        # BorderStyle 和阴影色(&H59… ≈ 预览 rgba(0,0,0,.65) 的投影)。
        "Style: Text,Sans,48,&H00FFFFFF,&H000000FF,&H00000000,&H59000000,-1,0,0,0,"
        "100,100,0,0,1,0,0,5,0,0,0,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = [
        f"Dialogue: 0,{_ass_timestamp(item.start)},{_ass_timestamp(item.start + item.duration)},"
        f"Default,,0,0,0,,{_ass_text(item.text)}"
        for item in plan.subtitles
    ]
    lines += [line for item in plan.text_overlays for line in _text_overlay_dialogues(item, w, h)]
    return header + "\n".join(lines) + "\n"


def _escape_filter_path(path: Path) -> str:
    # Inside filter_complex, colons separate options and backslashes escape.
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _subtitle_overlay_pos(style, pw: int, ph: int, w: int, h: int) -> tuple[int, int]:
    """字幕 PNG 左上角坐标:水平居中 + 按 position/offset 竖直定位(镜像预览 subtitleCss)。

    由 contracts/subtitle-cases.json 钉住,前端 subtitleStyle.parity.test.ts 跑同一份语料。
    offset 是画幅高百分比;center 位置里 offset 是相对元素高(与前端 translate 的 % 语义一致)。"""
    x = max(0, (w - pw) // 2)
    off = style.offset / 100.0
    if style.position == "top":
        y = int(round(off * h))
    elif style.position == "center":
        y = int(round(h / 2 + off * ph - ph / 2))
    else:  # bottom
        y = int(round(h - off * h - ph))
    return x, y


# 从深处剪一小段时,靠 trim 滤镜切会逼 ffmpeg 从第 0 帧一路解码到 src_in——长素材里这一步
# 能占掉绝大多数导出时间(表现为进度长时间卡在个位数、speed≈0.0x)。改用输入级 -ss 快进:
# ffmpeg 先跳到 src_in 之前最近的关键帧,默认 accurate_seek 会精确解码并丢弃到 src_in、并把
# 该点重置为时间 0,所以 trim 改成从 0 起算、长度不变,帧仍然精确。src_in≈0(图片、从头的
# 片段)不加 -ss,行为与之前完全一致。
_INPUT_SEEK_THRESHOLD = 0.05


def _seek_and_trim(src_in: float, src_out: float) -> tuple[list[str], float, float]:
    """返回 (输入前置的 -ss 参数, trim 起点, trim 终点)。src_in 够大才快进,否则保持原样。"""
    if src_in > _INPUT_SEEK_THRESHOLD:
        return ["-ss", f"{src_in:.6f}"], 0.0, round(src_out - src_in, 6)
    return [], src_in, src_out


_IMAGE_LOOP_PAD = 0.2  # -t 相对 trim 末尾留的小余量,保证末帧不缺


def _image_loop_args(path: Path, trim_end: float) -> list[str]:
    """静态图片一律 -loop 成真正逐帧推进的视频流。

    图片默认进 ffmpeg 只有**一帧**,时间戳不推进,于是任何按时间求值的东西都停在 t=0:
      · 自身的 transform 关键帧动画 / 淡入淡出 → 恒取首值(表现为动画失效、透明度卡 0 全黑);
      · 叠在它上面的 overlay 的 enable='between(t,…)' → 窗口永不命中(图片作底轨时上层画中画整段消失);
      · 图片自己作 overlay 时同理 → 该叠层根本不出现。
    这三类都真实发生过。曾经用一个 needs_time 开关只在"看起来需要时间轴"时才 loop,但需求方
    (自身动画 / 上层 / 下层)分散在各处,每个调用点都得记得算对——两处算漏就是两个 bug。
    索性去掉开关:图片一律逐帧,正确性由构造保证,代价只是极小的解码开销。
    -t 必须给(无限流会让 concat 永远卡在这一段),取 trim 末尾加点余量保住末帧。"""
    if guess_kind(path) == "image":
        return ["-loop", "1", "-t", f"{max(trim_end, 0.04) + _IMAGE_LOOP_PAD:.6f}"]
    return []


def _base_video_chain(input_index: int, i: int, src_in: float, src_out: float, setpts: str, width: int, height: int, fps: float, tail: str, fill_mode: str) -> str:
    """[input:v] → [vi] 的完整视频链;按画幅填充模式选择裁剪/留黑边/模糊背景。"""
    head = f"[{input_index}:v]trim=start={src_in}:end={src_out},setpts={setpts}"
    end = f",fps={fps},format=yuv420p,setsar=1{tail}[v{i}]"
    if fill_mode == "cover":
        return f"{head},scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}{end}"
    if fill_mode == "blur":
        return (
            f"{head},split=2[bg{i}][fg{i}];"
            f"[bg{i}]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},gblur=sigma=20[bgb{i}];"
            f"[fg{i}]scale={width}:{height}:force_original_aspect_ratio=decrease[fgc{i}];"
            f"[bgb{i}][fgc{i}]overlay=(W-w)/2:(H-h)/2{end}"
        )
    # contain(留黑边)
    return f"{head},scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2{end}"


# 硬件 H.264 编码器,顺序即优先级。VideoToolbox 是 macOS 系统媒体引擎(Apple Silicon 与
# Intel Mac 都走);NVENC/QSV/AMF 分别对应 Windows 上的 N卡 / Intel 核显 / A卡。同机极少
# 同时具备多个,先探到谁用谁即可。
_HW_ENCODER_PRIORITY = ("h264_videotoolbox", "h264_nvenc", "h264_qsv", "h264_amf")


@functools.lru_cache(maxsize=1)
def _available_hw_encoder() -> str | None:
    """探测本机 ffmpeg 支持哪个硬件 H.264 编码器,进程内缓存一次。

    只看 `ffmpeg -encoders` 里“列出”的名字 —— 是否真能跑还取决于驱动/权限/是否有显卡,
    所以真正编码失败时 execute_render 会回落到软件 libx264 再跑一遍。探测本身失败(ffmpeg
    缺失等)按“无硬件”处理。"""
    try:
        proc = run_logged(
            [settings.ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=20, what="硬件编码器探测", level=logging.DEBUG)
    except Exception:
        return None
    listed = proc.stdout or ""
    for name in _HW_ENCODER_PRIORITY:
        if name in listed:
            return name
    return None


def _target_bitrate_kbps(output) -> int:
    """由 分辨率×帧率×每像素比特(bpp) 推目标码率,bpp 受 CRF 调节。

    硬件编码器大多没有 x264 那种成熟的 CRF 恒定质量,得给码率。把用户设的 CRF 映射成 bpp:
    CRF 20 ≈ 0.10 bpp(1080p30 ≈ 6Mbps 的高画质),CRF 每 +6 码率减半、每 −6 翻倍,和 x264
    的 CRF 手感一致。最后夹在 [0.5, 120] Mbps 的合理区间内。"""
    width = max(int(output.width), 2)
    height = max(int(output.height), 2)
    fps = output.fps if getattr(output, "fps", 0) and output.fps > 0 else 30.0
    bpp = 0.10 * (2.0 ** ((20 - int(output.crf)) / 6.0))
    kbps = width * height * fps * bpp / 1000.0
    return int(max(500.0, min(kbps, 120_000.0)))


def _hw_encode_args(encoder: str, output) -> list[str]:
    """给定硬件编码器的完整 -c:v 参数(码率模式 + yuv420p,保证各家播放器都能放)。"""
    kbps = _target_bitrate_kbps(output)
    common = [
        "-c:v",
        encoder,
        "-b:v",
        f"{kbps}k",
        "-maxrate",
        f"{int(kbps * 1.5)}k",
        "-bufsize",
        f"{kbps * 2}k",
        "-pix_fmt",
        "yuv420p",
    ]
    if encoder == "h264_videotoolbox":
        # 非实时(-realtime 0)换更好画质;-allow_sw 1 在个别机器无硬件编码单元时回落苹果的
        # 软件实现而不是直接报错。
        return common + ["-realtime", "0", "-allow_sw", "1"]
    if encoder == "h264_nvenc":
        # p5 是质量/速度的平衡档,vbr 走上面的 b:v/maxrate,spatial_aq 改善平坦区域观感。
        return common + ["-preset", "p5", "-rc", "vbr", "-spatial-aq", "1"]
    if encoder == "h264_qsv":
        return common + ["-preset", "medium"]
    if encoder == "h264_amf":
        return common + ["-quality", "balanced", "-rc", "vbr_peak"]
    return common


def _video_encode_args(output, *, force_software: bool = False) -> list[str]:
    """导出的视频编码参数:能用硬件就用硬件(码率模式),否则回落 libx264+CRF。

    force_software=True 用于硬件编码失败后的重试,强制走软件编码。"""
    if settings.hw_encode and not force_software:
        encoder = _available_hw_encoder()
        if encoder:
            return _hw_encode_args(encoder, output)
    return [
        "-c:v",
        "libx264",
        "-preset",
        output.encode_preset,
        "-crf",
        str(output.crf),
        "-pix_fmt",
        "yuv420p",
    ]


def build_ffmpeg_command(
    plan: RenderPlan,
    resolve: Callable[[str], Path],
    output_path: Path,
    *,
    force_software: bool = False,
    text_pngs: dict | None = None,
    still_at: float | None = None,
) -> list[str]:
    """…still_at 给了就**只出那一时刻的一帧**(一张图,不是一段片子)。

    **滤镜图一个字都不改** —— 保真度全在那里:变换、调色、花字、字幕、叠层。另写一条"取当前帧"
    的路的话,它迟早和成片长得不一样,而这种不一样是最难发现的:画面看着对,只是少了一层字。
    """
    width, height, fps = plan.output.width, plan.output.height, plan.output.fps
    # Probe every source we will ask about up front, concurrently, instead of once per clip as
    # the command is assembled — the probes are independent and each one is just waiting on an
    # ffprobe child. Repeated sources collapse to one probe.
    has_audio = probe_has_audio_many(
        [resolve(segment.source.file_key) for segment in plan.video_segments
         if segment.kind == "clip" and segment.source is not None]
        + [resolve(item.source.file_key) for item in plan.audio_overlays if item.optional]
    )
    args: list[str] = [settings.ffmpeg, "-y", "-v", "error", "-progress", "pipe:1", "-nostats"]
    filters: list[str] = []
    pair_labels: list[str] = []
    input_index = 0

    for i, segment in enumerate(plan.video_segments):
        if segment.kind == "clip" and segment.source is not None:
            path = resolve(segment.source.file_key)
            src = segment.source
            seek, tin, tout = _seek_and_trim(src.src_in, src.src_out)
            args += _image_loop_args(path, tout) + seek + ["-i", str(path)]
            setpts = "PTS-STARTPTS" if segment.speed == 1.0 else f"(PTS-STARTPTS)/{segment.speed}"
            # Picture fade (画面淡变, fade to/from black) is independent of the audio fade below.
            video_fades = _fade_filters(segment.video_fade_in, segment.video_fade_out, segment.duration, audio=False)
            preset = f",{FILTER_PRESETS[segment.filter]}" if segment.filter else ""
            lut_path = _escape_filter_path(resolve(segment.lut)) if segment.lut else ""
            preset += _grade_filter(dict(segment.grade), segment.curves, lut_path)
            if segment.transform.is_identity:
                filters.append(
                    _base_video_chain(
                        input_index, i, tin, tout, setpts, width, height, fps,
                        f"{preset}{video_fades}", plan.output.fill_mode,
                    )
                )
            else:
                # Free-element clip: cover-fill to frame, grade/fade, then composite over black
                # at its transform (matches the preview compositor; fill_mode is moot here since
                # the element is cover-filled like the preview's objectFit:cover).
                filters.append(
                    f"[{input_index}:v]trim=start={tin}:end={tout},setpts={setpts},"
                    f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
                    f"{preset}{video_fades},fps={fps},setsar=1[elt{i}]"
                )
                # setpts reset the segment to t=0, so progress runs over start=0..duration.
                tfilters, tlabel, ox, oy = _element_transform(
                    f"elt{i}", segment.transform, width, height, f"bt{i}", start=0.0, duration=segment.duration
                )
                filters += tfilters
                filters.append(
                    # 背景必须给时长:无 :d 的 color 是无限流,concat 会永远停在这一段推不动,
                    # 整条 filtergraph 疯狂缓冲——带动画的图片幻灯片导出因此慢到 0.0x(见回归测试)。
                    f"color=black:s={width}x{height}:r={fps}:d={segment.duration}[bg{i}];"
                    f"[bg{i}][{tlabel}]overlay=x='{ox}':y='{oy}',format=yuv420p,setsar=1[v{i}]"
                )
            if has_audio.get(path, False) and not plan.mute_base_audio and not segment.muted:
                tempo = _atempo_chain(segment.speed)
                audio_fades = _fade_filters(segment.fade_in, segment.fade_out, segment.duration, audio=True)
                # The clip's own gain (增益) mixes its audio, like a video clip's linked audio in PR/DaVinci.
                gain = _volume_expr(segment.gain, segment.gain_keyframes, segment.duration)
                filters.append(
                    f"[{input_index}:a]atrim=start={tin}:end={tout},asetpts=PTS-STARTPTS,{tempo}"
                    f"{gain}aresample={AUDIO_RATE},aformat=channel_layouts=stereo{audio_fades}[a{i}]"
                )
            else:
                # No source audio, or the base track is silenced by a solo elsewhere.
                filters.append(
                    f"anullsrc=r={AUDIO_RATE}:cl=stereo,atrim=0:{segment.duration}[a{i}]"
                )
            input_index += 1
        else:
            filters.append(
                f"color=black:s={width}x{height}:r={fps},trim=0:{segment.duration},format=yuv420p,setsar=1[v{i}]"
            )
            filters.append(f"anullsrc=r={AUDIO_RATE}:cl=stereo,atrim=0:{segment.duration}[a{i}]")
        pair_labels.append(f"[v{i}][a{i}]")

    n = len(plan.video_segments)
    filters.append(f"{''.join(pair_labels)}concat=n={n}:v=1:a=1[vbase][abase]")

    # Upper-video-track clips composited over the base, each a free element at its transform
    # (cover-filled to the frame then scaled/rotated/faded — same model as the base track).
    video_label = "[vbase]"
    for i, overlay in enumerate(plan.overlays):
        path = resolve(overlay.source.file_key)
        src = overlay.source
        seek, tin, tout = _seek_and_trim(src.src_in, src.src_out)
        args += _image_loop_args(path, tout) + seek + ["-i", str(path)]
        filters.append(
            f"[{input_index}:v]trim=start={tin}:end={tout},"
            f"setpts=PTS-STARTPTS+{overlay.start}/TB,"
            f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}[oelt{i}]"
        )
        # Overlay lives on the main timeline; progress runs over its start..start+duration.
        tfilters, tlabel, ox, oy = _element_transform(
            f"oelt{i}", overlay.transform, width, height, f"ot{i}", start=overlay.start, duration=overlay.duration
        )
        filters += tfilters
        out_label = f"[vov{i}]"
        filters.append(
            # eof_action=repeat(而不是 pass):叠加流常常比它的 enable 窗口短一丁点 —— 用了
            # 输入级 -ss 快进后,解码从 src_in 之后的第一帧开始,尾巴就少了不到一帧。pass 会在
            # 流结束的瞬间把底层放出来,于是**每个叠加片段的最后 1~2 帧变黑**,连续片段之间
            # 看起来就是"切换处闪一下黑"(blackdetect 在真实工程里逐个边界都抓到了)。
            # repeat 保持最后一帧,窗口由 enable 关闭,不会多画。
            f"{video_label}[{tlabel}]overlay=x='{ox}':y='{oy}':eof_action=repeat:"
            f"enable='between(t,{overlay.start},{overlay.start + overlay.duration})'{out_label}"
        )
        video_label = out_label
        input_index += 1

    # 字幕 + 花字:优先叠加「按预览 CSS 用无头 Chromium 渲染的透明 PNG」(text_pngs),逐像素
    # 对齐预览(字体/字号/描边/阴影/背景圆角全一致);拿不到(找不到前端 dist/Chromium,或测试
    # 关闭)时回落到下面的 ASS(libass)烧字。每条 PNG 都 -loop 成时间线上的一段,再叠加。
    if text_pngs is not None:
        for item, (png, pw, ph) in zip(plan.subtitles, text_pngs.get("subtitles", [])):
            args += ["-loop", "1", "-framerate", f"{fps:g}", "-t", f"{item.duration + 0.2:.6f}", "-i", str(png)]
            sx, sy = _subtitle_overlay_pos(plan.subtitle_style, pw, ph, width, height)
            filters.append(f"[{input_index}:v]setpts=PTS-STARTPTS+{item.start}/TB[stin{input_index}]")
            out_label = f"[vts{input_index}]"
            filters.append(
                f"{video_label}[stin{input_index}]overlay=x={sx}:y={sy}:eof_action=repeat:"
                f"enable='between(t,{item.start},{item.start + item.duration})'{out_label}"
            )
            video_label = out_label
            input_index += 1
        for k, (item, (png, pw, ph)) in enumerate(zip(plan.text_overlays, text_pngs.get("text_overlays", []))):
            args += ["-loop", "1", "-framerate", f"{fps:g}", "-t", f"{item.duration + 0.2:.6f}", "-i", str(png)]
            # 花字 PNG 当作一个自由元素:移到时间线起点,再复用元素变换管线施加动画,以文字中心
            # 对齐 (cx,cy)。element_sized=True 让缩放/定位按 PNG 自然尺寸而非画幅尺寸。
            filters.append(f"[{input_index}:v]setpts=PTS-STARTPTS+{item.start}/TB[htin{k}]")
            tfilters, tlabel, tox, toy = _element_transform(
                f"htin{k}", item.transform, width, height, f"ht{k}",
                start=item.start, duration=item.duration, element_sized=True,
            )
            filters += tfilters
            out_label = f"[vtx{k}]"
            filters.append(
                f"{video_label}[{tlabel}]overlay=x='{tox}':y='{toy}':eof_action=repeat:"
                f"enable='between(t,{item.start},{item.start + item.duration})'{out_label}"
            )
            video_label = out_label
            input_index += 1
    elif plan.subtitles or plan.text_overlays:
        ass_path = output_path.with_suffix(".ass")
        ass_path.parent.mkdir(parents=True, exist_ok=True)
        ass_path.write_text(_build_ass(plan), encoding="utf-8")
        out_label = "[vsub]"
        # fontsdir lets libass find a font that is uploaded rather than installed; without it the
        # family in the Style: line resolves to nothing and the burn silently uses a default face.
        # 字幕或任一花字用了上传字体都要给 fontsdir(都指向同一个 workspace 字体根,libass 递归扫描)。
        fonts_dir = plan.subtitle_style.font_dir or next(
            (item.style.font_dir for item in plan.text_overlays if item.style.font_dir), ""
        )
        fonts_arg = f":fontsdir='{_escape_filter_path(Path(fonts_dir))}'" if fonts_dir else ""
        filters.append(
            f"{video_label}subtitles=filename='{_escape_filter_path(ass_path)}'{fonts_arg}{out_label}"
        )
        video_label = out_label

    # Audio-track clips + overlay video-track clips' audio, mixed over the base audio. An
    # overlay source may be a video without an audio stream (or an image) — probe and skip it,
    # since mapping [n:a] on a source with no audio would fail the whole render.
    audio_label = "[abase]"
    if plan.audio_overlays:
        mix_inputs = ["[abase]"]
        for i, item in enumerate(plan.audio_overlays):
            path = resolve(item.source.file_key)
            if item.optional and not has_audio.get(path, False):
                continue  # overlay video-track source with no audio stream
            src = item.source
            seek, tin, tout = _seek_and_trim(src.src_in, src.src_out)
            args += seek + ["-i", str(path)]
            delay_ms = int(item.start * 1000)
            audio_fades = _fade_filters(item.fade_in, item.fade_out, item.duration, audio=True)
            # Ducking: after adelay the stream is on timeline time, so the enable windows are
            # absolute — drop to DUCK_GAIN while a non-ducked clip overlaps, full gain elsewhere.
            duck = ""
            if item.duck_windows:
                enable = "+".join(f"between(t,{a},{b})" for a, b in item.duck_windows)
                duck = f",volume=enable='{enable}':volume={DUCK_GAIN}"
            filters.append(
                f"[{input_index}:a]atrim=start={tin}:end={tout},asetpts=PTS-STARTPTS,"
                f"{_volume_expr(item.gain, item.gain_keyframes, item.duration)}"
                f"aresample={AUDIO_RATE},aformat=channel_layouts=stereo{audio_fades},"
                f"adelay={delay_ms}:all=1{duck}[aov{i}]"
            )
            mix_inputs.append(f"[aov{i}]")
            input_index += 1
        if len(mix_inputs) > 1:
            filters.append(f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:normalize=0[amix]")
            audio_label = "[amix]"

    if still_at is not None:
        #: 只取一帧:画面那一路照旧,音频整条不要(一张图没有声音),输出换成单帧图片。
        #: -ss 放在 filter_complex **之后** —— 输出侧 seek,滤镜图照常从头算,
        #: 那些跟时间走的东西(关键帧、淡入淡出、字幕的出入点)才会落在正确的位置上。
        args += [
            "-filter_complex",
            ";".join(filters),
            "-map",
            video_label,
            "-ss",
            f"{max(still_at, 0.0):.3f}",
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(output_path),
            #: **音频那条也得有人接。** 滤镜图和成片的是同一份(保真度全在那里),而它的
            #: concat 会同时吐出画面和声音 —— 只接画面的话 ffmpeg 直接拒跑:
            #: 「Filter 'concat' has output 1 (abase) unconnected」。丢进 null 就行,
            #: 一张图本来就不要声音。
            "-map",
            audio_label,
            "-f",
            "null",
            "-",
        ]
        return args

    args += [
        "-filter_complex",
        ";".join(filters),
        "-map",
        video_label,
        "-map",
        audio_label,
        "-t",
        str(plan.timeline_duration),
        # 强制恒定帧率输出:多段(图片+视频)concat 会产生 VFR,mp4 头里 avg_frame_rate 变成
        # 十几帧、播放器据此播得一卡一卡(逐帧其实是 30fps,但时间戳不规整)。输出 -r 把成片钉成
        # 规整的 30fps CFR(各版本 ffmpeg 通用),和预览一样顺。
        "-r",
        str(plan.output.fps),
        *_video_encode_args(plan.output, force_software=force_software),
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    return args


def _png_size(data: bytes) -> tuple[int, int]:
    """从 PNG 头(IHDR)读宽高,免依赖。"""
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def _rasterize_text(plan: RenderPlan, workdir: Path) -> dict | None:
    """把每条字幕/花字按预览 CSS 渲染成透明 PNG,返回 {subtitles, text_overlays} 列表(元素为
    (png路径, 宽, 高));关掉开关 / 找不到前端 dist / Chromium 失败时返回 None → 回落 ASS。"""
    if not settings.text_rasterize:
        return None
    if not (plan.subtitles or plan.text_overlays):
        return {"subtitles": [], "text_overlays": []}
    try:
        from app.media.text_render import TextRasterizer

        tr = TextRasterizer(plan.output.width, plan.output.height)
        if not tr.available():
            logger.warning("frontend dist not found; text burn falls back to ASS")
            return None
        result: dict = {"subtitles": [], "text_overlays": []}
        stem = workdir / output_stem(plan)
        with tr:
            for i, item in enumerate(plan.subtitles):
                png = tr.render_subtitle(item.text, plan.subtitle_style)
                path = stem.with_name(f"{stem.name}.sub{i}.png")
                path.write_bytes(png)
                result["subtitles"].append((path, *_png_size(png)))
            for i, item in enumerate(plan.text_overlays):
                png = tr.render_huazi(item.text, item.style)
                path = stem.with_name(f"{stem.name}.txt{i}.png")
                path.write_bytes(png)
                result["text_overlays"].append((path, *_png_size(png)))
        return result
    except Exception:
        logger.exception("text rasterization failed; falling back to ASS burn")
        return None


def render_still(plan: RenderPlan, resolve: Callable[[str], Path], output_path: Path, at: float) -> Path:
    """把时间线在 `at` 处的**合成画面**渲成一张图。

    **走和成片同一条命令**(build_ffmpeg_command,只是换了输出那一段)。另写一条的话它迟早和
    成片长得不一样,而这种不一样最难发现:画面看着对,只是少了一层花字 —— 而那正是预览里
    用 DOM 叠出来的、canvas 抓不到的东西。

    这里**也要先把文字渲成 PNG**:少这一步,取出来的帧就是没有字幕的那一版。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    text_pngs = _rasterize_text(plan, output_path.parent)
    command = build_ffmpeg_command(plan, resolve, output_path, text_pngs=text_pngs, still_at=at)
    try:
        run_logged(command, check=True, capture_output=True, timeout=180, what="取当前帧")
    except subprocess.SubprocessError as exc:
        raise RenderExecutionError("取当前帧失败") from exc
    if not output_path.is_file() or output_path.stat().st_size == 0:
        #: 时间点落在片尾之后:ffmpeg 成功退出但什么都不写。空文件比报错更难查。
        raise RenderExecutionError("这个时间点上没有画面 —— 是不是超过片长了?")
    return output_path


def output_stem(plan: RenderPlan) -> str:
    return f"text_{plan.sequence_id}"


def execute_render(
    plan: RenderPlan,
    resolve: Callable[[str], Path],
    output_path: Path,
    on_progress: Callable[[RenderProgress], None] | None = None,
    on_child: Callable[[ChildProcess], None] | None = None,
    on_phase: Callable[[str], None] | None = None,
) -> None:
    """Run FFmpeg, reporting progress from its -progress stream.

    `on_progress` gets a RenderProgress (fraction + live speed/fps/ETA) per progress block, so the
    caller can show something more legible than a bare percentage. `on_phase` announces the coarse
    stage (prepare/encode/finalize/fallback) so a job stuck building filters or rewriting the moov
    box reads as work-in-progress rather than a frozen bar. `on_child` hands the caller the running
    child so a cancellation can kill it — without that, cancel only flipped a database row while
    ffmpeg ran to completion.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    total_us = max(plan.timeline_duration, 0.001) * 1_000_000

    hw_encoder = _available_hw_encoder() if settings.hw_encode else None
    logger.info(
        "render start: encoder=%s output=%dx%d@%gfps duration=%.1fs → %s",
        hw_encoder or "libx264",
        plan.output.width,
        plan.output.height,
        plan.output.fps,
        plan.timeline_duration,
        output_path.name,
    )

    # 起一次无头 Chromium 把所有字幕/花字渲染成 PNG(软件回落时复用同一批,不重复渲染)。
    text_pngs = _rasterize_text(plan, output_path.parent)

    def run_once(*, force_software: bool) -> tuple[int, str, bool]:
        if on_phase is not None:
            on_phase(PHASE_FALLBACK if force_software else PHASE_PREPARE)
        # build_ffmpeg_command probes every source; that is part of the "preparing" wait.
        command = build_ffmpeg_command(
            plan, resolve, output_path, force_software=force_software, text_pngs=text_pngs
        )
        process = popen_text(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        # ffmpeg's stderr must be drained WHILE we read progress off stdout. A source it cannot
        # fully decode emits an error per frame even at -v error; once that fills the pipe ffmpeg
        # blocks writing it, stops emitting progress, and both sides wait forever with the job
        # stuck in `running` and no way out but killing the backend.
        child = ChildProcess(process)
        if on_child is not None:
            on_child(child)
        block: dict[str, str] = {}
        encoding = False
        for line in child.raw_lines():
            line = line.strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            block[key] = value
            if key != "progress":  # accumulate until the block terminator
                continue
            if not encoding and on_phase is not None:
                encoding = True
                on_phase(PHASE_ENCODE)  # first block ⇒ frames are flowing
            if value == "end" and on_phase is not None:
                on_phase(PHASE_FINALIZE)  # -progress end; ffmpeg still writes faststart moov
            if on_progress is not None:
                on_progress(_progress_from_block(block, total_us))
            block = {}
        stderr_tail = child.finish()
        return process.returncode or 0, stderr_tail, child.killed

    returncode, stderr_tail, killed = run_once(force_software=False)
    # A hardware encoder can be *listed* by ffmpeg yet fail at runtime (no GPU, driver/permission,
    # unsupported dimensions). When that happens — and only when we weren't the ones who stopped it
    # (cancel/timeout set `killed`) — fall back to software libx264 once so the export still lands.
    hw_used = hw_encoder is not None
    if returncode != 0 and hw_used and not killed:
        logger.warning(
            "render: hardware encoder %s failed (rc=%s), retrying with software libx264",
            hw_encoder,
            returncode,
        )
        returncode, stderr_tail, killed = run_once(force_software=True)
    if returncode != 0:
        logger.error("render: ffmpeg failed (rc=%s):\n%s", returncode, stderr_tail)
        raise RenderExecutionError(
            f"FFmpeg exited with code {returncode}",
            stderr_tail=stderr_tail,
        )
