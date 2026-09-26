"""讲解视频:把结构化的教学内容整理成场景读的 spec.json。

**这里不生成代码。** 场景是一份写死的文件(scene_kit/mosael_explainer.py),内容走 JSON —— 用户的文字、
公式、代码一个字符也不会拼进 Python 源码。这里做的是:校验、截到画得下、算每一步多长、挡掉危险的 LaTeX、
把函数表达式解析一遍并算好坐标范围,然后交给场景。
"""

from __future__ import annotations

import math
import re
from typing import Any

from manim_guard import FORBIDDEN_TEX
from plugin_kit import PluginError, line
from scene_kit.mosael_expr import ExpressionError, auto_y_range, compile_function, nice_step, parse, sample
from scene_kit.mosael_text import display_width, latex_to_plain, reading_seconds

# 与场景里的 T_* 同一组数:估算「这一步至少要多久」。
BEATS = {"title": 0.6, "caption": 0.4, "formula": 1.2, "axes": 0.8, "curve": 1.5, "label": 0.4,
         "code": 0.8, "highlight": 0.4, "bullet": 0.5, "out": 0.5}

MAX_STEPS = 20
MAX_BULLETS = 6
MAX_FORMULAS = 3
MAX_CODE_LINES = 30
MAX_TOTAL_SECONDS = 600

THEMES = {
    "dark": {"background": "#0F1115", "text": "#F4F4F5", "muted": "#A1A1AA", "panel": "#1B1E24", "accent": "#4F8CFF",
             "code_style": "monokai"},
    "light": {"background": "#FAFAF7", "text": "#16181D", "muted": "#5B6070", "panel": "#ECEAE4", "accent": "#2563EB",
              "code_style": "friendly"},
}

def _text(value: Any, limit: int) -> str:
    return re.sub(r"[ \t]+", " ", str(value or "")).strip()[:limit]


def _number(value: Any, fallback: float | None = None) -> float | None:
    if value is None or value == "":
        return fallback
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def check_latex(formula: str, where: str, locale: str) -> str:
    formula = str(formula or "").strip()
    if len(formula) > 400:
        raise PluginError(line(locale, f"{where}的公式太长(最多 400 字符)。", f"The formula in {where} is too long (max 400)."))
    bad = FORBIDDEN_TEX.search(formula)
    if bad:
        raise PluginError(line(
            locale,
            f"{where}的公式里不能用 {bad.group(0)}:讲解视频的公式只排版,不读写文件、不定义命令。",
            f"{where}: {bad.group(0)} is not allowed in a formula — formulas are typeset only, no files or definitions.",
        ))
    depth = 0
    for index, ch in enumerate(formula):
        if ch in "{}" and index and formula[index - 1] == "\\":
            continue
        depth += 1 if ch == "{" else -1 if ch == "}" else 0
        if depth < 0:
            break
    if depth != 0:
        raise PluginError(line(locale, f"{where}的公式花括号没配平:{formula}", f"Unbalanced braces in the formula of {where}: {formula}"))
    return formula


def _highlights(raw: Any, lines: int, where: str, locale: str) -> list[list[int]]:
    """`[2, "4-6", 9]` → `[[2, 2], [4, 6], [9, 9]]`。每一项是讲解时依次停留的一处。"""
    out: list[list[int]] = []
    for item in (raw or [])[:12]:
        text = str(item).strip()
        match = re.fullmatch(r"(\d+)\s*(?:[-–~,:]\s*(\d+))?", text)
        if not match:
            raise PluginError(line(locale, f"{where}的高亮行写成行号或「起-止」,比如 3 或 \"4-6\":{item}",
                                   f"Highlight lines in {where} are line numbers or \"start-end\", e.g. 3 or \"4-6\": {item}"))
        first = int(match.group(1))
        last = int(match.group(2) or first)
        first, last = min(first, last), max(first, last)
        if first < 1 or first > lines:
            raise PluginError(line(locale, f"{where}的代码只有 {lines} 行,高亮不到第 {first} 行。",
                                   f"The code in {where} has {lines} lines; line {first} cannot be highlighted."))
        out.append([first, min(last, lines)])
    return out


