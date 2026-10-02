from __future__ import annotations

import bisect
import contextlib
import functools
import logging
import math
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import NamedTuple

import numpy as np

from app.core.i18n import LocalizedError
from app.core.child_process import ChildProcess, popen_text, run_logged

from app.core.config import settings
from app.core.text import blame_line
from app.media.probe import guess_kind, probe_has_audio_many
from app.media.tempo import atempo_filters
from app.media.render_plan import (
    AiLabelItem,
    FILTER_PRESETS,
    ClipAppearance,
    RenderPlan,
    Segment,
    ShadowSpec,
    TextOverlayItem,
    Transform,
)

"""
RenderExecutor (plan §11): turns a RenderPlan into one FFmpeg invocation.
Every segment yields a normalized [vN][aN] pair (scaled/padded to the output
format, gaps as black + silence), concatenated and encoded to mp4.
"""

logger = logging.getLogger(__name__)

AUDIO_RATE = 48000
DUCK_GAIN = 0.3  # ≈ −10.5 dB: how far a ducked track drops under overlapping audio (闪避)


#: 闪避压下去 / 抬回来用多久(秒):压在人声开口**之前**的 30 ms 里,抬在人声结束**之后**的 30 ms 里。
#: 此前是一刀切的 volume=enable:音乐在窗口边上瞬间掉 10 dB,听得见一声「咔」。
DUCK_RAMP = 0.03
#: 增益包络的采样率。包络是分段线性的(平台 + 30 ms 斜坡),1 kHz 足够,进滤镜图时再升到 48 kHz。
DUCK_ENVELOPE_RATE = 1000


def _duck_envelope(windows: tuple[tuple[float, float], ...], length: float) -> np.ndarray:
    """闪避的增益包络:窗口外 1、窗口里 DUCK_GAIN,两头各一段 DUCK_RAMP 的线性斜坡。时间是时间线时间。

    **为什么是一条预先算好的包络,而不是 volume 的 enable 表达式**:此前每个窗口拼一段 `between(t,a,b)`,
    一条配音一个窗口 —— 译配一集一两百句,表达式超过 ffmpeg 的解析上限,导出直接失败(实测 100 段左右
    开始挂)。包络是一个文件,窗口再多它也只是长一点;窗口挨得比两段斜坡还近时取两者的小值,中间不回弹。

    不用 sidechaincompress(按人声电平触发):预览(audioMix.audioGainAt)是按窗口压到 0.3 的,导出改成
    按电平压,两边听起来就不一样了 —— 而且基底轨的人声和配音哪个算「人声」也说不清。"""
    rate = DUCK_ENVELOPE_RATE
    envelope = np.ones(int(math.ceil(length * rate)) + 1, dtype=np.float32)
    ramp = max(1, int(round(DUCK_RAMP * rate)))
    down = np.linspace(1.0, DUCK_GAIN, ramp + 1, dtype=np.float32)
    for start, end in windows:
        lo, hi = int(round(start * rate)), int(round(end * rate))
        pieces = ((lo - ramp, down), (lo, np.full(max(0, hi - lo), DUCK_GAIN, np.float32)), (hi, down[::-1]))
        for at, values in pieces:
            first, last = max(0, at), min(len(envelope), at + len(values))
            if last > first:
                envelope[first:last] = np.minimum(envelope[first:last], values[first - at:last - at])
    return envelope


