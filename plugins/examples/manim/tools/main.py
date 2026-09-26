"""Manim 教学动画 —— 用 Python 代码画数学、几何、函数图、算法步骤、代码讲解。

## 它是为什么存在的

讲一条公式、推一个几何关系、走一遍算法,要的是**准确**,而且要「一步一步地变」:这一项移过去、
那条边转过来、这一行代码亮起来。视频生成模型给的是像样的画面,不是对的推导;Manim(3Blue1Brown
那套动画的社区版)就是为这件事写的,本机渲染,零生成费用。

## 四个工具(都是流式的:边跑边报进度,取消时连 Manim 一起停)

- `manim_setup`:准备环境 —— 建虚拟环境、装锁定版本的 Manim、查 LaTeX、试渲一帧。
- `manim_explainer`:给结构化的教学内容(每一步的标题、旁白、要点、公式 / 函数图 / 代码),出讲解视频,不写代码。
- `manim_animation`:给一段 Manim 场景代码,画什么都行。
- `manim_still`:同样给代码,只要最后一帧(PNG)。

## 协议

stdin 读一个 JSON 请求 {"tool", "input", "locale"};stdout 一行一个 JSON(NDJSON):进度
`{"event": "progress", …}`,最后一行是结果 `{"ok": …}`。**Manim、pip 的输出一律截获**,不漏到 stdout。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from plugin_kit import Emit, PluginError, data_dir, emit, line, output_dir, progress, safe_stem
from manim_env import (
    MANIM_VERSION, configured_python, install, latex_hint, latex_status, probe, render_python, venv_dir, venv_python,
)
from manim_explainer import build_spec, has_formulas, srt, timings
from manim_guard import check
from manim_render import (
    FORMATS, RENDER_TIMEOUT, LatexFailed, Options, build_args, explain_failure, find_output, latex_failed, new_job,
    resolve_options, run,
)

TRUE = {"1", "true", "yes", "on"}


def _render(python: str, job: Path, scene_file: Path, scene: str, options: Options, locale: str,
            on_event, *, timeout: float = RENDER_TIMEOUT, user_file: str = "scene.py") -> tuple[Path, Any]:
    media = job / "media"
    log = run(build_args(python, scene_file, scene, media, options), job, locale, on_event, timeout=timeout)
    produced = find_output(media, scene, options)
    if log.returncode != 0 or produced is None:
        failure = LatexFailed if latex_failed(log) else PluginError
        raise failure(line(locale, "渲染失败:", "Rendering failed: ") + explain_failure(log, job, user_file, locale))
    return produced, log


def _deliver(produced: Path, payload: dict[str, Any], fallback: str, extension: str, locale: str) -> str:
    name = f"{safe_stem(payload.get('filename'), fallback, (*FORMATS, 'png', 'srt'))}.{extension}"
    shutil.move(str(produced), str(output_dir(locale) / name))
    return name


# ---------------------------------------------------------------- 准备环境

CHECK_SCENE = """
from manim import *


class MosaelCheck(Scene):
    def construct(self):
        self.add(Text("Manim ✓ 你好", font_size=64))


class MosaelLatexCheck(Scene):
    def construct(self):
        self.add(MathTex(r"\\int_0^1 x^2\\,dx = \\frac{1}{3}"))