def _plot(raw: Any, where: str, locale: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not str(raw.get("expression") or "").strip():
        return None
    expression = str(raw["expression"]).strip()
    try:
        parse(expression)
    except ExpressionError as exc:
        raise PluginError(f"{where}:" + (exc.zh if line(locale, "zh", "en") == "zh" else exc.en)) from exc
    x_min, x_max = _number(raw.get("x_min"), -5.0), _number(raw.get("x_max"), 5.0)
    if x_min is None or x_max is None or not x_min < x_max or x_max - x_min > 1e6:
        raise PluginError(line(locale, f"{where}的 x 范围不对:要 x_min < x_max。", f"{where}: the x range needs x_min < x_max."))
    f = compile_function(expression)
    points = sample(f, x_min, x_max, 400)
    if not any(y is not None for _, y in points):
        raise PluginError(line(locale, f"{where}的函数在 [{x_min:g}, {x_max:g}] 上没有定义(比如 log 的自变量是负数)。",
                               f"{where}: the function is undefined on [{x_min:g}, {x_max:g}]."))
    y_min, y_max = _number(raw.get("y_min")), _number(raw.get("y_max"))
    if y_min is None or y_max is None or not y_min < y_max:
        y_min, y_max = auto_y_range(points)
    # 默认标签把 `x^2`、`x**2` 写成 `x²`:图上的字是给人看的,不是给解析器看的
    label = _text(raw.get("label"), 60) or f"y = {latex_to_plain(expression.replace('**', '^').replace('*', '·'))}"
    return {"expression": expression, "x_range": [x_min, x_max], "y_range": [y_min, y_max],
            "x_step": nice_step(x_min, x_max), "y_step": nice_step(y_min, y_max), "label": label}


def step_minimum(step: dict[str, Any], show_narration: bool) -> float:
    """这一步的动画本身要多久(不算停留)。"""
    total = BEATS["title"] + BEATS["out"]
    if step.get("narration") and show_narration:
        total += BEATS["caption"]
    total += BEATS["formula"] * len(step.get("formulas") or [])
    if step.get("plot"):
        total += BEATS["axes"] + BEATS["curve"] + BEATS["label"]
    if step.get("code"):
        total += BEATS["code"] + BEATS["highlight"] * len(step["code"].get("highlight") or [])
    total += BEATS["bullet"] * len(step.get("bullets") or [])
    return total


def step_seconds(step: dict[str, Any], requested: float | None, show_narration: bool) -> float:
    """这一步多长:给了就用给的(不少于动画本身),没给按旁白的朗读时长,没有旁白按画面上的字。"""
    minimum = step_minimum(step, show_narration) + 0.5
    if requested is not None:
        return round(max(minimum, min(120.0, requested)), 2)
    if step.get("narration"):
        reading = reading_seconds(step["narration"]) + 1.0
    else:
        on_screen = " ".join([step["title"], *(step.get("bullets") or [])])
        reading = reading_seconds(on_screen) + 1.5 + (2.0 if step.get("code") or step.get("plot") else 0.0)
    return round(min(90.0, max(minimum, reading)), 2)


def build_spec(payload: dict[str, Any], locale: str, *, use_latex: bool) -> dict[str, Any]:
    """工具入参 → 场景读的 spec。不合格抛 PluginError(说得出是第几步的哪一项)。"""
    title = _text(payload.get("title"), 80)
    if not title:
        raise PluginError(line(locale, "缺标题(title)。", "A title is required."))
    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise PluginError(line(locale, "至少要有一步(steps)。", "At least one step is required."))
    if len(raw_steps) > MAX_STEPS:
        raise PluginError(line(locale, f"最多 {MAX_STEPS} 步 —— 再多请拆成几段视频。", f"At most {MAX_STEPS} steps; split longer lessons."))
    show_narration = payload.get("show_narration") is not False
    theme_name = "light" if payload.get("theme") == "light" else "dark"
    colors = dict(THEMES[theme_name])
    code_style = colors.pop("code_style")
    accent = str(payload.get("accent") or "").strip()
    if accent:
        if not re.fullmatch(r"#?[0-9A-Fa-f]{6}", accent):
            raise PluginError(line(locale, f"强调色要写成 #RRGGBB:{accent}", f"The accent colour must be #RRGGBB: {accent}"))
        colors["accent"] = "#" + accent.lstrip("#").upper()

    steps: list[dict[str, Any]] = []
    for number, raw in enumerate(raw_steps, start=1):
        where = line(locale, f"第 {number} 步", f"step {number}")
        if not isinstance(raw, dict) or not _text(raw.get("title"), 80):
            raise PluginError(line(locale, f"{where}缺标题(title)。", f"{where.capitalize()} needs a title."))
        step: dict[str, Any] = {"kind": "step", "index": number, "title": _text(raw.get("title"), 80)}
        narration = _text(raw.get("narration"), 600)
        if narration:
            step["narration"] = narration
        bullets = [_text(one, 140) for one in (raw.get("bullets") or []) if _text(one, 140)]
        if len(bullets) > MAX_BULLETS:
            bullets = bullets[:MAX_BULLETS]
        if bullets:
            step["bullets"] = bullets
        formulas = raw.get("formulas")
        if isinstance(formulas, str):
            formulas = [formulas]
        formulas = [*(formulas or []), *([raw["formula"]] if isinstance(raw.get("formula"), str) else [])]
        formulas = [check_latex(one, where, locale) for one in formulas if str(one or "").strip()][:MAX_FORMULAS]
        plot = _plot(raw.get("plot"), where, locale)
        code_raw = raw.get("code")
        if isinstance(code_raw, str):
            code_raw = {"code": code_raw}
        code = None
        if isinstance(code_raw, dict) and str(code_raw.get("code") or "").strip():
            source = str(code_raw["code"]).expandtabs(4).strip("\n")
            source_lines = source.split("\n")
            if len(source_lines) > MAX_CODE_LINES or len(source) > 3000:
                raise PluginError(line(locale, f"{where}的代码太长:最多 {MAX_CODE_LINES} 行、3000 字符。",
                                       f"The code in {where} is too long: at most {MAX_CODE_LINES} lines and 3000 characters."))
            language = re.sub(r"[^A-Za-z0-9+#._-]", "", str(code_raw.get("language") or "python"))[:30] or "python"
            code = {"code": source, "language": language,
                    "highlight": _highlights(code_raw.get("highlight"), len(source_lines), where, locale)}
        visuals = [name for name, value in (("formulas", formulas), ("plot", plot), ("code", code)) if value]
        if len(visuals) > 1:
            raise PluginError(line(
                locale,
                f"{where}同时给了{'、'.join(visuals)}:一步只放一样(公式、函数图、代码三选一),拆成两步讲更清楚。",
                f"{where.capitalize()} has {', '.join(visuals)}: one visual per step (formulas, plot or code) — split it into two steps.",
            ))
        if formulas:
            step["formulas"] = formulas
        if plot:
            step["plot"] = plot
        if code:
            step["code"] = code
        requested = _number(raw.get("seconds"))
        step["seconds"] = step_seconds(step, requested if requested and requested > 0 else None, show_narration)
        steps.append(step)

    segments: list[dict[str, Any]] = []
    subtitle = _text(payload.get("subtitle"), 120)
    label = _text(payload.get("label"), 40)
    title_seconds = round(min(8.0, max(3.5, 2.5 + reading_seconds(f"{title} {subtitle}"))), 2)
    segments.append({"kind": "title", "title": title, "subtitle": subtitle, "label": label, "seconds": title_seconds})
    segments.extend(steps)
    summary = [_text(one, 120) for one in (payload.get("summary") or []) if _text(one, 120)][:MAX_BULLETS]
    if summary:
        seconds = BEATS["title"] + BEATS["bullet"] * len(summary) + BEATS["out"] + reading_seconds(" ".join(summary)) + 1.0
        segments.append({"kind": "summary", "title": line(locale, "要点回顾", "Key takeaways"), "points": summary,
                         "seconds": round(min(40.0, seconds), 2)})
    total = sum(one["seconds"] for one in segments)
    if total > MAX_TOTAL_SECONDS:
        raise PluginError(line(locale, f"整段大约 {total:.0f} 秒,超过 {MAX_TOTAL_SECONDS} 秒 —— 拆成几段视频。",
                               f"About {total:.0f}s in total, over {MAX_TOTAL_SECONDS}s — split it into several videos."))
    return {
        "version": 1,
        "colors": colors,
        "code_style": code_style,
        "font": _text(payload.get("font"), 60),
        "use_latex": bool(use_latex),
        "show_narration": show_narration,
        "segments": segments,
    }


def has_formulas(spec: dict[str, Any]) -> bool:
    return any(one.get("formulas") for one in spec["segments"])


def timings(spec: dict[str, Any], markers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """每一段**实际**的起止时间(场景渲染时报的,不是估的),给旁白、字幕对时间用。"""
    starts = {m["index"]: float(m.get("time") or 0) for m in markers if m.get("kind") == "segment"}
    ends = {m["index"]: float(m.get("time") or 0) for m in markers if m.get("kind") == "segment_end"}
    out: list[dict[str, Any]] = []
    elapsed = 0.0
    for index, segment in enumerate(spec["segments"]):
        start = starts.get(index, elapsed)
        end = ends.get(index, start + segment["seconds"])
        elapsed = end
        entry: dict[str, Any] = {"kind": segment["kind"], "title": segment.get("title", ""),
                                 "start": round(start, 3), "end": round(end, 3)}
        if segment["kind"] == "step":
            entry["step"] = segment["index"]
            if segment.get("narration"):
                entry["narration"] = segment["narration"]
        out.append(entry)
    return out


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？；!?;])\s*|(?<=[.])\s+", text)
    return [one.strip() for one in parts if one.strip()]


def srt(entries: list[dict[str, Any]]) -> str:
    """有旁白的每一步切成几句,按字数分这一步的时长 —— 一整段旁白挂满一屏的字幕没法看。"""
    cues: list[tuple[float, float, str]] = []
    for entry in entries:
        narration = entry.get("narration")
        if not narration:
            continue
        pieces = _sentences(narration) or [narration]
        weights = [max(1, display_width(one)) for one in pieces]
        span = max(0.5, entry["end"] - entry["start"])
        cursor = entry["start"]
        for piece, weight in zip(pieces, weights):
            length = span * weight / sum(weights)
            cues.append((cursor, cursor + length, piece))
            cursor += length

    def stamp(seconds: float) -> str:
        millis = int(round(seconds * 1000))
        hours, rest = divmod(millis, 3_600_000)
        minutes, rest = divmod(rest, 60_000)
        secs, millis = divmod(rest, 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    return "".join(f"{number}\n{stamp(start)} --> {stamp(end)}\n{text}\n\n"
                   for number, (start, end, text) in enumerate(cues, start=1))
