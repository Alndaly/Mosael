"""跑一次 `manim render`:拼参数、边读边报进度、看取消、找产出、把报错说成人话。"""

from __future__ import annotations

import json
import re
import shutil
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from manim_env import child_env, latex_hint
from plugin_kit import PluginError, TimedOut, blame_line, fresh_dir, follow, line, strip_ansi

HERE = Path(__file__).resolve().parent
KIT = HERE / "scene_kit"
#: 渲染子进程的上限。清单里给渲染工具声明了 170 秒(压在智能体单次调用 180 秒以内),
#: 这里留出收尾(搬文件、整理报错)的余量:超时时自己说一句人话,而不是被宿主直接掐掉。
RENDER_TIMEOUT = 150
MARKER = "MOSAEL_MANIM "

#: 画质 → (短边像素, 默认帧率)。讲解视频 30 帧足够,60 帧要多渲一倍。
QUALITIES = {"low": (480, 15), "medium": (720, 30), "high": (1080, 30), "production": (1440, 30), "4k": (2160, 30)}
FPS_CHOICES = (15, 24, 25, 30, 60)
ASPECTS = {"16:9": (16, 9), "9:16": (9, 16), "1:1": (1, 1), "4:3": (4, 3), "3:4": (3, 4)}
FORMATS = ("mp4", "webm", "mov", "gif")


@dataclass(frozen=True)
class Options:
    width: int
    height: int
    fps: int
    format: str
    transparent: bool = False
    still: bool = False
    notes: tuple[str, ...] = ()

    @property
    def extension(self) -> str:
        return "png" if self.still else self.format


def _even(value: float) -> int:
    number = int(round(value))
    return number + (number % 2)


def dimensions(aspect: str, quality: str) -> tuple[int, int]:
    """画幅 + 画质 → 像素。短边取画质的档位,长边按比例(取偶数:H.264 要求宽高是偶数)。"""
    short = QUALITIES[quality][0]
    a, b = ASPECTS[aspect]
    if a >= b:
        return _even(short * a / b), short
    return short, _even(short * b / a)


def resolve_options(payload: dict[str, Any], locale: str, *, still: bool = False, default_quality: str = "medium") -> Options:
    aspect = str(payload.get("aspect") or "16:9")
    if aspect not in ASPECTS:
        raise PluginError(line(locale, f"画幅只能是 {'、'.join(ASPECTS)}。", f"Aspect must be one of {', '.join(ASPECTS)}."))
    quality = str(payload.get("quality") or default_quality)
    if quality not in QUALITIES:
        raise PluginError(line(locale, f"画质只能是 {'、'.join(QUALITIES)}。", f"Quality must be one of {', '.join(QUALITIES)}."))
    width, height = dimensions(aspect, quality)
    try:
        fps = int(payload.get("fps") or QUALITIES[quality][1])
    except (TypeError, ValueError):
        fps = QUALITIES[quality][1]
    if fps not in FPS_CHOICES:
        raise PluginError(line(locale, f"帧率只能是 {'、'.join(map(str, FPS_CHOICES))}。", f"fps must be one of {', '.join(map(str, FPS_CHOICES))}."))
    transparent = payload.get("transparent") is True
    fmt = str(payload.get("format") or "mp4").lower()
    if fmt not in FORMATS:
        raise PluginError(line(locale, f"格式只能是 {'、'.join(FORMATS)}。", f"Format must be one of {', '.join(FORMATS)}."))
    notes: list[str] = []
    if transparent and not still:
        if fmt == "mp4":
            # mp4(H.264)没有透明通道;Manim 自己也会换成 mov,这里先说清楚
            fmt = "mov"
            notes.append(line(locale, "mp4 不支持透明背景,已改为 mov。", "mp4 has no alpha channel; rendered as mov instead."))
        elif fmt == "gif":
            raise PluginError(line(locale, "透明背景请用 mov 或 webm。", "Use mov or webm for a transparent background."))
    return Options(width=width, height=height, fps=fps, format=fmt, transparent=transparent, still=still, notes=tuple(notes))


