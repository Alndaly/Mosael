"""跑一次 `manim render`:拼参数、边读边报进度、看取消、找产出、把报错说成人话。"""

from __future__ import annotations

import codecs
import json
import re
import shutil
import subprocess
import threading
import time
import queue
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from manim_common import Cancelled, PluginError, blame_line, cancel_requested, line, strip_ansi
from manim_env import _group_kwargs, child_env, latex_hint, stop

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
    顺手清掉一天以前的残留(进程被强杀时来不及删)。
    """
    jobs = data / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - 86400
    for old in jobs.iterdir():
        try:
            if old.is_dir() and old.stat().st_mtime < cutoff:
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            pass
    job = jobs / uuid.uuid4().hex[:12]
    job.mkdir()
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
    """起 Manim,读到它退出为止。看到取消文件就停下它(连同 latex 之类的子进程),超时同样停下。"""
    process = subprocess.Popen(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                               env=child_env(), **_group_kwargs())
    log = RenderLog()
    lines: queue.Queue = queue.Queue()

    def pump(stream, name: str) -> None:
        # 进度条用 `\r` 原地重画,按行读会一直读不到换行 —— 所以按块读,`\r` 和 `\n` 都算分隔。
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        buffer = ""
        while True:
            chunk = stream.read1(4096) if hasattr(stream, "read1") else stream.read(4096)
            if not chunk:
                break
            buffer += decoder.decode(chunk)
            parts = re.split(r"[\r\n]", buffer)
            buffer = parts.pop()
            for part in parts:
                if part.strip():
                    lines.put((name, part))
        buffer += decoder.decode(b"", final=True)
        if buffer.strip():
            lines.put((name, buffer))
        lines.put((name, None))

    readers = [threading.Thread(target=pump, args=(process.stderr, "err"), daemon=True),
               threading.Thread(target=pump, args=(process.stdout, "out"), daemon=True)]
    for reader in readers:
        reader.start()
    deadline = time.monotonic() + timeout
    open_streams = 2
    while open_streams:
        try:
            name, text = lines.get(timeout=0.25)
        except queue.Empty:
            name, text = "", ""
        if text is None:
            open_streams -= 1
        elif text:
            log.tail.append(text)
            event = parse_line(text) if name == "err" else None
            if event is not None:
                kind, value = event
                if kind == "marker":
                    if value.get("kind") == "error":
                        log.error = value
                    else:
                        log.markers.append(value)
                on_event(kind, value)
        if cancel_requested():
            stop(process)
            raise Cancelled(line(locale, "已取消。", "Cancelled."))
        if time.monotonic() > deadline:
            stop(process)
            raise PluginError(line(
                locale,
                f"渲染超过 {timeout:g} 秒还没完成。降低画质(quality: low / medium)、减少步数或缩短时长,或者拆成几段分别渲染。",
                f"Rendering did not finish within {timeout:g}s. Lower the quality (low / medium), use fewer steps or split it into parts.",
            ))
    process.wait()
    log.returncode = process.returncode
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
        if kind == "FileNotFoundError" and re.search(r"'(latex|dvisvgm|xelatex|lualatex)'", raw_message):
            return line(locale, "没装 LaTeX,MathTex / Tex 排不了公式。", "LaTeX is not installed, so MathTex / Tex cannot typeset. ") \
                + latex_hint(locale) + line(locale, " 不装的话:公式改用 Text 写。", " Without it, write formulas with Text instead.")
        if "did not produce a log file" in raw_message:
            return line(locale, "LaTeX 没能运行(装得不完整?)。", "LaTeX failed to run (incomplete install?). ") + latex_hint(locale)
        if "error converting to" in raw_message:
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