def _duck_input(windows: tuple[tuple[float, float], ...], length: float, path: Path) -> list[str]:
    """把包络写成裸 float32 文件,返回读它的输入参数。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    _duck_envelope(windows, length).astype("<f4").tofile(path)
    return ["-f", "f32le", "-ar", str(DUCK_ENVELOPE_RATE), "-ac", "1", "-i", str(path)]


def _duck_apply(label: str, envelope_input: int, out: str) -> str:
    """[label] × 包络 → [out]。包络升到 48 kHz、复制成双声道(不走默认的单→双混音,那会 −3 dB),再逐采样相乘。
    包络比声音长一截(见调用处),amultiply 跟着短的那条结束,不会截掉声音。"""
    return (f"[{envelope_input}:a]aresample={AUDIO_RATE},pan=stereo|c0=c0|c1=c0[{out}env];"
            f"{label}[{out}env]amultiply[{out}]")


class RenderExecutionError(LocalizedError, RuntimeError):
    """渲染没跑成。带文案 key(`renderErr_*`);`stderr_tail` 是 ffmpeg 的原话,给诊断用。"""

    def __init__(self, key: str, *, stderr_tail: str = "", **params: object) -> None:
        super().__init__(key, **params)
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


def _is_free_element(appearance: ClipAppearance) -> bool:
    """有蒙版或投影的片段是「自由元素」:画幅那么大(铺满再裁到画幅),蒙版和投影画在这一块上 ——
    契约 contracts/clip-free-element-geometry.json。和预览 scenePaint 的 freeElement 同一条判据:
    看**开没开**,不看外观字典和默认值是否逐字段相等(关着的投影改过颜色,也还是没有投影)。"""
    return appearance.mask.shape != "none" or appearance.shadow.enabled


def _element_fit(appearance: ClipAppearance, fit: str, width: int, height: int) -> str:
    """素材 → 元素的那一步缩放(不带前后逗号)。

    自由元素:铺满画幅再裁成画幅大小。其余:按 fit(increase 铺满 / decrease 装进)缩到画幅,**保持素材自己的
    宽高比、不裁** —— 预览 scenePaint 里就是 mw×fit、mh×fit 那么大的一块。"""
    if _is_free_element(appearance):
        return f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    return f"scale={width}:{height}:force_original_aspect_ratio={fit}:force_divisible_by=2"


def _appearance_filters(
    in_label: str,
    appearance: ClipAppearance,
    width: int,
    height: int,
    prefix: str,
) -> tuple[list[str], str, bool]:
    """Apply the mask in local element space before transform.

    Returns filters, output label, and whether the resulting element must be scaled from its own
    dimensions (circle centre-crops to a square). The drop shadow is **not** drawn here — it lives
    in frame pixels and is composited after placement (see _with_shadow).
    """
    filters: list[str] = []
    label = in_label
    element_width, element_height = width, height
    if appearance.mask.shape == "circle":
        side = min(width, height)
        filters.append(f"[{label}]crop={side}:{side}:(iw-{side})/2:(ih-{side})/2[{prefix}crop]")
        label = f"{prefix}crop"
        element_width = element_height = side

    if appearance.mask.shape != "none":
        if appearance.mask.shape == "circle":
            alpha = "if(lte(pow(X-W/2,2)+pow(Y-H/2,2),pow(min(W,H)/2,2)),alpha(X,Y),0)"
        else:
            radius = min(element_width, element_height) * appearance.mask.radius
            alpha = (
                "if(lte("
                f"pow(max({radius:.4f}-min(X,W-1-X),0),2)+"
                f"pow(max({radius:.4f}-min(Y,H-1-Y),0),2),"
                f"pow({radius:.4f},2)),alpha(X,Y),0)"
            )
        filters.append(
            f"[{label}]format=yuva420p,geq=lum='lum(X,Y)':cb='cb(X,Y)':cr='cr(X,Y)':a='{alpha}'[{prefix}mask]"
        )
        label = f"{prefix}mask"

    return filters, label, appearance.mask.shape == "circle"


def _with_shadow(
    in_label: str,
    ox: str,
    oy: str,
    shadow: ShadowSpec,
    width: int,
    height: int,
    fps: float,
    prefix: str,
    *,
    start: float,
    duration: float,
) -> tuple[list[str], str, str, str]:
    """把**已经摆好位置**的元素连同它的投影合成一张画幅大小的透明层,交回 (滤镜, 标签, "0", "0")。
    没开投影就原样交回。

    投影的偏移与模糊按**画面像素**算,不随片段的缩放、旋转变(契约 contracts/clip-shadow-cases.json)。
    预览 canvas 的 shadowOffset / shadowBlur 本来就不受变换影响;此前这里把投影画在元素自己的坐标里、再连同
    元素一起缩放旋转 —— 缩到 0.4 的画中画,成片里的投影偏移只有预览的四成,转 90° 还换了方向。所以投影从
    「元素摆好之后的样子」取:元素先叠到一张透明底板上(和底下的画面同一个坐标),拿它的 alpha 上色、模糊、
    平移,垫在元素下面。

    模糊:canvas 的 shadowBlur 是 2σ(HTML 规范,Chromium 实测一致),gblur 要的是 σ —— 取 blur / 2;此前
    直接拿 blur 当 σ,成片比预览糊一倍。gblur 默认 steps=1 是 IIR 的粗近似,实测出来的 σ 只有设定值的
    87%;steps=4 到 96%,和 canvas 的真高斯差不出来。偏移取整到像素(pad / crop 只认整数),和预览差不到一个像素。
    """
    if not shadow.enabled or shadow.opacity <= 0:
        return [], in_label, ox, oy
    red, green, blue = (int(shadow.color[index:index + 2], 16) for index in (1, 3, 5))
    dx, dy = int(round(shadow.offset_x)), int(round(shadow.offset_y))
    sigma = shadow.blur / 2
    # 底板和元素同一段时间:上层片段的元素带着时间线上的时间戳(start 起),底板也从那里开始。
    timing = f",setpts=PTS+{start:.6f}/TB" if start else ""
    blur = f",gblur=sigma={sigma:.4f}:steps=4:planes=8" if sigma > 0 else ""
    # 平移:一边垫透明边、另一边裁掉,还是画幅大小。负方向同理。
    shift = (
        f",pad={width + abs(dx)}:{height + abs(dy)}:{max(dx, 0)}:{max(dy, 0)}:color=black@0,"
        f"crop={width}:{height}:{max(-dx, 0)}:{max(-dy, 0)}"
        if dx or dy
        else ""
    )
    return [
        f"color=black@0:s={width}x{height}:r={fps}:d={duration:.6f},format=rgba{timing}[{prefix}board]",
        f"[{prefix}board][{in_label}]overlay=x='{ox}':y='{oy}':format=auto,format=rgba,split=2[{prefix}fg][{prefix}src]",
        f"[{prefix}src]lutrgb=r={red}:g={green}:b={blue}:a='val*{shadow.opacity:.4f}'{blur}{shift},format=rgba[{prefix}sh]",
        f"[{prefix}sh][{prefix}fg]overlay=0:0:format=auto,format=rgba[{prefix}layer]",
    ], f"{prefix}layer", "0", "0"


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


def _shown_during(start: float, end: float, fps: float) -> str:
    """一个叠层在时间线 [start, end) 里画 —— overlay 的 enable 表达式,**右开**。

    此前是 `between(t,start,end)`,两端都闭:相邻两段的交界帧(上一段的 end == 下一段的 start)两段都画,
    交界那一帧叠着两条字幕;上层视频那一路还带 eof_action=repeat,上一段在交界帧把自己的末帧再画一遍。
    边界往前挪半帧:帧时间是 k/fps 的浮点数,恰好落在边界上的那一帧不该因为 1e-9 的误差两边倒 ——
    挪半帧等于「离哪个边界近就归哪段」,边界在帧格上时结果和精确的 [start, end) 一样。"""
    half = 0.5 / max(fps, 1e-6)
    return f"gte(t,{start - half:.6f})*lt(t,{end - half:.6f})"


#: 总线限幅的天花板:−1 dBFS。AAC 编码会让峰值再冒一点,留 1 dB 给它。
MASTER_CEILING = 0.891
#: 响度标准化的目标(短视频平台的常见值):整体 −14 LUFS,真峰值 −1 dBTP,响度范围 11 LU(不压得太扁)。
LOUDNORM_TARGET = "I=-14:TP=-1:LRA=11"


def _master_bus(loudnorm: bool) -> str:
    """混音之后、编码之前的总线(不带输入输出标签)。

    **限幅总是有。** amix 是 normalize=0 的直接相加,增益关键帧又能拉到 4 倍:人声 + 音乐 + 原声叠在一起,
    采样轻易超过 ±1,编码时被硬削成方波(审查实测一段三轨叠加 9% 的采样在 0 dBFS 上)。alimiter 在
    −1 dBFS 处软压:level=0 不做自动增益(不改没超的部分),latency=1 补偿它的前视延迟(不然整条声音晚 5 ms)。

    **响度标准化可选,默认关**:单遍的 loudnorm 是动态模式,会改动混音的起伏;预览(浏览器里直接放)也
    听不到它,导出和预览就不一样了;何况主流平台播放时自己会做响度归一。要发到不做归一的地方、或者
    几段素材音量差得多时,导出框里打开。它会把采样率升到 192 kHz,后面接一个 aresample 拉回来。"""
    chain = ""
    if loudnorm:
        chain += f"loudnorm={LOUDNORM_TARGET},aresample={AUDIO_RATE},"
    return chain + f"alimiter=limit={MASTER_CEILING}:level=0:latency=1"


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


def _ass_bord(st, scale: float) -> str:
    """描边外圈在缩放 `scale` 下的 \\bord 值。

    libass 的 \\bord 本来就是纯外描边,直接写外圈宽度;ScaledBorderAndShadow 开着、PlayRes 等于
    输出画幅,脚本像素即画面像素(契约 contracts/text-stroke-cases.json)。但它**不跟 \\fscx 走**:
    预览和 PNG 路径是整块放大,描边一起变粗,这里得自己乘上花字的缩放。"""
    return f"\\bord{st.outer_stroke_px * scale:g}"


def _text_style_tags(st, scale: float = 1.0) -> list[str]:
    """花字外观标签(字号/颜色/描边/阴影/粗斜/字体),不含位置/缩放/旋转/透明度。
    scale 只用来换算描边(见 _ass_bord),缩放本身由调用方的 \\fscx 给。"""
    tags = [f"\\fs{st.font_size * _ASS_FONTSIZE_SCALE:g}", f"\\1c{_ass_bgr(st.color)}"]
    if st.outer_stroke_px > 0:
        tags.append(f"{_ass_bord(st, scale)}\\3c{_ass_bgr(st.stroke_color)}")
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
        override = "{" + "".join(tags + _text_style_tags(st, scale=tf.scale)) + "}"
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
            if st.outer_stroke_px > 0:
                parts.append(_ass_bord(st, sb))  # 描边跟着缩放一起渐变(见 _ass_bord)
        if abs(rb - ra) > 1e-4:
            parts.append(f"\\frz{-rb:.2f}")
        if abs(ob - oa) > 1e-4:
            parts.append(f"\\alpha&H{round((1.0 - ob) * 255):02X}&")
        anim = f"\\t(0,{seg_ms},{''.join(parts)})" if parts else ""
        override = "{" + "".join(tags + _text_style_tags(st, scale=sa)) + anim + "}"
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
        "100,100,0,0,1,0,0,5,0,0,0,1\n"
        # 「AI 生成」标识:BorderStyle=3 的半透明深色底框 + 白字(和浏览器那条路的 _label_css 同一个样子)。
        # 底框色在 OutlineColour 和 BackColour 都给(libass 画框用前者、投影用后者)。拉丁字母和汉字落在
        # 两个字体里时 libass 一段一个框,接缝处略深 —— 不用 BorderStyle=4(整条一个框):libass 0.17 之前
        # 不认它,会退成没有框的白字,压在白底上就看不见了。
        f"Style: Label,Sans,48,&H00FFFFFF,&H000000FF,{_LABEL_BOX},{_LABEL_BOX},-1,0,0,0,"
        "100,100,0,0,3,0,0,5,0,0,0,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = [
        f"Dialogue: 0,{_ass_timestamp(item.start)},{_ass_timestamp(item.start + item.duration)},"
        f"Default,,0,0,0,,{_ass_text(item.text)}"
        for item in plan.subtitles
    ]
    lines += [line for item in plan.text_overlays for line in _text_overlay_dialogues(item, w, h)]
    lines += [_ai_label_dialogue(item, w, h) for item in plan.ai_labels]
    return header + "\n".join(lines) + "\n"


#: 标识底框:黑,不透明度 0.55(ASS 的 alpha 是透明度,0x73 ≈ 0.45 透明)。
_LABEL_BOX = "&H73000000"
#: 底框比字多出来的边(相对字号),两条路一样。
_LABEL_PAD = 0.25


def _ai_label_dialogue(item: AiLabelItem, w: int, h: int) -> str:
    """一块标识 → 一条 ASS Dialogue(Layer 1,压在字幕和花字上面)。

    角标用 \\an9(右上角为锚点)贴在离右边、上边各 margin 的地方:锚的是**字**,底框还要往外多出
    一圈 pad,所以锚点再往里收 pad —— 框的外沿正好落在 margin 上。"""
    size = item.font_size * _ASS_FONTSIZE_SCALE
    pad = round(item.font_size * _LABEL_PAD)
    if item.placement == "top_right":
        anchor = f"\\an9\\pos({w - item.margin - pad:.1f},{item.margin + pad:.1f})"
    else:
        anchor = f"\\an5\\pos({w / 2:.1f},{h / 2:.1f})"
    override = "{" + anchor + f"\\fs{size:g}\\bord{pad}\\shad0" + "}"
    return (f"Dialogue: 1,{_ass_timestamp(item.start)},{_ass_timestamp(item.start + item.duration)},"
            f"Label,,0,0,0,,{override}{_ass_text(item.text)}")


def _escape_filter_path(path: Path) -> str:
    # Inside filter_complex, colons separate options and backslashes escape.
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _ai_label_position(label: AiLabelItem, pw: int, ph: int, w: int, h: int) -> tuple[int, int]:
    """标识 PNG(已带底框)左上角坐标:片头那块居中;角标的右边、上边各离画面边缘 margin。"""
    if label.placement == "top_right":
        return int(round(w - label.margin - pw)), int(round(label.margin))
    return (w - pw) // 2, (h - ph) // 2


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


class TextTrack(NamedTuple):
    """字幕(和能并进来的静止花字)合成的**一路**透明画面:一份 ffconcat,每一段是一张画布大小的 PNG +
    它在画面上停多久。画布只有所有字的外接框那么大,叠在 (x, y)。"""

    script: Path
    x: int
    y: int


class BurnedText(NamedTuple):
    """浏览器那条路渲好的文字,按叠的次序分好层:最下面一路字幕轨(TextTrack),再往上是没并进轨的花字
    (plan.text_overlays 里的下标 + PNG,一条一路,带动画的都在这里),最上面是 AI 标识(PNG)。"""

    track: TextTrack | None
    text_overlays: tuple[tuple[int, Path, int, int], ...]
    ai_labels: tuple[tuple[Path, int, int], ...]


class _TrackLayer(NamedTuple):
    """并进字幕轨的一块字:画在 [on, off) 毫秒(切换点落在两帧正中,见 compose_text_layers),左上角 (x, y)。"""

    on: int
    off: int
    png: Path
    x: int
    y: int
    w: int
    h: int


def _overlay_xy(value: float) -> int:
    """overlay 滤镜落位置的取法:截断成整数,再按 4:2:0 的色度对齐往下取偶数(vf_overlay 的
    normalize_xy)。并进轨的字要落在和单独叠时**同一个**像素上。"""
    return int(value) & ~1


def _still_text_xy(item: TextOverlayItem, pw: int, ph: int, width: int, height: int) -> tuple[int, int] | None:
    """一条花字能不能并进字幕轨:不动(没有关键帧)、不缩放不旋转、不透明 —— 这样它就是一张原样贴上去的
    PNG,贴在哪和单独叠时(_element_transform 的元素尺寸那条路)算得一模一样。能就返回左上角。"""
    tf = item.transform
    if tf.keyframes or tf.scale != 1.0 or tf.rotation != 0 or tf.opacity < 1.0:
        return None
    x, y = float(f"{tf.x:.5f}"), float(f"{tf.y:.5f}")
    return _overlay_xy((0.5 + x * 0.5) * width - pw / 2), _overlay_xy((0.5 + y * 0.5) * height - ph / 2)


def compose_text_layers(plan: RenderPlan, pngs: dict, workdir: Path) -> BurnedText:
    """把逐条渲好的文字 PNG(_rasterize_text 的那张表)分层:字幕和能并的花字合成一条轨,其余照旧一条一路。

    **为什么要合成一条轨**:此前每条字幕是一路 `-loop` 的 PNG 输入加一个整幅 overlay,而 overlay 不在
    窗口里也要逐帧走一遍 —— 字幕越多,每一帧付的钱越多(1 小时 1000 条字幕的片子多花约 50 分钟),
    命令行和输入数也跟着涨。一条轨就只有一路输入、一个 overlay。

    **叠的次序不变**:字幕在所有花字下面;一条花字只有在它之前、和它时间上重叠的花字都也并得进来时
    才并 —— 否则它会被压到本该在它下面的那条带动画的花字底下。"""
    width, height, fps = plan.output.width, plan.output.height, plan.output.fps

    def switch_ms(at: float) -> int:
        # _shown_during 的式子 gte(t, at − 半帧) 按**精确**算术求:先算出第一个到了的帧(k/fps ≥ at − 半帧),
        # 再把切换点放在它和前一帧**正中间**(毫秒,ffconcat 的精度),离两边的帧都有半帧远,不会被时间戳的取整
        # 带偏。边界恰好压在某一帧上时(片段起止不在帧格上,挪半帧正好挪到帧上),那一帧归后一段 —— 逐条 enable
        # 时这一帧归哪边取决于浮点误差(同一条时间线里实测两边都有),这里定下来。
        first = math.ceil(at * fps - 0.5 - 1e-6)
        return max(0, round((first - 0.5) / fps * 1000))

    def window(start: float, duration: float) -> tuple[int, int]:
        return switch_ms(start), switch_ms(start + duration)

    layers: list[_TrackLayer] = []
    for item, (png, pw, ph) in zip(plan.subtitles, pngs.get("subtitles", [])):
        sx, sy = _subtitle_overlay_pos(plan.subtitle_style, pw, ph, width, height)
        layers.append(_TrackLayer(*window(item.start, item.duration), png, _overlay_xy(sx), _overlay_xy(sy), pw, ph))
    loose: list[tuple[int, Path, int, int]] = []
    for k, (item, (png, pw, ph)) in enumerate(zip(plan.text_overlays, pngs.get("text_overlays", []))):
        xy = _still_text_xy(item, pw, ph, width, height)
        on, off = window(item.start, item.duration)
        below_loose = any(
            on < window(plan.text_overlays[j].start, plan.text_overlays[j].duration)[1]
            and window(plan.text_overlays[j].start, plan.text_overlays[j].duration)[0] < off
            for j, *_ in loose
        )
        if xy is None or below_loose:
            loose.append((k, png, pw, ph))
        else:
            layers.append(_TrackLayer(on, off, png, *xy, pw, ph))
    track = _write_text_track(layers, workdir, width, height) if layers else None
    return BurnedText(track, tuple(loose), tuple(pngs.get("ai_labels", [])))


def _write_text_track(layers: list[_TrackLayer], workdir: Path, width: int, height: int) -> TextTrack | None:
    """按「这一段里哪几块字在场」切段,每种组合画一张画布 PNG(同一组合只画一次),写成 ffconcat。

    画布是所有字的外接框(夹在画幅里、左上角取偶数),每张都一样大 —— 一路视频中途换尺寸,ffmpeg 会把
    整张滤镜图重建。时间用每个文件的 `option framerate 1000` 定到毫秒(不给的话 image2 按 25fps 取整,
    边界会差出 40 毫秒);各段时长是相邻边界之差,不会越拼越漂。"""
    from PIL import Image

    left = max(0, min(layer.x for layer in layers)) & ~1
    top = max(0, min(layer.y for layer in layers)) & ~1
    right = min(width, max(layer.x + layer.w for layer in layers))
    bottom = min(height, max(layer.y + layer.h for layer in layers))
    if right <= left or bottom <= top:
        return None  # 字全在画外
    canvas_w, canvas_h = right - left + (right - left) % 2, bottom - top + (bottom - top) % 2

    folder = workdir / "text_track"
    folder.mkdir(parents=True, exist_ok=True)
    images: dict[Path, Image.Image] = {}
    states: dict[tuple[int, ...], str] = {}

    def state(visible: tuple[int, ...]) -> str:
        if visible not in states:
            canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            for index in visible:
                layer = layers[index]
                if layer.png not in images:
                    images[layer.png] = Image.open(layer.png).convert("RGBA")
                _paste(canvas, images[layer.png], layer.x - left, layer.y - top)
            name = f"state{len(states)}.png"
            canvas.save(folder / name, compress_level=1)
            states[visible] = name
        return states[visible]

    edges = sorted({0, *(layer.on for layer in layers), *(layer.off for layer in layers)})
    entries: list[tuple[str, int]] = []
    for at, until in zip(edges, edges[1:]):
        visible = tuple(i for i, layer in enumerate(layers) if layer.on <= at < layer.off)
        name = state(visible)
        if entries and entries[-1][0] == name:
            entries[-1] = (name, entries[-1][1] + until - at)
        else:
            entries.append((name, until - at))
    #: 最后一段:全透明,没有时长 —— 它是这一路的最后一帧,overlay 一直拿它垫到片尾。
    entries.append((state(()), 0))
    lines = ["ffconcat version 1.0"]
    for name, ms in entries:
        lines += [f"file '{name}'", "option framerate 1000"]
        if ms:
            lines.append(f"duration {ms / 1000:.3f}")
    script = folder / "track.ffconcat"
    script.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return TextTrack(script, left, top)


def _paste(canvas, image, x: int, y: int) -> None:
    """把 image 按 straight alpha 叠到 canvas 的 (x, y);伸出画布的部分裁掉(alpha_composite 不认负坐标)。"""
    sx, sy = max(0, -x), max(0, -y)
    w = min(image.width - sx, canvas.width - max(x, 0))
    h = min(image.height - sy, canvas.height - max(y, 0))
    if w > 0 and h > 0:
        canvas.alpha_composite(image, dest=(max(x, 0), max(y, 0)), source=(sx, sy, sx + w, sy + h))


# 从深处剪一小段时,靠 trim 滤镜切会逼 ffmpeg 从第 0 帧一路解码到 src_in——长素材里这一步
# 能占掉绝大多数导出时间(表现为进度长时间卡在个位数、speed≈0.0x)。改用输入级 -ss 快进:
# ffmpeg 先跳到 src_in 之前最近的关键帧,默认 accurate_seek 会精确解码并丢弃到 src_in、并把
# 该点重置为时间 0,所以 trim 改成从 0 起算、长度不变,帧仍然精确。src_in≈0(图片、从头的
# 片段)不加 -ss,行为与之前完全一致。
_INPUT_SEEK_THRESHOLD = 0.05
#: 快进点比入点再往前留这么多秒,trim 从这里切到入点。**快进点正好落在关键帧上时**(相机、录屏素材的剪辑点
#: 很常见),各路从快进点起解:声音解码器的头一帧没有前一帧可以叠(AAC 的 MDCT 重叠、MP3 的比特池、Opus 的
#: 预滚都要前一帧),入点开头几十毫秒的声音和源对不上,听起来是一声「咔」。落在关键帧之间时 ffmpeg 会退到
#: 前一个关键帧起解,正好躲过 —— 所以只坏在关键帧上。半秒够任何一种编码收敛;画面多解的那一点(最多一个 GOP)
#: 被 trim 丢掉,帧仍然精确。
_SEEK_PREROLL = 0.5


def _seek_and_trim(src_in: float, src_out: float) -> tuple[list[str], float, float]:
    """返回 (输入前置的 -ss 参数, trim 起点, trim 终点)。入点够深才快进(快进到入点前 _SEEK_PREROLL),否则从头解。"""
    seek = src_in - _SEEK_PREROLL
    if seek > _INPUT_SEEK_THRESHOLD:
        return ["-ss", f"{seek:.6f}"], round(src_in - seek, 6), round(src_out - seek, 6)
    return [], src_in, src_out


def _video_from(tin: float, speed: float) -> str:
    """把一段素材的画面放到「从 trim 起点算的 0」上(setpts 表达式)。

    减的是 **trim 起点**,不是 STARTPTS(trim 之后第一帧自己的时间戳)—— 声音那边同理,见 _audio_from。
    两路都以同一个点为 0,画面和声音在素材里差多少,成片里就差多少。"""
    base = f"PTS{_minus(tin)}/TB"
    return base if speed == 1.0 else f"({base})/{speed}"


def _minus(value: float) -> str:
    """「减去 value」的写法。value 可以是负的(只渲一截时,素材的 0 点在这一路输入的快进点之前,见
    _Window):写成 `-0.5`,不写 `--0.5`。"""
    return f"-{value}" if value >= 0 else f"+{-value}"


def _audio_from(tin: float) -> str:
    """声音那一路的「从 trim 起点算的 0」,外加把开头缺的那段补成静音(带尾逗号)。

    **素材里的音轨常常比画面晚开始**(AAC 的起始延迟、录屏、-itsoffset 过的文件:音轨 start_time 0.2~0.5 秒)。
    此前两路各自 `PTS-STARTPTS`:画面的第一帧归 0,声音的第一个采样**也**归 0 —— 声音整段提前了它晚开始的
    那么多,口型对不上,而素材自己放是对的。走 -ss 快进的片段一样:快进点之后音轨的第一个采样也被拽到 0。
    现在两路都减 trim 起点;声音开头空着的那段由 aresample 的 first_pts=0 补静音(min_comp 打开补偿,
    中间的断档同样补上),后面 atempo 变速时这段静音跟着一起变。"""
    return f"asetpts=PTS{_minus(tin)}/TB,aresample={AUDIO_RATE}:min_comp=0.001:min_hard_comp=0.01:first_pts=0,"


_IMAGE_LOOP_PAD = 0.2  # -t 相对 trim 末尾留的小余量,保证末帧不缺
#: ffmpeg 用 image2 解复用器打开的静态图后缀 —— 只有它们认 `-loop`(见 _image_loop_args)。
_IMAGE2_STILL_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".jfif", ".bmp", ".tif", ".tiff", ".webp"})


def _image_loop_args(path: Path, trim_end: float) -> list[str]:
    """静态图片一律 -loop 成真正逐帧推进的视频流。

    图片默认进 ffmpeg 只有**一帧**,时间戳不推进,于是任何按时间求值的东西都停在 t=0:
      · 自身的 transform 关键帧动画 / 淡入淡出 → 恒取首值(表现为动画失效、透明度卡 0 全黑);
      · 叠在它上面的 overlay 的 enable='between(t,…)' → 窗口永不命中(图片作底轨时上层画中画整段消失);
      · 图片自己作 overlay 时同理 → 该叠层根本不出现。
    这三类都真实发生过。曾经用一个 needs_time 开关只在"看起来需要时间轴"时才 loop,但需求方
    (自身动画 / 上层 / 下层)分散在各处,每个调用点都得记得算对——两处算漏就是两个 bug。
    索性去掉开关:图片一律逐帧,正确性由构造保证,代价只是极小的解码开销。
    -t 必须给(无限流会让 concat 永远卡在这一段),取 trim 末尾加点余量保住末帧。

    **`-loop` 不是 ffmpeg 的通用选项,是 image2 解复用器私有的。** GIF 走 gif 解复用器、
    AVIF/HEIC 走 mov 解复用器,它们都不认 `-loop`,ffmpeg 连输入都打不开
    (「Option loop not found」)—— 时间线上只要有一段 GIF,取帧和导出就**整条**失败。
    所以只有 image2 认的那几种静态图用 `-loop 1`;其余图片用通用的 `-stream_loop -1`
    (任何解复用器都认,GIF 也因此按预览里 <img> 那样循环播放,而不是播一遍就断流)。
    不全用 `-stream_loop`:它对 image2 每一轮都要重新 seek 打开文件,大图上慢一个数量级。"""
    if guess_kind(path) != "image":
        return []
    duration = ["-t", f"{max(trim_end, 0.04) + _IMAGE_LOOP_PAD:.6f}"]
    if path.suffix.lower() in _IMAGE2_STILL_SUFFIXES:
        return ["-loop", "1", *duration]
    return ["-stream_loop", "-1", *duration]


def _onto_frame_grid(fps: float, start_time: float) -> str:
    """把一路素材画面落到输出的帧格上(带前导逗号):每个输出时刻挑一帧,从段内第 start_time 秒开始。

    **紧跟在 trim / setpts 后面,不放在 scale / overlay 后面。** fps 按上游报的结束时刻决定最后一帧要不要:
    结束时刻等于最后一帧自己的时刻,那一帧就算「零时长」被丢掉。旧版 ffmpeg 的 framesync 结束时不带时刻,下游
    看到的就是最后一帧自己的时刻 —— 上游提交 de976eaf30「avfilter/framesync: fix forward EOF pts」才补上(8.0 起,
    7.1 系列 7.1.1 起;它的说明里写的就是 fps 丢最后一帧)。overlay 一直走 framesync,scale 从 7.1 起也走。
    此前 fps 在 scale 后面、模糊背景时还在 overlay 后面:Ubuntu 24.04 的 ffmpeg 6.1 上,模糊背景的段在素材正好
    够帧数时末一帧被丢掉,由后面补齐整帧的那一步拿倒数第二帧顶上。挑帧只看时间戳,挪到前面挑出来的是同一帧。"""
    return f",fps={fps}:start_time={start_time:g}"


def _base_video_chain(source: str, i: int, src_in: float, src_out: float, setpts: str, width: int, height: int, fps: float, tail: str, fill_mode: str, *, start_time: float = 0.0) -> str:
    """source(如 [3:v],或共用输入分出来的一支,见 _base_sources)→ [vi] 的完整视频链;按画幅填充模式
    选择裁剪/留黑边/模糊背景。start_time 是这一路画面从段内第几秒开始(只有只渲一截时不是 0,见 _Window)。"""
    head = f"{source}trim=start={src_in}:end={src_out},setpts={setpts}{_onto_frame_grid(fps, start_time)}"
    end = f",format=yuv420p,setsar=1{tail}[v{i}]"
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


@functools.lru_cache(maxsize=4)
def ffmpeg_has_libass(ffmpeg: str) -> bool:
    """这个 ffmpeg 有没有 `subtitles` 滤镜(libass)。按二进制路径缓存:路径换了(设置里改了)要重探。

    Homebrew 的 core `ffmpeg` 是精简版,没有 libass —— 文字一旦落到 ASS 那条路,ffmpeg 只会说一句
    「No such filter: 'subtitles'」,导出失败的原因用户看不懂。探不出来(ffmpeg 不在)按「没有」算。"""
    try:
        proc = run_logged([ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True,
                          timeout=20, what="libass 探测", level=logging.DEBUG)
    except Exception:
        return False
    return any(line.split()[1:2] == ["subtitles"] for line in (proc.stdout or "").splitlines())


def _text_rasterizer_available() -> bool:
    """文字能不能走「浏览器按预览 CSS 渲成 PNG」那条路(不需要 libass)。Chromium 起不起得来要到用时才知道。"""
    if not settings.text_rasterize:
        return False
    from app.media.text_render import find_frontend_dist

    return find_frontend_dist() is not None


def _has_text(plan: RenderPlan) -> bool:
    return bool(plan.subtitles or plan.text_overlays or plan.ai_labels)


def ensure_text_can_burn(plan: RenderPlan) -> None:
    """有字要烧,而两条路(浏览器渲 PNG、libass 烧 ASS)都走不通时,**在建任务之前**就说清楚。

    此前要等任务跑起来、ffmpeg 报「No such filter」才失败,失败原因是一串滤镜图。"""
    if _has_text(plan) and not _text_rasterizer_available() and not ffmpeg_has_libass(settings.ffmpeg):
        raise RenderExecutionError("renderErr_noLibass", ffmpeg=settings.ffmpeg)


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


def _videotoolbox_quality(crf: int) -> int:
    """x264 的 CRF → VideoToolbox 恒定质量 `-q:v`(1–100,越大越好)。

    两个标定点是真 ffmpeg 对着 x264 veryfast 同档量 SSIM 定的:标准档 CRF 20 ↔ q 66、体积小档
    CRF 26 ↔ q 50。在 360p/720p/1080p 的分形、测试图、渐变颗粒、满屏噪声上(30fps)都不低于
    x264 同档 —— 最难的满屏噪声上 q 63 还差 0.03,所以取 66;代价是文件大三到五成。之间线性
    插值。q 和 CRF 不一样,不随帧率给码:10fps 的噪声片 x264 每帧给的码多出一倍多,硬件追不上,
    好在导出是序列帧率(24–60)。此前给的是按分辨率×帧率推出来的固定码率,硬件「高画质」只有
    0.978,比软件「体积小」的 0.981 还低,档位名不副实。"""
    return int(round(max(1.0, min(100.0, 66 - (crf - 20) * 8 / 3))))


def _hw_encode_args(encoder: str, output) -> list[str]:
    """给定硬件编码器的完整 -c:v 参数(yuv420p,保证各家播放器都能放)。

    VideoToolbox 用恒定质量(见 _videotoolbox_quality);其余几家在本机量不到,仍是码率模式。"""
    if encoder == "h264_videotoolbox":
        # 非实时(-realtime 0)换更好画质;-allow_sw 1 在个别机器无硬件编码单元时回落苹果的
        # 软件实现而不是直接报错。-q:v 只有 Apple Silicon 认 —— Intel Mac 上起不来,由
        # _hw_encoder_works 的小样自检挡在开跑之前。
        return [
            "-c:v", encoder, "-q:v", str(_videotoolbox_quality(int(output.crf))),
            "-pix_fmt", "yuv420p", "-realtime", "0", "-allow_sw", "1",
        ]
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
    if encoder == "h264_nvenc":
        # p5 是质量/速度的平衡档,vbr 走上面的 b:v/maxrate,spatial_aq 改善平坦区域观感。
        return common + ["-preset", "p5", "-rc", "vbr", "-spatial-aq", "1"]
    if encoder == "h264_qsv":
        return common + ["-preset", "medium"]
    if encoder == "h264_amf":
        return common + ["-quality", "balanced", "-rc", "vbr_peak"]
    return common


#: CRF 低于这个(「高画质」档是 18)直接软件编码。硬件恒定质量追到 x264 medium CRF 18 的画质,
#: 实测 q 71 仍略低(复杂画面 SSIM 0.9936 对 0.9940)而文件还大三成;选了「高画质」的人要的
#: 是画质,不是快那一两倍。其余几家硬件编码器在本机量不到,同样不让它们接这一档。
_HW_MIN_CRF = 20
#: 比这短的片子直接软件编码:硬件编码器开一次会话的固定开销抵掉了它的速度,实测 10 秒
#: 1080p 的简单画面软件 0.8 秒、硬件 2.3 秒;复杂画面到 60 秒以上硬件才快出一倍。
_HW_MIN_DURATION = 30.0
#: 小样自检通过过的 (ffmpeg, 宽, 高, 编码参数)。只记成功:一次失败可能只是当时 GPU 忙。
_HW_SELF_TESTED: set[tuple] = set()


def _hw_encoder_works(encoder: str, output) -> bool:
    """用这次导出的分辨率、帧率和编码参数先编 0.2 秒黑场,看硬件编码器到底起不起得来。

    `-encoders` 里列着不等于能用:没有显卡、驱动或权限不对、分辨率超出硬件上限、Intel Mac 不认
    VideoToolbox 的 -q:v,都要到开编那一刻才报错。此前的办法是整条硬件跑挂了再用软件**从 0
    重来**,而那之前读素材、建滤镜图、渲字幕的时间全白花了;先编一小段,挂了就一开始走软件。"""
    args = _hw_encode_args(encoder, output)
    key = (settings.ffmpeg, output.width, output.height, tuple(args))
    if key in _HW_SELF_TESTED:
        return True
    fps = output.fps if output.fps and output.fps > 0 else 30
    try:
        probe = run_logged(
            [settings.ffmpeg, "-v", "error", "-f", "lavfi",
             "-i", f"color=black:s={output.width}x{output.height}:r={fps:g}:d=0.2",
             *args, "-f", "null", "-"],
            capture_output=True, text=True, timeout=30, what="硬件编码小样自检", level=logging.DEBUG,
        )
    except Exception:
        logger.warning("render: hardware encoder %s self-test could not run", encoder, exc_info=True)
        return False
    if probe.returncode != 0:
        logger.warning("render: hardware encoder %s failed its self-test: %s", encoder, blame_line(probe.stderr))
        return False
    _HW_SELF_TESTED.add(key)
    return True


def _choose_hw_encoder(plan: RenderPlan) -> str | None:
    """这次导出用哪个硬件编码器;None = 软件 libx264。

    开关关着、没有硬件编码器、「高画质」档(_HW_MIN_CRF)、片子太短(_HW_MIN_DURATION)、
    小样自检没过,都走软件。"""
    if not settings.hw_encode:
        return None
    encoder = _available_hw_encoder()
    if encoder is None or plan.output.crf < _HW_MIN_CRF or plan.timeline_duration < _HW_MIN_DURATION:
        return None
    return encoder if _hw_encoder_works(encoder, plan.output) else None


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


#: 只渲一截(取一帧、分块)时,跨进这一截的片段从这一截之前多少秒开始解码。不卡在正好那一刻:fps 滤镜按
#: 输入时间戳给每个输出时刻挑帧,前面留一小段余量,挑出来的才稳稳是整条渲时同一时刻的那一帧。
_WINDOW_PREROLL = 1.0


class _Window(NamedTuple):
    """只渲时间线上 [start, end) 这一截(取一帧时 start == end,就是那一刻)。

    基底轨上画面落在这一截里的是第 first..last 段;first 在时间线上从 base 开始,从段内第 skip 秒开始解
    (前面的用不上)。别的层按各自的时间窗筛、跨进来的同样从这一截前一点开始解(见 _layer_skip)。"""

    start: float
    end: float
    first: int
    last: int
    base: float
    skip: float

    def covers(self, item_start: float, duration: float) -> bool:
        """这一层和这一截有没有交集(闭区间,宁多勿少 —— 真正显不显示仍由各自的 enable 决定)。"""
        return item_start <= self.end and item_start + duration >= self.start


def _segment_frames(plan: RenderPlan) -> list[tuple[int, int]]:
    """基底轨每一段落在哪几帧上:(第一帧的帧号, 帧数)。段的起止按时间线时间取到最近的帧格。

    **基底轨按整帧接**:每段的画面补齐 / 截到正好这么多帧、声音补齐 / 截到正好这么长(见 _exact_span),
    concat 接出来的第 k 帧就是时间线上的第 k 帧。此前每段的长短由 concat 自己估 —— 画面按「最后一帧的时刻
    × 帧数 /(帧数 − 1)」算、声音按采样算,取两者长的那个:起止不在帧格上的段,每段多出零点几帧,越往后
    底轨越晚于上层、字幕和音频轨;而且估出来的长短取决于这一段从哪一帧开始,只渲一截(分块、取帧)时
    接出来的位置和整条渲时就对不上。整帧接,位置只看帧号。"""
    fps = plan.output.fps
    frames: list[tuple[int, int]] = []
    at = 0.0
    count = len(plan.video_segments)
    for index, segment in enumerate(plan.video_segments):
        begin = _nearest_frame(at, fps)
        at = round(at + segment.duration, 9)
        #: 最后一段收在「片长之前的最后一整帧」之后 —— 和成片的 -t 片长一样:k/fps < 片长的帧都在。
        end = math.ceil(at * fps - 1e-6) if index == count - 1 else _nearest_frame(at, fps)
        frames.append((begin, end - begin))
    return frames


def _nearest_frame(at: float, fps: float) -> int:
    """时间线上的一刻落在第几帧:四舍五入,正好半帧时往后(浮点误差不让它两边倒)。"""
    return math.floor(at * fps + 0.5 + 1e-6)


def _exact_span(frames: int, fps: float, *, audio: bool) -> str:
    """一段补齐 / 截到正好 frames 帧那么长(带前导逗号;本段自己的时间,从 0 起)。画面不够就重复最后一帧
    (素材比片段短时,此前那里是一段空档,成片按恒定帧率补的也是最后一帧),声音不够就补静音。

    画面这边 tpad 之后、trim 之前再过一道 fps:tpad 补的第一帧落在上游报的**结束时刻**上,而这一段的末尾常常是
    overlay(带变换 / 投影的段、模糊背景),旧版 ffmpeg 的 overlay 报的结束时刻是最后一帧**自己的**时刻(哪些版本见
    _onto_frame_grid)—— 补出来的第一帧和最后一帧同一个时间戳,这一段就多出一帧。Ubuntu 24.04 的 ffmpeg 6.1 上
    实测:带变换的段多一帧,成片按 -r 排帧时把它往后挤,这一段之后的每一帧都晚一帧。fps 每个时刻只留一帧(同一
    时刻的两帧留后一帧,补出来的那帧和最后一帧是同一张画面);新版上没有重复的时刻,它什么都不改。"""
    span = f"{frames / fps:.6f}"
    if audio:
        return f",apad=whole_dur={span},atrim=end={span}"
    return f",tpad=stop_mode=clone:stop_duration={span},fps={fps},trim=end={span}"


def _window(plan: RenderPlan, start: float, end: float) -> _Window:
    """时间线 [start, end) 在基底轨上落在哪几段。前后的段在这一截里都不出画面,解它们纯属白干 ——
    审查实测:300 秒的时间线,取第 5 秒和第 290 秒都要 3 秒,因为每次都把整条从头解了一遍。

    段的起止按整帧算(见 _segment_frames);段内跳过的也是整帧,接起来的位置和整条渲时一帧不差。"""
    fps = plan.output.fps
    first = base = None
    last = len(plan.video_segments) - 1
    for index, (begin, count) in enumerate(_segment_frames(plan)):
        lo, hi = begin / fps, (begin + count) / fps
        if first is None and count and lo <= start < hi:
            first, base = index, begin
        if first is not None and count and lo <= max(start, end - 1e-6) < hi:
            last = index
            break
    if first is None or base is None:
        raise RenderExecutionError("stillErr_noFrame")
    skip_frames = max(0, math.floor((start - base / fps - _WINDOW_PREROLL) * fps + 1e-6))
    return _Window(start, end, first, last, base / fps, skip_frames / fps)


def _layer_skip(window: _Window | None, item_start: float, path: Path) -> float:
    """上层片段跨进这一截时,段内跳过的秒数;整条渲、图片(-loop 的流不认快进)是 0。"""
    if window is None or guess_kind(path) == "image":
        return 0.0
    return round(max(0.0, window.start - _WINDOW_PREROLL - item_start), 6)


def _frame_clock(fps: float) -> str:
    """把底轨的时间单位换成「一帧」(不带逗号)。

    concat 出来的时间单位是微秒,第 k 帧的时刻 k/fps 取整到微秒,而这个取整随这一路从哪一段开始接、前面
    估过几段长短而差一微秒:整条渲是 6.000000,只渲一截时是 5.999999。上层片段的帧正好落在同一时刻时,
    overlay 按「不晚于底下这一帧」挑帧 —— 差一微秒就挑到上一帧。换成帧,第 k 帧的时刻就是整数 k。"""
    return f"settb=1/{fps:g}"


def _shift_pts(seconds: float) -> str:
    """把一路画面的时间戳整体挪 seconds 秒(带前导逗号,负数往前挪);不挪就是空串,命令一字不变。

    挪的都是整帧(只渲一截时的段内跳过、这一截在时间线上的位置),但秒数是浮点:0.6333… 秒乘回帧数可能是
    18.9999… 也可能是 19.0000…1,而 setpts 把结果**截断**成整数 —— 差一个时间单位(帧率时基下就是一整帧),
    上层片段选帧就跟着错一帧。所以先 round。"""
    return f",setpts=round(PTS{_minus(-seconds)}/TB)" if seconds else ""


def still_plan(plan: RenderPlan, at: float) -> RenderPlan:
    """`at` 这一刻**看得见的东西**组成的计划:取一帧只渲它们。

    基底轨上 `at` 之前的段并成一段空白(只为保住那一段在时间线上的位置),之后的段扔掉;上层、
    字幕、花字、AI 标识只留时间窗盖住这一刻的(闭区间,宁多勿少 —— 真正显不显示仍由各自的
    enable 决定,见 _shown_during);声音整条不要。字幕和花字因此也只光栅化这一刻的那几条 ——
    200 条字幕的片子取一帧,此前要先起浏览器把 200 张 PNG 全画一遍,再把它们全挂进滤镜图。
    """
    segments: list[Segment] = []
    start = 0.0
    for segment in plan.video_segments:
        if start <= at < start + segment.duration:
            if start > 0:
                segments.append(Segment(kind="gap", duration=start))
            segments.append(segment)
            break
        start += segment.duration

    def covers(item_start: float, duration: float) -> bool:
        return item_start <= at <= item_start + duration

    return replace(
        plan,
        video_segments=tuple(segments),
        overlays=tuple(item for item in plan.overlays if covers(item.start, item.duration)),
        audio_overlays=(),
        subtitles=tuple(item for item in plan.subtitles if covers(item.start, item.duration)),
        text_overlays=tuple(item for item in plan.text_overlays if covers(item.start, item.duration)),
        ai_labels=tuple(item for item in plan.ai_labels if covers(item.start, item.duration)),
        base_audio_duck_windows=(),
    )


#: 同一素材在基底轨上**接着往后**用(源里的位置只往前走)、中间跳过的不超过这么多秒,就共用一路输入。
#: 跳过的那段照样要解码(解出来就丢),10 秒 1080p 的 H.264 解码是零点几秒;另开一路输入要从关键帧解起、
#: 再占一份解码器的内存(1080p 约 25 MB)。
_SHARE_MAX_GAP = 10.0


class _BaseSource(NamedTuple):
    """基底轨上一段素材的画面、声音从哪个标签取,trim 的起止相对那一路输入的 0 点;zero 是这一段自己的
    0 点在那一路输入里的位置(只渲一截、段内跳过一截时比 tin 早,可以是负的)。"""

    video: str
    audio: str | None  # 不要它的声音(没有音轨、被静音、取一帧)时是 None
    tin: float
    tout: float
    zero: float
    skip: float  # 只渲一截时段内跳过的秒数(见 _Window);整条渲恒为 0
    #: 声音那一路的 (trim 起, trim 止, 0 点)。和画面同一路输入时就是上面那三个;段内跳过了一截时声音另开
    #: 一路、从段头解(见 _base_sources),这三个按那一路算。
    sound_trim: tuple[float, float, float]


def _base_sources(
    plan: RenderPlan, resolve: Callable[[str], Path], has_audio: dict, window: _Window | None, *, sound: bool,
    frames: list[tuple[int, int]],
) -> tuple[list[str], list[str], dict[int, _BaseSource]]:
    """基底轨各段的输入:返回 (输入参数, 分支滤镜, 每段 → _BaseSource)。

    **同一素材接着往后用的几段共用一路输入**,由 split / asplit 分给各段,每段照旧自己 trim。此前一段一路
    输入:一条 1 小时的口播剪成 300 段,就是 300 个解码器(1080p 每个约 25 MB)、300 次快进、300 个 `-i`。

    只合并**源里的位置只往前走**的那几段(下一段的入点不早于上一段的出点,中间跳过的不超过 _SHARE_MAX_GAP):
    concat 是一段一段取的,解码器往前走时,还没轮到的那几支只会丢掉不归它的帧;要是后面的段倒回去用
    前面的内容,先解出来的帧就得一直攒在那一支里等 concat 轮到它 —— 那会攒下整段画面。倒回去的、
    跳得太远的、图片(-loop 出来的流),都另开一路。"""
    runs: list[dict] = []
    by_source: dict[Path, list[dict]] = {}
    separate: list[tuple[int, Path, float, float]] = []
    for i, segment in enumerate(plan.video_segments):
        if segment.kind != "clip" or segment.source is None or not frames[i][1]:
            continue  # 不到半帧长的段落不到任何一帧上
        if window is not None and not window.first <= i <= window.last:
            continue
        path = resolve(segment.source.file_key)
        image = guess_kind(path) == "image"
        # 只渲一截时,头一段从段内第 skip 秒开始解;-loop 出来的图片流不认输入侧快进,从头生成也只是几帧静图。
        skip = window.skip if window is not None and i == window.first and not image else 0.0
        src_in, src_out = segment.source.src_in + skip * segment.speed, segment.source.src_out
        audible = sound and has_audio.get(path, False) and not plan.mute_base_audio and not segment.muted
        member = (i, src_in, src_out, audible and not skip, skip, segment.source.src_in)
        if audible and skip:
            #: 声音不跟着画面跳:从段内某处快进起解的声音,aresample 的时间戳补偿会把开头那几秒拉伸一点点,
            #: 和整条渲时连续解出来的差在采样上;画面跳过省下的是解码,声音解码几乎不花钱。所以这一段的声音
            #: 另开一路、从段头解。
            separate.append((i, path, segment.source.src_in, src_out))
        #: 接得上的几路里挑跳得最少的那一路(倒回去用过一次之后,后面接着往后剪的还能回到原来那一路)。
        fits = [run for run in by_source.get(path, []) if run["end"] - 1e-6 <= src_in <= run["end"] + _SHARE_MAX_GAP]
        if fits:
            run = max(fits, key=lambda run: run["end"])
            run["members"].append(member)
            run["end"] = src_out
            continue
        run = {"path": path, "image": image, "seek": src_in, "end": src_out, "members": [member]}
        runs.append(run)
        if not image:
            by_source.setdefault(path, []).append(run)

    args: list[str] = []
    splits: list[str] = []
    sources: dict[int, _BaseSource] = {}
    for index, run in enumerate(runs):
        members = run["members"]
        seek, tin, _tout = _seek_and_trim(run["seek"], run["end"])
        base = round(run["seek"] - tin, 6)  # 这一路输入的 0 点在源里的位置(快进了就是快进点,否则是 0)
        args += _image_loop_args(run["path"], round(run["end"] - base, 6)) + seek + ["-i", str(run["path"])]
        videos = [f"[{index}:v]"] if len(members) == 1 else [f"[bv{index}_{k}]" for k in range(len(members))]
        if len(members) > 1:
            splits.append(f"[{index}:v]split={len(members)}{''.join(videos)}")
        with_sound = [member for member in members if member[3]]
        audios = [f"[{index}:a]"] if len(with_sound) == 1 else [f"[ba{index}_{k}]" for k in range(len(with_sound))]
        if len(with_sound) > 1:
            splits.append(f"[{index}:a]asplit={len(with_sound)}{''.join(audios)}")
        sounding = iter(audios)
        for video, (i, src_in, src_out, audible, skip, origin) in zip(videos, members):
            trim = (round(src_in - base, 6), round(src_out - base, 6), round(origin - base, 6))
            sources[i] = _BaseSource(video, next(sounding) if audible else None, *trim, skip, trim)
    for index, (i, path, src_in, src_out) in enumerate(separate, start=len(runs)):
        seek, tin, tout = _seek_and_trim(src_in, src_out)
        sources[i] = sources[i]._replace(audio=f"[{index}:a]", sound_trim=(tin, tout, tin))
        args += seek + ["-i", str(path)]
    return args, splits, sources


def build_ffmpeg_command(
    plan: RenderPlan,
    resolve: Callable[[str], Path],
    output_path: Path,
    *,
    force_software: bool = False,
    text_layers: BurnedText | None = None,
    still_at: float | None = None,
    chunk: tuple[float, float] | None = None,
    audio_path: Path | None = None,
    workdir: Path | None = None,
) -> list[str]:
    """…still_at 给了就**只出那一时刻的一帧**(一张图,不是一段片子)。

    workdir 是这一次渲染自己的中转目录(.ass 等写在这里),由调用方建、调用方清 —— 见
    execute_render。不给就写在成片旁边:只有直接拿命令去跑的测试走这条。

    **每一层的滤镜和成片是同一份** —— 保真度全在那里:变换、调色、花字、字幕、叠层。另写一条
    "取当前帧"的路的话,它迟早和成片长得不一样,而这种不一样是最难发现的:画面看着对,只是
    少了一层字。取一帧只在两处不同:基底轨只渲那一刻所在的一段(从那一刻前一点开始解,时间戳
    挪回时间线位置),声音不建。各层要不要先按 still_plan 筛,是调用方的事(render_still 筛)。

    chunk=(start, end) 给了就只渲时间线上这一截(分块渲染,见 _chunk_windows):画面写进 output_path(只有
    画面,end 之前的整帧),混音前的声音写进 audio_path(无损 PCM,按采样数切),和取一帧同一套「只渲一截」。
    """
    width, height, fps = plan.output.width, plan.output.height, plan.output.fps
    still = still_at is not None
    window = (
        _window(plan, max(still_at, 0.0), max(still_at, 0.0)) if still_at is not None
        else _window(plan, *chunk) if chunk is not None else None
    )
    # Probe every source we will ask about up front, concurrently, instead of once per clip as
    # the command is assembled — the probes are independent and each one is just waiting on an
    # ffprobe child. Repeated sources collapse to one probe. 取一帧不要声音,也就不用问。
    has_audio = {} if still else probe_has_audio_many(
        [resolve(segment.source.file_key) for segment in plan.video_segments
         if segment.kind == "clip" and segment.source is not None]
        + [resolve(item.source.file_key) for item in plan.audio_overlays if item.optional]
    )
    args: list[str] = [settings.ffmpeg, "-y", "-v", "error", "-progress", "pipe:1", "-nostats"]
    frames = _segment_frames(plan)
    base_args, filters, sources = _base_sources(plan, resolve, has_audio, window, sound=not still, frames=frames)
    args += base_args
    video_labels: list[str] = []
    audio_labels: list[str] = []
    if window is not None and not still and window.base > 0:
        #: 这一截之前的那些段,声音并成一段静音:混音按时间线时间对齐,前面得垫上(静音几乎不花钱)。
        filters.append(f"anullsrc=r={AUDIO_RATE}:cl=stereo,atrim=0:{window.base}[abefore]")
        audio_labels.append("[abefore]")
    input_index = args.count("-i")

    for i, segment in enumerate(plan.video_segments):
        if window is not None and not window.first <= i <= window.last:
            continue  # 只渲一截:基底轨只渲画面落在这一截里的那几段
        if not frames[i][1]:
            continue  # 不到半帧长的段落不到任何一帧上
        #: 只渲一截时头一段从段内第 skip 秒(整帧)开始解码(见 _Window);整条渲恒为 0。
        skip = window.skip if window is not None and i == window.first else 0.0
        span = frames[i][1] / fps
        #: 画面补齐 / 截到整帧;从段内第 skip 秒开始的那段再挪回 0 起 —— concat 按「这段从 0 开始」估长短。
        exact = _exact_span(frames[i][1], fps, audio=False) + _shift_pts(-skip)
        if segment.kind == "clip" and segment.source is not None:
            source = sources[i]
            tin, tout, skip = source.tin, source.tout, source.skip
            setpts = _video_from(source.zero, segment.speed)
            # Picture fade (画面淡变, fade to/from black) is independent of the audio fade below.
            video_fades = _fade_filters(segment.video_fade_in, segment.video_fade_out, segment.duration, audio=False)
            preset = f",{FILTER_PRESETS[segment.filter]}" if segment.filter else ""
            lut_path = _escape_filter_path(resolve(segment.lut)) if segment.lut else ""
            preset += _grade_filter(dict(segment.grade), segment.curves, lut_path)
            free = _is_free_element(segment.appearance)
            if segment.transform.is_identity and not free:
                filters.append(
                    _base_video_chain(
                        source.video, i, tin, tout, setpts, width, height, fps,
                        f"{preset}{video_fades}{exact}", plan.output.fill_mode, start_time=skip,
                    )
                )
            else:
                # 带变换(或蒙版 / 投影)的底轨片段:先成一个元素,再按变换叠到背景上。**没有蒙版 / 投影时它仍跟着
                # 画幅的填充模式** —— contain / blur 下元素是「装进画幅」的大小,blur 的背景是同一段素材铺满再模糊;
                # 和预览 scenePaint 的 followsBaseFill 同一条。此前这里一律铺满再裁到画幅:contain / blur 的片子一打
                # 关键帧,画面就从留边跳成裁满。
                head = f"{source.video}trim=start={tin}:end={tout},setpts={setpts}{_onto_frame_grid(fps, skip)}"
                tail = f"{preset}{video_fades},setsar=1"
                if not free and plan.output.fill_mode == "blur":
                    filters.append(f"{head},split=2[eltsrc{i}][bgsrc{i}]")
                    filters.append(
                        f"[bgsrc{i}]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
                        f"gblur=sigma=20{tail},format=yuv420p[bg{i}]"
                    )
                    head = f"[eltsrc{i}]"
                else:
                    filters.append(
                        # 背景必须给时长:无 :d 的 color 是无限流,concat 会永远停在这一段推不动,
                        # 整条 filtergraph 疯狂缓冲——带动画的图片幻灯片导出因此慢到 0.0x(见回归测试)。
                        f"color=black:s={width}x{height}:r={fps}:d={round(span - skip, 6)}"
                        f"{_shift_pts(skip)}[bg{i}]"
                    )
                    head += ","
                fit = "increase" if free or plan.output.fill_mode == "cover" else "decrease"
                filters.append(f"{head}{_element_fit(segment.appearance, fit, width, height)}{tail}[elt{i}]")
                appearance_filters, appearance_label, appearance_sized = _appearance_filters(
                    f"elt{i}", segment.appearance, width, height, f"ba{i}"
                )
                filters += appearance_filters
                # setpts reset the segment to t=0, so progress runs over start=0..duration.
                tfilters, tlabel, ox, oy = _element_transform(
                    appearance_label,
                    segment.transform,
                    width,
                    height,
                    f"bt{i}",
                    start=0.0,
                    duration=segment.duration,
                    element_sized=appearance_sized or not free,
                )
                filters += tfilters
                shadow_filters, tlabel, ox, oy = _with_shadow(
                    tlabel, ox, oy, segment.appearance.shadow, width, height, fps, f"bs{i}",
                    start=skip, duration=round(span - skip, 6),
                )
                filters += shadow_filters
                filters.append(f"[bg{i}][{tlabel}]overlay=x='{ox}':y='{oy}',format=yuv420p,setsar=1{exact}[v{i}]")
            if still:
                pass  # 一张图没有声音:音频那一路整条不建
            elif source.audio is not None:
                tempo = atempo_filters(segment.speed)
                audio_fades = _fade_filters(segment.fade_in, segment.fade_out, segment.duration, audio=True)
                # The clip's own gain (增益) mixes its audio, like a video clip's linked audio in PR/DaVinci.
                gain = _volume_expr(segment.gain, segment.gain_keyframes, segment.duration)
                sound_in, sound_out, sound_zero = source.sound_trim
                filters.append(
                    f"{source.audio}atrim=start={sound_in}:end={sound_out},{_audio_from(sound_zero)}{tempo}"
                    f"{gain}aresample={AUDIO_RATE},aformat=channel_layouts=stereo{audio_fades}"
                    f"{_exact_span(frames[i][1], fps, audio=True)}[a{i}]"
                )
            else:
                # No source audio, or the base track is silenced by a solo elsewhere.
                filters.append(f"anullsrc=r={AUDIO_RATE}:cl=stereo,atrim=0:{span:.6f}[a{i}]")
        else:
            #: 空档:正好这么多帧的黑(从段内 skip 起的那截已经挪回 0 起)。
            filters.append(
                f"color=black:s={width}x{height}:r={fps},trim=0:{round(span - skip, 6)},format=yuv420p,setsar=1[v{i}]"
            )
            if not still:
                filters.append(f"anullsrc=r={AUDIO_RATE}:cl=stereo,atrim=0:{span:.6f}[a{i}]")
        video_labels.append(f"[v{i}]")
        if not still:
            audio_labels.append(f"[a{i}]")

    if window is not None:
        #: 这几段的画面接起来、挪回它们在时间线上的位置:上层、字幕、花字的 enable 窗口和关键帧都按
        #: 时间线绝对时间写,底下这一路也得是绝对时间。
        joined = "".join(video_labels)
        if len(video_labels) > 1:
            filters.append(f"{joined}concat=n={len(video_labels)}:v=1:a=0[vjoined]")
            joined = "[vjoined]"
        filters.append(f"{joined}{_frame_clock(fps)}{_shift_pts(round(window.base + window.skip, 6))}[vbase]")
        if not still:
            filters.append(f"{''.join(audio_labels)}concat=n={len(audio_labels)}:v=0:a=1[abase]")
    else:
        pairs = "".join(v + a for v, a in zip(video_labels, audio_labels))
        filters.append(f"{pairs}concat=n={len(video_labels)}:v=1:a=1[vjoined][abase]")
        filters.append(f"[vjoined]{_frame_clock(fps)}[vbase]")

    # Upper-video-track clips composited over the base, each an element at its transform
    # (cover-fitted at the source's own aspect ratio, then scaled/rotated/faded — see _element_fit).
    video_label = "[vbase]"
    for i, overlay in enumerate(plan.overlays):
        if window is not None and not window.covers(overlay.start, overlay.duration):
            continue
        path = resolve(overlay.source.file_key)
        src = overlay.source
        skip = _layer_skip(window, overlay.start, path)
        seek, tin, tout = _seek_and_trim(src.src_in + skip * overlay.speed, src.src_out)
        zero = round(tin - skip * overlay.speed, 6)  # 这一段自己的 0 点在这一路输入里的位置
        args += _image_loop_args(path, tout) + seek + ["-i", str(path)]
        preset = f",{FILTER_PRESETS[overlay.filter]}" if overlay.filter else ""
        lut_path = _escape_filter_path(resolve(overlay.lut)) if overlay.lut else ""
        preset += _grade_filter(dict(overlay.grade), overlay.curves, lut_path)
        video_fades = _fade_filters(overlay.video_fade_in, overlay.video_fade_out, overlay.duration, audio=False)
        # 上层片段按素材**自己的宽高比**成元素(铺满画幅的那个大小,不裁),再按变换缩放 —— 竖素材做横画幅的
        # 画中画就是竖的,和预览一样。此前先裁成画幅的比例:竖的人像画中画在成片里成了一条横的。
        filters.append(
            f"[{input_index}:v]trim=start={tin}:end={tout},setpts={_video_from(zero, overlay.speed)},"
            f"{_element_fit(overlay.appearance, 'increase', width, height)}"
            f"{preset}{video_fades},setpts=PTS+{overlay.start}/TB[oelt{i}]"
        )
        appearance_filters, appearance_label, appearance_sized = _appearance_filters(
            f"oelt{i}", overlay.appearance, width, height, f"oa{i}"
        )
        filters += appearance_filters
        # Overlay lives on the main timeline; progress runs over its start..start+duration.
        tfilters, tlabel, ox, oy = _element_transform(
            appearance_label,
            overlay.transform,
            width,
            height,
            f"ot{i}",
            start=overlay.start,
            duration=overlay.duration,
            element_sized=appearance_sized or not _is_free_element(overlay.appearance),
        )
        filters += tfilters
        shadow_filters, tlabel, ox, oy = _with_shadow(
            tlabel, ox, oy, overlay.appearance.shadow, width, height, fps, f"os{i}",
            start=overlay.start + skip, duration=round(overlay.duration - skip, 6),
        )
        filters += shadow_filters
        out_label = f"[vov{i}]"
        filters.append(
            # eof_action=repeat(而不是 pass):叠加流常常比它的 enable 窗口短一丁点 —— 用了
            # 输入级 -ss 快进后,解码从 src_in 之后的第一帧开始,尾巴就少了不到一帧。pass 会在
            # 流结束的瞬间把底层放出来,于是**每个叠加片段的最后 1~2 帧变黑**,连续片段之间
            # 看起来就是"切换处闪一下黑"(blackdetect 在真实工程里逐个边界都抓到了)。
            # repeat 保持最后一帧,窗口由 enable 关闭 —— 前提是 enable 右开(见 _shown_during),
            # 否则窗口末端那一帧还开着,repeat 出来的末帧就多露一帧。
            f"{video_label}[{tlabel}]overlay=x='{ox}':y='{oy}':eof_action=repeat:"
            f"enable='{_shown_during(overlay.start, overlay.start + overlay.duration, fps)}'{out_label}"
        )
        video_label = out_label
        input_index += 1

    # 字幕 + 花字:优先叠加「按预览 CSS 用无头 Chromium 渲染的透明 PNG」(text_layers),逐像素
    # 对齐预览(字体/字号/描边/阴影/背景圆角全一致);拿不到(找不到前端 dist/Chromium,或测试
    # 关闭)时回落到下面的 ASS(libass)烧字。字幕(和能并的静止花字)合成一路轨叠一次,见 compose_text_layers;
    # 带动画的花字和 AI 标识各 -loop 成时间线上的一段,再叠加。
    if text_layers is not None:
        if text_layers.track is not None:
            args += ["-f", "concat", "-safe", "0", "-i", str(text_layers.track.script)]
            out_label = "[vtrack]"
            filters.append(
                f"{video_label}[{input_index}:v]overlay=x={text_layers.track.x}:y={text_layers.track.y}{out_label}"
            )
            video_label = out_label
            input_index += 1
        for k, png, _pw, _ph in text_layers.text_overlays:
            item = plan.text_overlays[k]
            if window is not None and not window.covers(item.start, item.duration):
                continue
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
                f"enable='{_shown_during(item.start, item.start + item.duration, fps)}'{out_label}"
            )
            video_label = out_label
            input_index += 1
        for k, (label, (png, pw, ph)) in enumerate(zip(plan.ai_labels, text_layers.ai_labels)):
            if window is not None and not window.covers(label.start, label.duration):
                continue
            #: 标识是一张不动的图:只渲一截时从这一截前一点开始生成,不必从片头一帧帧数过来(整片的角标就是整片长)。
            begin = max(label.start, window.start - _WINDOW_PREROLL) if window is not None else label.start
            span = label.start + label.duration - begin
            args += ["-loop", "1", "-framerate", f"{fps:g}", "-t", f"{span + 0.2:.6f}", "-i", str(png)]
            lx, ly = _ai_label_position(label, pw, ph, width, height)
            filters.append(f"[{input_index}:v]setpts=PTS-STARTPTS+{begin}/TB[lbin{k}]")
            out_label = f"[vlb{k}]"
            filters.append(
                f"{video_label}[lbin{k}]overlay=x={lx}:y={ly}:eof_action=repeat:"
                f"enable='{_shown_during(label.start, label.start + label.duration, fps)}'{out_label}"
            )
            video_label = out_label
            input_index += 1
    elif _has_text(plan):
        ass_path = (workdir or output_path.parent) / "subtitles.ass"
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

    if still and window is not None:
        #: 只取一帧:输出换成单帧图片,音频整条不建(一张图没有声音)。
        #: -ss 放在 filter_complex **之后** —— 输出侧 seek,各层照常按时间线时间算,
        #: 那些跟时间走的东西(关键帧、淡入淡出、字幕的出入点)才会落在正确的位置上。
        args += [
            "-filter_complex",
            ";".join(filters),
            "-map",
            video_label,
            "-ss",
            f"{window.start:.3f}",
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(output_path),
        ]
        return args

    # Audio-track clips + overlay video-track clips' audio, mixed over the base audio. An
    # overlay source may be a video without an audio stream (or an image) — probe and skip it,
    # since mapping [n:a] on a source with no audio would fail the whole render.
    # 基底视频轨的声音也能被闪避。**它不在 audio_overlays 里** —— 上层轨的声音是 overlay,
    # 基底轨的声音是 concat 出来的 [abase]。配音压原声正是这个形状(原片在基底轨上),漏了这一路
    # 就等于整条闪避没生效:成片里两个人同时说话,而界面上那个开关是按下去了的。
    base_audio_label = "[abase]"
    scratch = workdir or output_path.parent
    if plan.base_audio_duck_windows:
        args += _duck_input(plan.base_audio_duck_windows, plan.timeline_duration + 1.0, scratch / "duck_base.f32")
        filters.append(_duck_apply("[abase]", input_index, "abaseduck"))
        input_index += 1
        base_audio_label = "[abaseduck]"
    audio_label = base_audio_label
    if plan.audio_overlays:
        mix_inputs = [base_audio_label]
        for i, item in enumerate(plan.audio_overlays):
            if window is not None and not window.covers(item.start, item.duration):
                continue
            path = resolve(item.source.file_key)
            if item.optional and not has_audio.get(path, False):
                continue  # overlay video-track source with no audio stream
            src = item.source
            #: 跨进这一截的照样从头解(和底轨跳过一截时的声音一样,见 _base_sources):声音解码几乎不花钱,
            #: 从中间快进起解反倒会被时间戳补偿拉伸一点点,和整条渲时差在采样上。
            seek, tin, tout = _seek_and_trim(src.src_in, src.src_out)
            args += seek + ["-i", str(path)]
            delay_ms = int(item.start * 1000)
            audio_fades = _fade_filters(item.fade_in, item.fade_out, item.duration, audio=True)
            # 闪避:adelay 之后这条声音已经在时间线时间上,窗口是绝对时间,包络也从时间线 0 算起。
            delayed = f"aovpre{i}" if item.duck_windows else f"aov{i}"
            filters.append(
                f"[{input_index}:a]atrim=start={tin}:end={tout},{_audio_from(tin)}"
                f"{atempo_filters(item.speed)}"
                f"{_volume_expr(item.gain, item.gain_keyframes, item.duration)}"
                f"aresample={AUDIO_RATE},aformat=channel_layouts=stereo{audio_fades},"
                f"adelay={delay_ms}:all=1[{delayed}]"
            )
            input_index += 1
            if item.duck_windows:
                args += _duck_input(item.duck_windows, item.start + item.duration + 1.0, scratch / f"duck{i}.f32")
                filters.append(_duck_apply(f"[{delayed}]", input_index, f"aov{i}"))
                input_index += 1
            mix_inputs.append(f"[aov{i}]")
        if len(mix_inputs) > 1:
            filters.append(f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:normalize=0[amix]")
            audio_label = "[amix]"

    if chunk is not None and window is not None:
        #: 分块:画面只要这一截里的整帧(end 之前,帧号按帧格算,块与块之间不多不少),只有画面;声音在**混音之后、
        #: 总线之前**按采样数切下这一截,写成无损 PCM —— 限幅 / 响度标准化是跨整条的状态,接起来以后再统一过一遍
        #: (见 _chunk_mux_command)。切下来的声音**保留时间线上的时间戳**,不归零:两个输出按时间戳齐头并进,声音
        #: 要是从 0 起而画面从这一截的起点起,ffmpeg 会先把声音追到画面那么远,这期间解出来的画面全攒在内存里
        #: (实测 20 秒 1080p 就多攒 1.3 GB)。WAV 不认时间戳,写进去的只是采样。
        first_frame = round(window.start * fps)
        first_sample, last_sample = round(window.start * AUDIO_RATE), round(window.end * AUDIO_RATE)
        filters.append(
            f"{audio_label}atrim=start_sample={first_sample}:end_sample={last_sample}[achunk]"
        )
        assert audio_path is not None, "分块渲染要给声音那一截的去处"
        last = window.end >= plan.timeline_duration
        args += [
            "-filter_complex", ";".join(filters),
            "-map", video_label, "-ss", f"{window.start:.6f}",
            #: 最后一块和整条渲一样按 -t 截在片长上;其余按帧数,块与块之间不多不少。
            *(["-t", str(round(plan.timeline_duration - window.start, 6))] if last
              else ["-frames:v", str(round(window.end * fps) - first_frame)]),
            "-r", str(plan.output.fps), *_video_encode_args(plan.output, force_software=force_software), "-an",
            str(output_path),
            "-map", "[achunk]", "-c:a", "pcm_f32le", str(audio_path),
        ]
        return args

    filters.append(f"{audio_label}{_master_bus(plan.output.loudnorm)}[amaster]")
    audio_label = "[amaster]"

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
        #: 写进文件的元数据(AI 生成内容的 AIGC 隐式标识)。只用 MP4 的标准键,不开 use_metadata_tags:
        #: 那样写出来的 mdta 键在 remux / 转码后会丢,见 domain.render.aigc_metadata。
        *[part for key, value in plan.output.metadata for part in ("-metadata", f"{key}={value}")],
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    return args


_FILTER_SCRIPT_FLAGS: dict[str, str] = {}


def _filter_script_flag(ffmpeg: str) -> str:
    """「从文件读滤镜图」在这台机器的 ffmpeg 上怎么写(按可执行文件缓存)。

    ffmpeg 7.0 起是通用的 `-/filter_complex <文件>`(任何选项前加 `-/` 都表示从文件读值),
    旧的 `-filter_complex_script` 在 7.x 还认、8.0 起删了;6.x 及更早只认后者。所以看
    `-h full` 里还列不列它:列着就用它(≤7.x 都通),没列就是新版,用 `-/`。
    探测没成就按新版算,但**不记住** —— 一次失败的探测不该定下这个进程以后每一次导出。"""
    if ffmpeg in _FILTER_SCRIPT_FLAGS:
        return _FILTER_SCRIPT_FLAGS[ffmpeg]
    try:
        probe = run_logged(
            [ffmpeg, "-hide_banner", "-h", "full"],
            capture_output=True, text=True, timeout=20, what="ffmpeg 选项探测", level=logging.DEBUG,
        )
    except Exception:
        return "-/filter_complex"
    if probe.returncode != 0 or not probe.stdout:
        return "-/filter_complex"
    flag = "-filter_complex_script" if "-filter_complex_script" in probe.stdout else "-/filter_complex"
    _FILTER_SCRIPT_FLAGS[ffmpeg] = flag
    return flag


def _with_filter_script(command: list[str], workdir: Path) -> list[str]:
    """把命令里的滤镜图挪进这次渲染中转目录里的一个文件,命令行只留文件路径(随目录一起清掉)。

    滤镜图随时间线线性增长(每段、每层、每条字幕都是几百个字符),而 Windows 上一条命令行
    最长 32767 个字符(CreateProcess 的上限)—— 一两百段的时间线在那里连 ffmpeg 都起不来,
    报的还是「文件名或扩展名太长」这种看不出原因的话。放进文件就和时间线多长无关了。
    build_ffmpeg_command 仍然产出带内联滤镜图的命令:读起来、测起来都是一整条。"""
    if "-filter_complex" not in command:
        return command
    at = command.index("-filter_complex")
    script = workdir / "filter_complex.txt"
    script.write_text(command[at + 1], encoding="utf-8")
    return [*command[:at], _filter_script_flag(command[0]), str(script), *command[at + 2:]]


def _png_size(data: bytes) -> tuple[int, int]:
    """从 PNG 头(IHDR)读宽高,免依赖。"""
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def _text_for_burn(plan: RenderPlan, workdir: Path) -> BurnedText | None:
    """文字怎么烧:能渲成 PNG 就用 PNG(分好层,见 compose_text_layers);否则回落 ASS(返回 None)—— 回落
    之前先看 ffmpeg 有没有 libass。没有的话 ffmpeg 会以「No such filter: 'subtitles'」失败,在这里先说人话。"""
    text_pngs = _rasterize_text(plan, workdir)
    if text_pngs is None:
        if _has_text(plan) and not ffmpeg_has_libass(settings.ffmpeg):
            raise RenderExecutionError("renderErr_noLibass", ffmpeg=settings.ffmpeg)
        return None
    return compose_text_layers(plan, text_pngs, workdir)


def _rasterize_text(plan: RenderPlan, workdir: Path) -> dict | None:
    """把每条字幕/花字按预览 CSS 渲染成透明 PNG,返回 {subtitles, text_overlays, ai_labels} 列表(元素为
    (png路径, 宽, 高),和计划里的条目一一对应);关掉开关 / 找不到前端 dist / Chromium 失败时返回 None → 回落 ASS。

    字一样、样式一样的只渲一次,几条共用一张 PNG:字幕是「一框一段」,同一句话被别的轨上的字切开、或者
    隔一阵又出现一次,都是同一张图。"""
    if not settings.text_rasterize:
        return None
    if not _has_text(plan):
        return {"subtitles": [], "text_overlays": [], "ai_labels": []}
    try:
        from app.media.text_render import TextRasterizer

        tr = TextRasterizer(plan.output.width, plan.output.height)
        if not tr.available():
            logger.warning("frontend dist not found; text burn falls back to ASS")
            return None
        rendered: dict[tuple, tuple[Path, int, int]] = {}

        def once(key: tuple, name: str, draw: Callable[[], bytes]) -> tuple[Path, int, int]:
            if key not in rendered:
                png = draw()
                path = workdir / name
                path.write_bytes(png)
                rendered[key] = (path, *_png_size(png))
            return rendered[key]

        result: dict = {"subtitles": [], "text_overlays": [], "ai_labels": []}
        with tr:
            for i, item in enumerate(plan.subtitles):
                result["subtitles"].append(once(
                    ("subtitle", item.text), f"sub{i}.png",
                    lambda item=item: tr.render_subtitle(item.text, plan.subtitle_style),
                ))
            for i, item in enumerate(plan.text_overlays):
                result["text_overlays"].append(once(
                    ("huazi", item.text, item.style), f"txt{i}.png",
                    lambda item=item: tr.render_huazi(item.text, item.style),
                ))
            for i, label in enumerate(plan.ai_labels):
                result["ai_labels"].append(once(
                    ("label", label.text, label.font_size), f"label{i}.png",
                    lambda label=label: tr.render_label(label.text, label.font_size),
                ))
        return result
    except Exception:
        logger.exception("text rasterization failed; falling back to ASS burn")
        return None


_STILL_TIMEOUT = 180  # 秒;一帧通常几百毫秒到两三秒


def render_still(plan: RenderPlan, resolve: Callable[[str], Path], output_path: Path, at: float) -> Path:
    """把时间线在 `at` 处的**合成画面**渲成一张图。

    **走和成片同一条命令**(build_ffmpeg_command,只是换了输出那一段)。另写一条的话它迟早和
    成片长得不一样,而这种不一样最难发现:画面看着对,只是少了一层花字 —— 而那正是预览里
    用 DOM 叠出来的、canvas 抓不到的东西。

    这里**也要先把文字渲成 PNG**:少这一步,取出来的帧就是没有字幕的那一版。只渲这一刻
    看得见的那几条(still_plan)。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plan = still_plan(plan, at)
    with render_workdir() as workdir:
        text_layers = _text_for_burn(plan, workdir)
        command = build_ffmpeg_command(plan, resolve, output_path, text_layers=text_layers, still_at=at, workdir=workdir)
        try:
            result = run_logged(_with_filter_script(command, workdir), capture_output=True, text=True,
                                timeout=_STILL_TIMEOUT, what="取当前帧")
        except subprocess.TimeoutExpired as exc:
            raise RenderExecutionError("renderErr_frameTimeout", seconds=_STILL_TIMEOUT) from exc
    if result.returncode != 0:
        #: 带上 ffmpeg 自己说的那句 —— 只说「取当前帧失败」的话,用户和排查的人都只能干瞪眼
        #: (GIF 不认 `-loop` 那次就是这样:界面上一句话,原因只在后端日志里)。
        raise RenderExecutionError(
            "renderErr_frameFailed",
            detail=blame_line(result.stderr) or LocalizedError("audioErr_ffmpegNoReason"),
        )
    if not output_path.is_file() or output_path.stat().st_size == 0:
        #: 时间点落在片尾之后:ffmpeg 成功退出但什么都不写。空文件比报错更难查。
        raise RenderExecutionError("stillErr_noFrame")
    return output_path