def build_args(python: str, scene_file: Path, scene: str, media_dir: Path, options: Options) -> list[str]:
    """`manim render` 的命令行。经 mosael_runner 起(出错时多交一份结构化的原因)。

    - `--silent`:不在渲完之后去 PyPI 查新版本 —— 那是一次联网,而且渲染本身不该联网;
    - `--disable_caching`:每次都是新的工作目录,缓存用不上,算哈希反而多花时间;
    - `--verbosity WARNING`:INFO 日志按 80 列折行写在 stdout 上,既没用又挡路;进度条在 stderr 上照常出。
    """
    args = [
        python, str(scene_file.parent / "mosael_runner.py"), "render", str(scene_file), scene,
        "--media_dir", str(media_dir),
        "--resolution", f"{options.width},{options.height}",
        "--frame_rate", str(options.fps),
        "--renderer", "cairo",
        "--disable_caching", "--silent",
        "--verbosity", "WARNING",
        "--progress_bar", "display",
    ]
    if options.still:
        args += ["--save_last_frame", "--format", "png"]
    else:
        args += ["--format", options.format]
    if options.transparent:
        args.append("--transparent")
    return args


# ---------------------------------------------------------------- 工作目录

def new_job(data: Path) -> Path:
    """这一次渲染自己的目录:场景文件、数据、Manim 的中间产物都在这里,渲完即删。

    放在持久目录而不是系统临时目录:LaTeX 的中间文件、分段视频可能有几百 MB,临时目录在有的机器上很小。
    """
    job = fresh_dir(data / "jobs")
    for name in ("mosael_runner.py", "mosael_expr.py", "mosael_text.py", "mosael_explainer.py", "mosael.py"):
        shutil.copy2(KIT / name, job / name)
    return job


# ---------------------------------------------------------------- 进度

_ANIMATION = re.compile(r"Animation (\d+)\s*:\s*(.*?):\s*(\d+)%\|")


def parse_line(text: str) -> tuple[str, Any] | None:
    """stderr 的一行 → 事件。

    - `MOSAEL_MANIM {…}` → ("marker", 对象):场景 / runner 报的(段落开始结束、错误);
    - Manim 的进度条 `Animation 3: Write(Text('…')):  45%|…` → ("animation", (序号, 名字, 百分比))。
    """
    text = strip_ansi(text).strip()
    if text.startswith(MARKER):
        try:
            value = json.loads(text[len(MARKER):])
        except ValueError:
            return None
        return ("marker", value) if isinstance(value, dict) else None
    match = _ANIMATION.search(text)
    if match:
        return "animation", (int(match.group(1)), match.group(2).strip(), int(match.group(3)))
    return None


@dataclass
class RenderLog:
    markers: list[dict[str, Any]] = field(default_factory=list)
    error: dict[str, Any] | None = None
    tail: deque = field(default_factory=lambda: deque(maxlen=300))
    returncode: int = 0


def run(args: list[str], cwd: Path, locale: str, on_event: Callable[[str, Any], None], *,
        timeout: float = RENDER_TIMEOUT) -> RenderLog:
    """起 Manim,读到它退出为止。取消、超时都连同它起的 LaTeX 一起停(见 plugin_kit.follow)。"""
    log = RenderLog()

    def on_line(stream: str, text: str) -> None:
        event = parse_line(text) if stream == "err" else None
        if event is None:
            return
        kind, value = event
        if kind == "marker":
            if value.get("kind") == "error":
                log.error = value
            else:
                log.markers.append(value)
        on_event(kind, value)

    try:
        done = follow(args, locale=locale, timeout=timeout, cwd=cwd, env=child_env(), on_line=on_line)
    except TimedOut as exc:
        raise PluginError(line(
            locale,
            f"渲染超过 {timeout:g} 秒还没完成。降低画质(quality: low / medium)、减少步数或缩短时长,或者拆成几段分别渲染。",
            f"Rendering did not finish within {timeout:g}s. Lower the quality (low / medium), use fewer steps or split it into parts.",
        )) from exc
    log.tail, log.returncode = done.tail, done.returncode
    return log


def find_output(media_dir: Path, scene: str, options: Options) -> Path | None:
    """Manim 把成品放在 media/videos/<模块>/<分辨率帧率>/<场景>.<格式>(静帧在 media/images/…)。
    目录名随版本、画质变,所以按名字找,不拼路径。分段的中间文件(partial_movie_files)不算。"""
    if options.still:
        candidates = [one for one in media_dir.glob("images/**/*.png") if one.stem.startswith(scene)]
    else:
        candidates = [one for one in media_dir.glob(f"videos/**/{scene}.{options.extension}")
                      if "partial_movie_files" not in one.parts]
    candidates = [one for one in candidates if one.is_file() and one.stat().st_size > 0]
    return max(candidates, key=lambda one: one.stat().st_mtime) if candidates else None