"""


def manim_setup(payload: dict[str, Any], locale: str, send: Emit) -> dict[str, Any]:
    data = data_dir(locale)
    configured = configured_python()
    installed = False
    if configured:
        progress(send, 0.05, line(locale, "检查你配置的 Python", "Checking the configured Python"))
        if not Path(configured).is_file():
            raise PluginError(line(locale, f"配置的 Python 不存在:{configured}", f"The configured Python does not exist: {configured}"))
        python = configured
    else:
        installed = install(send, locale, reinstall=payload.get("reinstall") is True)
        python = str(venv_python(venv_dir(locale)))
    info = probe(python)
    if "manim" not in info:
        hint = line(locale, f"在那个环境里运行 `{python} -m pip install manim=={MANIM_VERSION}`,或清空配置改用插件自己的环境。",
                    f"Run `{python} -m pip install manim=={MANIM_VERSION}` there, or clear the setting to use the plugin's own environment.")
        raise PluginError(line(locale, "这个 Python 里导入不了 manim:", "manim cannot be imported in this Python: ")
                          + str(info.get("error") or "") + "\n" + hint)

    # 试渲一帧:cairo / pango / 字体有问题的话,在这里就暴露,而不是在第一次正式渲染时
    progress(send, 0.92, line(locale, "试渲一帧", "Rendering a test frame"))
    job = new_job(data)
    try:
        scene_file = job / "check.py"
        scene_file.write_text(CHECK_SCENE, encoding="utf-8")
        still = Options(width=640, height=360, fps=15, format="png", still=True)
        _render(python, job, scene_file, "MosaelCheck", still, locale, lambda *_: None, timeout=180, user_file="check.py")
        latex = latex_status()
        latex_ok, latex_note = latex["ok"], ""
        if latex_ok:
            progress(send, 0.96, line(locale, "试排一条公式(LaTeX)", "Typesetting a test formula (LaTeX)"))
            try:
                _render(python, job, scene_file, "MosaelLatexCheck", still, locale, lambda *_: None, timeout=180, user_file="check.py")
            except PluginError as exc:
                latex_ok, latex_note = False, str(exc)
    finally:
        shutil.rmtree(job, ignore_errors=True)

    if latex_ok:
        latex_line = line(locale, "LaTeX 可用,公式用 MathTex 排版。", "LaTeX works; formulas are typeset with MathTex.")
    elif latex["latex"]:
        latex_line = line(locale, "找到了 LaTeX,但试排公式失败(多半缺宏包):", "LaTeX was found but a test formula failed (likely a missing package): ") \
            + latex_note[:400] + line(locale, " 讲解视频会把公式写成纯文字。", " Explainers will show formulas as plain text.")
    else:
        latex_line = line(locale, "没装 LaTeX(可选):讲解视频把公式写成纯文字;自定义动画里的 MathTex 用不了。",
                          "LaTeX is not installed (optional): explainers show formulas as plain text; MathTex is unavailable in custom animations. ") \
            + latex_hint(locale)
    return {
        "ready": True,
        "python": info.get("python", ""),
        "manim": info.get("manim", ""),
        "source": "configured" if configured else "plugin",
        "latex": latex_ok,
        "ffmpeg": line(locale, "不需要:Manim 用 PyAV 编码,自带 FFmpeg 的库。", "Not needed: Manim encodes with PyAV, which bundles FFmpeg."),
        "summary": line(
            locale,
            f"Manim {info.get('manim')} 就绪{'(刚装好)' if installed else ''}。{latex_line}",
            f"Manim {info.get('manim')} is ready{' (just installed)' if installed else ''}. {latex_line}",
        ),
    }


# ---------------------------------------------------------------- 讲解视频

def manim_explainer(payload: dict[str, Any], locale: str, send: Emit) -> dict[str, Any]:
    python = render_python(locale)
    latex_ok = latex_status()["ok"]
    spec = build_spec(payload, locale, use_latex=latex_ok)
    options = resolve_options({**payload, "format": "mp4", "transparent": False}, locale)
    total = len(spec["segments"])
    titles = {index: one.get("title", "") for index, one in enumerate(spec["segments"])}
    state = {"segment": 0}

    def on_event(kind: str, value: Any) -> None:
        if kind == "marker" and value.get("kind") == "segment":
            state["segment"] = int(value.get("index") or 0)
            index = state["segment"]
            progress(send, 0.92 * index / total, line(locale, f"第 {index + 1}/{total} 段:{titles.get(index, '')}",
                                                      f"Part {index + 1}/{total}: {titles.get(index, '')}"))
        elif kind == "marker" and value.get("kind") == "done":
            progress(send, 0.95, line(locale, "合成视频", "Combining the video"))
        elif kind == "animation":
            index = state["segment"]
            _, _, percent = value
            progress(send, 0.92 * (index + 0.8 * percent / 100) / total,
                     line(locale, f"第 {index + 1}/{total} 段:{titles.get(index, '')} · {percent}%",
                          f"Part {index + 1}/{total}: {titles.get(index, '')} · {percent}%"))

    started = time.monotonic()
    notes: list[str] = []
    job = new_job(data_dir(locale))
    try:
        def attempt(current: dict[str, Any], budget: float):
            (job / "spec.json").write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
            return _render(python, job, job / "mosael_explainer.py", "MosaelExplainer", options, locale, on_event,
                           timeout=budget, user_file="mosael_explainer.py")

        progress(send, 0.01, line(locale, "准备场景", "Preparing the scene"))
        try:
            produced, log = attempt(spec, RENDER_TIMEOUT)
        except LatexFailed as exc:
            # LaTeX 找得到却排不了(缺宏包之类):公式退成纯文字再试一次,总比整段视频出不来好
            remaining = RENDER_TIMEOUT - (time.monotonic() - started)
            if not (spec["use_latex"] and has_formulas(spec) and remaining > 20):
                raise
            spec = {**spec, "use_latex": False}
            notes.append(line(locale, f"LaTeX 排公式失败,公式改用纯文字显示({str(exc)[:200]})。",
                              f"LaTeX failed, so formulas are shown as plain text ({str(exc)[:200]})."))
            produced, log = attempt(spec, remaining)
        name = _deliver(produced, payload, "explainer", "mp4", locale)
        steps = timings(spec, log.markers)
        artifacts: list[dict[str, Any]] = [{"path": name, "media": "video"}]
        if payload.get("subtitles") is True and any(one.get("narration") for one in steps):
            srt_name = name.rsplit(".", 1)[0] + ".srt"
            (output_dir(locale) / srt_name).write_text(srt(steps), encoding="utf-8")
            # 具名输出:宿主把它的素材 id 填进 `subtitles` 那一格,工作流能直接接「那份字幕」,画板上落成它自己的一格
            artifacts.append({"path": srt_name, "media": "subtitles", "output": "subtitles"})
    finally:
        shutil.rmtree(job, ignore_errors=True)

    seconds = round(max((one["end"] for one in steps), default=0.0), 2)
    if has_formulas(spec) and not spec["use_latex"] and not notes:
        notes.append(line(locale, "本机没装 LaTeX,公式按纯文字显示(装了 LaTeX 后自动改用排版)。",
                          "LaTeX is not installed, so formulas are shown as plain text (typeset automatically once LaTeX is installed)."))
    summary = line(locale, f"讲解视频已生成:{seconds:g} 秒,{options.width}×{options.height}。",
                   f"Explainer rendered: {seconds:g}s, {options.width}×{options.height}.")
    return {
        "artifacts": artifacts,
        "seconds": seconds, "width": options.width, "height": options.height, "fps": options.fps,
        "latex": bool(spec["use_latex"]),
        "steps": steps,
        "notes": notes,
        "summary": " ".join([summary, *notes]),
    }


# ---------------------------------------------------------------- 自定义动画 / 静帧

def _animation_progress(send: Emit, locale: str):
    def on_event(kind: str, value: Any) -> None:
        if kind == "animation":
            index, name, percent = value
            done = index + percent / 100
            progress(send, 0.9 * (1 - 0.92 ** done), line(locale, f"动画 {index + 1}:{name[:60]} · {percent}%",
                                                           f"Animation {index + 1}: {name[:60]} · {percent}%"))
        elif kind == "marker" and value.get("kind") == "rendered":
            progress(send, 0.95, line(locale, "收尾", "Finishing"))
    return on_event


def _run_code(payload: dict[str, Any], locale: str, send: Emit, *, still: bool) -> tuple[Path, Any, Options, str]:
    code = str(payload.get("code") or "")
    unrestricted = os.environ.get("UNRESTRICTED_CODE", "").strip().lower() in TRUE
    checked = check(code, str(payload.get("scene") or ""), locale, unrestricted=unrestricted)
    options = resolve_options(payload, locale, still=still)
    python = render_python(locale)
    job = new_job(data_dir(locale))
    try:
        (job / "scene.py").write_text(code, encoding="utf-8")
        data = payload.get("data")
        (job / "data.json").write_text(json.dumps(data if isinstance(data, dict) else {}, ensure_ascii=False), encoding="utf-8")
        progress(send, 0.01, line(locale, f"渲染 {checked.scene}", f"Rendering {checked.scene}"))
        produced, log = _render(python, job, job / "scene.py", checked.scene, options, locale, _animation_progress(send, locale))
        name = _deliver(produced, payload, "frame" if still else "animation", options.extension, locale)
    finally:
        shutil.rmtree(job, ignore_errors=True)
    return produced, log, options, name


def manim_animation(payload: dict[str, Any], locale: str, send: Emit) -> dict[str, Any]:
    _, log, options, name = _run_code(payload, locale, send, still=False)
    seconds = next((round(float(one.get("time") or 0), 2) for one in reversed(log.markers) if one.get("kind") == "rendered"), None)
    summary = line(locale, f"动画已生成:{name}", f"Animation rendered: {name}") + (
        line(locale, f",{seconds:g} 秒", f", {seconds:g}s") if seconds else "")
    return {
        "artifact": {"path": name, "media": "video"},
        "seconds": seconds, "width": options.width, "height": options.height, "fps": options.fps,
        "format": options.format, "notes": list(options.notes),
        "summary": " ".join([summary, *options.notes]),
    }


def manim_still(payload: dict[str, Any], locale: str, send: Emit) -> dict[str, Any]:
    _, _, options, name = _run_code(payload, locale, send, still=True)
    return {
        "artifact": {"path": name, "media": "image"},
        "width": options.width, "height": options.height,
        "summary": line(locale, f"已渲染最后一帧:{name}", f"Rendered the last frame: {name}"),
    }


TOOLS = {"manim_setup": manim_setup, "manim_explainer": manim_explainer,
         "manim_animation": manim_animation, "manim_still": manim_still}


def main() -> None:
    locale = "zh"
    try:
        request = json.loads(sys.stdin.read() or "{}")
        locale = str(request.get("locale") or os.environ.get("MOSAEL_LOCALE") or "zh")
        tool = TOOLS.get(str(request.get("tool")))
        if tool is None:
            raise PluginError(line(locale, f"不认识的工具:{request.get('tool')}", f"Unknown tool: {request.get('tool')}"))
        output = tool(dict(request.get("input") or {}), locale, emit)
        emit({"ok": True, "output": output})
    except PluginError as exc:
        emit({"ok": False, "error": str(exc)})
    except Exception as exc:  # noqa: BLE001 —— 插件自己的 bug:交一句话回去,别只剩一个退出码
        import traceback

        traceback.print_exc(file=sys.stderr)
        emit({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    main()