@contextlib.contextmanager
def render_workdir() -> Iterator[Path]:
    """一次导出 / 取帧自己的中转目录:文字 PNG、.ass、滤镜图这些都写在这里,结束(成功、失败、取消)时整个删掉。

    此前它们写在成片旁边,文件名按**序列** id 起(`text_{sequence_id}.sub0.png`):同一条时间线同时导出
    两份(比如 1080p 和 720p),后起的那份把先起的那份的字幕 PNG 覆盖掉 —— 先起的成片里烧进去的是另一份
    尺寸的字。.ass 倒是按任务起名,可从来没人删,导出目录里一直在攒。按任务一个目录,两件事一起没了。"""
    with tempfile.TemporaryDirectory(prefix="mosael-render-") as tmp:
        yield Path(tmp)


#: 一次 ffmpeg 最多同时挂多少层(底轨片段、上层片段、音频轨片段、花字):超过就分块渲,每块各起一次 ffmpeg。
#: 每一层是一路输入加一条滤镜链,1080p 下一层二三十 MB:300 段不同素材的时间线一次渲要 7 GB 内存;
#: macOS 从图形界面起的进程默认只能开 256 个文件,250 段以上 ffmpeg 直接「Too many open files」。
_CHUNK_LAYERS = 60


def _chunk_windows(plan: RenderPlan) -> list[tuple[float, float]] | None:
    """把时间线切成几截,每截同时在场的层不超过 _CHUNK_LAYERS;层不多(一次渲得下)就是 None。

    切点只取在帧格上(第 k 帧的时刻),而且挑在某一层**开始之前**:跨过切点的层两截都要挂一次。
    每一截尽量往后延,直到再延一刀就超了;一刀之内就超(同一时刻挂着的层本来就多)也只能切在那里。"""
    fps, total = plan.output.fps, plan.timeline_duration
    layers: list[tuple[float, float]] = []
    at = 0.0
    for segment in plan.video_segments:
        if segment.kind == "clip":
            layers.append((at, at + segment.duration))
        at += segment.duration
    layers += [(item.start, item.start + item.duration) for item in (*plan.overlays, *plan.audio_overlays)]
    layers += [(item.start, item.start + item.duration) for item in plan.text_overlays]
    if len(layers) <= _CHUNK_LAYERS:
        return None
    cuts = sorted({math.floor(start * fps + 1e-6) for start, _end in layers if 0 < start < total})
    windows: list[tuple[float, float]] = []
    first = 0
    while True:
        begin = first / fps
        live = sorted(start for start, end in layers if end > begin)
        later = [cut for cut in cuts if cut > first]
        best = None
        for cut in later:
            if bisect.bisect_left(live, cut / fps) > _CHUNK_LAYERS:
                break
            best = cut
        if best is None:
            best = later[0] if later else None
        if best is None:
            windows.append((begin, total))
            break
        windows.append((begin, best / fps))
        first = best
    return windows if len(windows) > 1 else None