# ---------------------------------------------------------------- 报错

def _latex_log_error(message: str) -> str:
    """LaTeX 编译失败时,Manim 的消息里带着日志路径;日志里以 `!` 开头的那行才是病因,`l.N` 那行是出错处。"""
    match = re.search(r"log file: (\S+\.log)", message)
    if not match:
        return ""
    try:
        log = Path(match.group(1)).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for index, text in enumerate(log):
        if text.startswith("!"):
            context = next((one for one in log[index:index + 12] if re.match(r"l\.\d+", one)), "")
            context = re.sub(r"^l\.\d+\s*", "", context).strip()
            return text[1:].strip() + (f"({context})" if context else "")
    return ""


class LatexFailed(PluginError):
    """公式排不了:没装 LaTeX、LaTeX 跑不起来、或者这条公式 LaTeX 报错。

    **分成一类是为了让调用方按类型接**:讲解视频遇到它就把公式退成纯文字再出一次。此前是在报错**文字**里找
    「LaTeX」—— 一个恰好提到 LaTeX 的无关失败(字体名、用户写的标题)也会白白再渲一遍,而措辞一改就认不出了。
    """


def _latex_cause(report: dict[str, Any]) -> str:
    """runner 交来的原因是不是 LaTeX 那一类:"missing" / "broken" / "formula",不是返回空串。"""
    message = str(report.get("message") or "")
    if report.get("type") == "FileNotFoundError" and re.search(r"'(latex|dvisvgm|xelatex|lualatex)'", message):
        return "missing"
    if "did not produce a log file" in message:
        return "broken"
    if "error converting to" in message:
        return "formula"
    return ""


def latex_failed(log: RenderLog) -> bool:
    return bool(log.error and _latex_cause(log.error))


def explain_failure(log: RenderLog, job: Path, user_file: str, locale: str) -> str:
    """把一次失败的渲染说成**改得动**的一句话。

    有 runner 交来的结构化原因时:LaTeX 的几种失败各说各的下一步;别的异常找出**用户代码里**最深的那一帧,
    说「第几行 `那行代码`:异常类型: 消息」。没有(Manim 本身都没起来)时从输出里挑最像原因的那一行 ——
    不取尾巴:最后一行常常是一根进度条或 rich 画的边框。
    """
    report = log.error
    if report:
        kind = str(report.get("type") or "Error")
        message = _clean_paths(str(report.get("message") or ""), job)
        raw_message = str(report.get("message") or "")
        cause = _latex_cause(report)
        if cause == "missing":
            return line(locale, "没装 LaTeX,MathTex / Tex 排不了公式。", "LaTeX is not installed, so MathTex / Tex cannot typeset. ") \
                + latex_hint(locale) + line(locale, " 不装的话:公式改用 Text 写。", " Without it, write formulas with Text instead.")
        if cause == "broken":
            return line(locale, "LaTeX 没能运行(装得不完整?)。", "LaTeX failed to run (incomplete install?). ") + latex_hint(locale)
        if cause == "formula":
            detail = _latex_log_error(raw_message)
            return line(locale, "公式排版失败(LaTeX 报错):", "Formula typesetting failed (LaTeX error): ") + (detail or message)
        frames = [one for one in report.get("frames") or [] if Path(str(one.get("file") or "")).name == user_file]
        if frames:
            frame = frames[-1]
            where = line(locale, f"第 {frame.get('line')} 行", f"Line {frame.get('line')}")
            code = str(frame.get("code") or "").strip()
            return f"{where}" + (f" `{code}`" if code else "") + f":{kind}: {message}"
        return f"{kind}: {message}"
    text = _clean_paths("\n".join(log.tail), job)
    reason = blame_line(text, fallback="")
    return reason or line(locale, f"Manim 退出码 {log.returncode},没有说原因。", f"Manim exited with code {log.returncode} and gave no reason.")


def _clean_paths(text: str, job: Path) -> str:
    """绝对路径换成相对的:读得懂,也不把用户目录抖出去(两种写法都换 —— macOS 上 /tmp 是 /private/tmp)。"""
    for base in sorted({str(job), str(job.resolve())}, key=len, reverse=True):
        text = text.replace(base + "/", "").replace(base + "\\", "").replace(base, ".")
    return text[:1500]