def _chunk_progress(block: dict[str, str], done_frames: int, total_frames: int, fps: float) -> RenderProgress:
    """分块渲染时的进度:按帧数算(每块各自从 0 数,前面几块已经出了 done_frames 帧)。"""
    try:
        frames = done_frames + int(block.get("frame", "0"))
    except ValueError:
        frames = done_frames
    fraction = min(1.0, frames / max(total_frames, 1))
    speed = _parse_ffmpeg_speed(block.get("speed", ""))
    eta = (total_frames - frames) / fps / speed if speed else None
    return RenderProgress(fraction=fraction, speed=speed, fps=None, eta_seconds=eta)


def _chunk_mux_command(plan: RenderPlan, workdir: Path, videos: list[Path], audios: list[Path], output_path: Path) -> list[str]:
    """把各块接起来:画面原样拷贝(各块同一套编码参数,开头都是关键帧),声音的 PCM 按采样接上以后**整条**过
    一遍总线(限幅 / 响度标准化跨整条才对),再编 AAC。"""
    def listing(name: str, files: list[Path]) -> Path:
        script = workdir / name
        script.write_text("ffconcat version 1.0\n" + "".join(f"file '{file.name}'\n" for file in files), encoding="utf-8")
        return script

    return [
        settings.ffmpeg, "-y", "-v", "error", "-progress", "pipe:1", "-nostats",
        "-f", "concat", "-safe", "0", "-i", str(listing("video.ffconcat", videos)),
        "-f", "concat", "-safe", "0", "-i", str(listing("audio.ffconcat", audios)),
        "-filter_complex", f"[1:a]{_master_bus(plan.output.loudnorm)}[amaster]",
        "-map", "0:v", "-map", "[amaster]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-t", str(plan.timeline_duration),
        *[part for key, value in plan.output.metadata for part in ("-metadata", f"{key}={value}")],
        "-movflags", "+faststart", str(output_path),
    ]


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

    hw_encoder = _choose_hw_encoder(plan)
    logger.info(
        "render start: encoder=%s output=%dx%d@%gfps duration=%.1fs → %s",
        hw_encoder or "libx264",
        plan.output.width,
        plan.output.height,
        plan.output.fps,
        plan.timeline_duration,
        output_path.name,
    )

    #: 中转文件(文字 PNG、.ass)都进这次渲染自己的目录,出了这个 with 就删,不管成败。
    with render_workdir() as workdir:
        # 起一次无头 Chromium 把所有字幕/花字渲染成 PNG(软件回落时复用同一批,不重复渲染)。
        text_layers = _text_for_burn(plan, workdir)

        windows = _chunk_windows(plan)
        encoding = False

        def spawn(
            command: list[str], progress_of: Callable[[dict[str, str]], RenderProgress], *, last: bool = True,
        ) -> tuple[int, str, bool]:
            nonlocal encoding
            process = popen_text(
                _with_filter_script(command, workdir), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            # ffmpeg's stderr must be drained WHILE we read progress off stdout. A source it cannot
            # fully decode emits an error per frame even at -v error; once that fills the pipe ffmpeg
            # blocks writing it, stops emitting progress, and both sides wait forever with the job
            # stuck in `running` and no way out but killing the backend.
            child = ChildProcess(process)
            if on_child is not None:
                on_child(child)
            block: dict[str, str] = {}
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
                if value == "end" and last and on_phase is not None:
                    on_phase(PHASE_FINALIZE)  # -progress end; ffmpeg still writes faststart moov
                if on_progress is not None:
                    on_progress(progress_of(block))
                block = {}
            stderr_tail = child.finish()
            return process.returncode or 0, stderr_tail, child.killed

        def run_once(*, force_software: bool, fallback: bool = False) -> tuple[int, str, bool]:
            nonlocal encoding
            encoding = False  # 回落重跑时,出帧了再报一次「编码」
            if on_phase is not None:
                on_phase(PHASE_FALLBACK if fallback else PHASE_PREPARE)
            if windows is None:
                # build_ffmpeg_command probes every source; that is part of the "preparing" wait.
                command = build_ffmpeg_command(
                    plan, resolve, output_path, force_software=force_software, text_layers=text_layers, workdir=workdir
                )
                return spawn(command, lambda block: _progress_from_block(block, total_us))
            return render_chunks(force_software)

        def render_chunks(force_software: bool) -> tuple[int, str, bool]:
            """分块渲(见 _chunk_windows):每块一次 ffmpeg,画面一个 mp4、混音前的声音一个 PCM,最后接起来。"""
            assert windows is not None
            fps = plan.output.fps
            total_frames = math.ceil(plan.timeline_duration * fps - 1e-6)
            videos: list[Path] = []
            audios: list[Path] = []
            for n, (start, end) in enumerate(windows):
                videos.append(workdir / f"chunk{n}.mp4")
                audios.append(workdir / f"chunk{n}.wav")
                command = build_ffmpeg_command(
                    plan, resolve, videos[-1], force_software=force_software, text_layers=text_layers,
                    chunk=(start, end), audio_path=audios[-1], workdir=workdir,
                )
                done = round(start * fps)
                result = spawn(
                    command, lambda block, done=done: _chunk_progress(block, done, total_frames, fps), last=False,
                )
                if result[0] != 0:
                    return result
            logger.info("render: %d chunks done, joining → %s", len(windows), output_path.name)
            return spawn(
                _chunk_mux_command(plan, workdir, videos, audios, output_path),
                lambda block: RenderProgress(fraction=1.0, speed=None, fps=None, eta_seconds=0.0),
            )

        returncode, stderr_tail, killed = run_once(force_software=hw_encoder is None)
        # 起不来的硬件编码器已经被小样自检挡在开跑之前(_hw_encoder_works);这里兜的是跑到一半才挂的
        # 那种 —— 只要不是我们自己停的(取消/超时会置 `killed`),就用软件再跑一遍,保证导出能落地。
        hw_used = hw_encoder is not None
        if returncode != 0 and hw_used and not killed:
            logger.warning(
                "render: hardware encoder %s failed (rc=%s), retrying with software libx264",
                hw_encoder,
                returncode,
            )
            returncode, stderr_tail, killed = run_once(force_software=True, fallback=True)
        if returncode != 0:
            logger.error("render: ffmpeg failed (rc=%s):\n%s", returncode, stderr_tail)
            raise RenderExecutionError("renderErr_ffmpegExit", code=returncode, stderr_tail=stderr_tail)
