"""Manim 插件:不装 Manim 也能验的那些。

真渲染要装三百多 MB(Manim、scipy、PyAV…),macOS / Linux 上还要编译 pycairo,不适合每次 CI 都跑;
那一半在本机用真的 Manim 0.21 跑过(准备环境 → 讲解视频横竖屏 → 自定义动画 → 静帧 → 报错 → 取消),
记在提交里。这里钉的是:

- 讲解视频的内容**从不拼进代码**:结构 → spec 的校验、截断、时长、危险 LaTeX、函数表达式(不经 eval);
- 命令行怎么拼、进度怎么读、报错怎么说成「第几行哪句代码」;
- 自定义代码的护栏;
- 用一个**假的 Manim**(一个冒充 Python 的脚本)跑通入口:产出交回、进度流出来、取消真的停下子进程。
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "examples" / "manim"
TOOLS = PLUGIN / "tools"

sys.path.insert(0, str(TOOLS))
try:
    import plugin_kit
    import manim_env
    import manim_explainer as ex
    import manim_guard as guard
    import manim_render as render
    from scene_kit import mosael_expr as expr
    from scene_kit import mosael_text as mtext
finally:
    sys.path.remove(str(TOOLS))

PluginError = plugin_kit.PluginError


# ---------------------------------------------------------------- 函数表达式:只认算式

class Test函数表达式:
    def test_常见写法都认(self) -> None:
        assert expr.normalize("y = 2x^2 + 3(x+1)") == "2*x**2 + 3*(x+1)"
        assert expr.normalize("f(x) = 2pi·x") == "2*pi*x"
        assert expr.normalize("log10(x) + log2(x)") == "log10(x) + log2(x)", "log10 里的 10 不是系数"
        f = expr.compile_function("sin(x) + x^2/8")
        assert f(0) == pytest.approx(0.0) and f(2) == pytest.approx(0.9093 + 0.5, abs=1e-3)

    @pytest.mark.parametrize("bad", [
        "__import__('os').system('echo hi')", "x.__class__", "(lambda: 1)()", "'a' * 3", "open('x')",
        "[x for x in range(3)]", "y", "x if x else 1", "sin(x, y=1)", "True + x",
    ])
    def test_代码进不来(self, bad: str) -> None:
        with pytest.raises(expr.ExpressionError):
            expr.parse(bad)

    def test_定义域外和溢出给None_不抛(self) -> None:
        f = expr.compile_function("log(x)")
        assert f(-1) is None and f(0) is None
        started = time.monotonic()
        assert expr.compile_function("10^10^10")(1) is None
        assert time.monotonic() - started < 1, "指数塔不能真的去算一个十亿位的整数"
        assert expr.compile_function("(-8)^(1/3)")(0) is None, "复数结果也当没定义"

    def test_渐近线两侧断开_y范围不被一个点撑爆(self) -> None:
        points = expr.sample(expr.compile_function("1/x"), -2, 2, 401)
        low, high = expr.auto_y_range(points)
        runs = expr.segments(points, low, high)
        assert len(runs) == 2 and all(x < 0 for x, _ in runs[0]) and all(x > 0 for x, _ in runs[1])
        low, high = expr.auto_y_range(expr.sample(expr.compile_function("tan(x)"), -3, 3, 600))
        assert high - low < 200

    def test_刻度取整数间隔(self) -> None:
        assert expr.nice_step(-5, 5) == 2 and expr.nice_step(0, 1) == 0.2 and expr.nice_step(0, 300) == 50
        assert expr.ticks(-5, 5, 2) == [-4, -2, 0, 2, 4]
        assert expr.format_tick(2.0) == "2" and expr.format_tick(0.5) == "0.5"


# ---------------------------------------------------------------- 文字

class Test文字:
    def test_按显示宽度折行_英文不从词中间断(self) -> None:
        lines = mtext.wrap("勾股定理说的是直角三角形两条直角边的平方和等于斜边的平方", 20)
        assert all(mtext.display_width(one) <= 20 for one in lines) and "".join(lines).startswith("勾股定理")
        lines = mtext.wrap("The quick brown fox jumps over the lazy dog", 16)
        assert all(len(one) <= 16 for one in lines) and " ".join(lines) == "The quick brown fox jumps over the lazy dog"

    def test_标点不落到行首(self) -> None:
        lines = mtext.wrap("一二三四五六七八九十。十一", 20)
        assert not any(one.startswith("。") for one in lines)

    @pytest.mark.parametrize(("latex", "plain"), [
        (r"a^2 + b^2 = c^2", "a² + b² = c²"),
        (r"\frac{-b \pm \sqrt{b^2-4ac}}{2a}", "(-b ± √(b²-4ac))/(2a)"),
        (r"x_{n+1} = x_n", "xₙ₊₁ = xₙ"),
        (r"\int_0^1 x^2\,dx = \frac{1}{3}", "∫₀¹ x² dx = 1/3"),
        (r"e^{i\pi} + 1 = 0", "e^(iπ) + 1 = 0"),
    ])
    def test_没有LaTeX时公式写成一行Unicode(self, latex: str, plain: str) -> None:
        assert mtext.latex_to_plain(latex) == plain

    def test_朗读时长(self) -> None:
        assert mtext.reading_seconds("一" * 45) == pytest.approx(10.0)
        assert mtext.reading_seconds("one two three four five") == pytest.approx(2.0)


# ---------------------------------------------------------------- 讲解视频的 spec

def _payload(**steps_and_more) -> dict:
    return {"title": "勾股定理", "steps": [{"title": "定理"}], **steps_and_more}


class Test讲解视频的内容:
    def test_标题和至少一步是必须的(self) -> None:
        with pytest.raises(PluginError, match="标题"):
            ex.build_spec({"steps": [{"title": "a"}]}, "zh", use_latex=False)
        with pytest.raises(PluginError, match="至少要有一步"):
            ex.build_spec({"title": "t", "steps": []}, "zh", use_latex=False)
        with pytest.raises(PluginError, match="第 2 步缺标题"):
            ex.build_spec({"title": "t", "steps": [{"title": "a"}, {"narration": "x"}]}, "zh", use_latex=False)
        with pytest.raises(PluginError, match="最多 20 步"):
            ex.build_spec({"title": "t", "steps": [{"title": "a"}] * 21}, "zh", use_latex=False)

    def test_一段文字原样进JSON_场景源码里没有它(self) -> None:
        """内容走 JSON,不拼进 Python:引号、三引号、反斜杠、换行、花括号都原样到场景手里。"""
        nasty = 'x"""; import os; os.system("rm -rf ~") #\'\\n{0}\n第二行'
        spec = ex.build_spec(_payload(steps=[{"title": nasty[:80], "narration": nasty, "bullets": [nasty]}]), "zh", use_latex=False)
        round_trip = json.loads(json.dumps(spec, ensure_ascii=False))
        step = round_trip["segments"][1]
        assert step["narration"] == re.sub(r"[ \t]+", " ", nasty).strip() and step["bullets"][0].startswith('x""";')
        scene = (TOOLS / "scene_kit" / "mosael_explainer.py").read_text(encoding="utf-8")
        assert "rm -rf" not in scene and 'Path(__file__).with_name("spec.json")' in scene
        assert "eval(" not in scene and "exec(" not in scene

    def test_一步只放一样视觉(self) -> None:
        with pytest.raises(PluginError, match="三选一"):
            ex.build_spec(_payload(steps=[{"title": "a", "formulas": ["x"], "code": {"code": "print(1)"}}]), "zh", use_latex=True)

    @pytest.mark.parametrize("formula", [r"\input{/etc/passwd}", r"\immediate\write18{ls}", r"\def\x{1}", r"\usepackage{shellesc}", r"\csname x\endcsname"])
    def test_读写文件和定义命令的LaTeX挡在门外(self, formula: str) -> None:
        with pytest.raises(PluginError, match="不能用"):
            ex.build_spec(_payload(steps=[{"title": "a", "formulas": [formula]}]), "zh", use_latex=True)

    def test_正常公式放行_花括号要配平(self) -> None:
        spec = ex.build_spec(_payload(steps=[{"title": "a", "formulas": [r"\frac{a}{b} = \left\{ x \right\}", r"\sqrt{2}"]}]), "zh", use_latex=True)
        assert spec["segments"][1]["formulas"][0].startswith(r"\frac") and spec["use_latex"] is True
        assert ex.has_formulas(spec)
        with pytest.raises(PluginError, match="没配平"):
            ex.build_spec(_payload(steps=[{"title": "a", "formula": r"\frac{a}{b"}]), "zh", use_latex=True)

    def test_没有LaTeX时照样出spec_由场景写成纯文字(self) -> None:
        spec = ex.build_spec(_payload(steps=[{"title": "a", "formula": "a^2+b^2=c^2"}]), "en", use_latex=False)
        assert spec["use_latex"] is False and spec["segments"][1]["formulas"] == ["a^2+b^2=c^2"]

    def test_函数图_算好范围和刻度_默认标签好读(self) -> None:
        spec = ex.build_spec(_payload(steps=[{"title": "a", "plot": {"expression": "x^2", "x_min": -3, "x_max": 3}}]), "zh", use_latex=False)
        plot = spec["segments"][1]["plot"]
        assert plot["x_range"] == [-3, 3] and plot["y_range"][0] < 0.1 and plot["y_range"][1] > 8
        assert plot["label"] == "y = x²" and plot["x_step"] == 1
        with pytest.raises(PluginError, match="第 1 步:不能调用「__import__」"):
            ex.build_spec(_payload(steps=[{"title": "a", "plot": {"expression": "__import__('os')"}}]), "zh", use_latex=False)
        with pytest.raises(PluginError, match="没有定义"):
            ex.build_spec(_payload(steps=[{"title": "a", "plot": {"expression": "log(x)", "x_min": -5, "x_max": -1}}]), "zh", use_latex=False)

    def test_代码高亮_行号与区间(self) -> None:
        code = "\n".join(f"line{i}" for i in range(1, 9))
        spec = ex.build_spec(_payload(steps=[{"title": "a", "code": {"code": code, "highlight": [2, "4-6", "7–9"]}}]), "zh", use_latex=False)
        assert spec["segments"][1]["code"]["highlight"] == [[2, 2], [4, 6], [7, 8]]
        with pytest.raises(PluginError, match="高亮不到第 12 行"):
            ex.build_spec(_payload(steps=[{"title": "a", "code": {"code": code, "highlight": [12]}}]), "zh", use_latex=False)
        with pytest.raises(PluginError, match="最多 30 行"):
            ex.build_spec(_payload(steps=[{"title": "a", "code": "x\n" * 40}]), "zh", use_latex=False)

    def test_时长跟着旁白走_不短于动画本身(self) -> None:
        narration = "一" * 45  # 约 10 秒
        spec = ex.build_spec(_payload(steps=[
            {"title": "a", "narration": narration},
            {"title": "b", "bullets": ["x"] * 6, "seconds": 1},
        ]), "zh", use_latex=False)
        first, second = spec["segments"][1], spec["segments"][2]
        assert first["seconds"] == pytest.approx(11.0)
        assert second["seconds"] >= ex.step_minimum(second, True) and second["seconds"] > 1

    def test_主题与强调色(self) -> None:
        spec = ex.build_spec(_payload(theme="light", accent="e4572e"), "zh", use_latex=False)
        assert spec["colors"]["accent"] == "#E4572E" and spec["colors"]["background"] == ex.THEMES["light"]["background"]
        with pytest.raises(PluginError, match="#RRGGBB"):
            ex.build_spec(_payload(accent="red"), "zh", use_latex=False)

    def test_要点回顾跟语言走(self) -> None:
        spec = ex.build_spec(_payload(summary=["a", "b"]), "en", use_latex=False)
        assert spec["segments"][-1] == {**spec["segments"][-1], "kind": "summary", "title": "Key takeaways", "points": ["a", "b"]}

    def test_实际起止时间与字幕(self) -> None:
        spec = ex.build_spec(_payload(steps=[{"title": "a", "narration": "第一句。第二句要长一点。"}]), "zh", use_latex=False)
        markers = [{"kind": "segment", "index": 0, "time": 0}, {"kind": "segment_end", "index": 0, "time": 4},
                   {"kind": "segment", "index": 1, "time": 4}, {"kind": "segment_end", "index": 1, "time": 10}]
        steps = ex.timings(spec, markers)
        assert steps[1] == {"kind": "step", "title": "a", "start": 4.0, "end": 10.0, "step": 1, "narration": "第一句。第二句要长一点。"}
        subtitles = ex.srt(steps)
        assert subtitles.startswith("1\n00:00:04,000 --> 00:00:06,000\n第一句。\n\n2\n00:00:06,000 --> 00:00:10,000\n第二句")


# ---------------------------------------------------------------- 命令行、进度、报错

class Test命令行:
    def test_画幅加画质给出偶数像素(self) -> None:
        assert render.dimensions("16:9", "low") == (854, 480)
        assert render.dimensions("16:9", "high") == (1920, 1080)
        assert render.dimensions("9:16", "medium") == (720, 1280)
        assert render.dimensions("1:1", "4k") == (2160, 2160)

    def test_选项校验_透明mp4改成mov(self) -> None:
        options = render.resolve_options({"transparent": True}, "zh")
        assert options.format == "mov" and options.notes and options.fps == 30
        assert render.resolve_options({"quality": "low"}, "zh").fps == 15
        with pytest.raises(PluginError, match="mov 或 webm"):
            render.resolve_options({"transparent": True, "format": "gif"}, "zh")
        for bad in ({"aspect": "2:1"}, {"quality": "ultra"}, {"fps": 12}, {"format": "avi"}):
            with pytest.raises(PluginError):
                render.resolve_options(bad, "zh")

    def test_参数(self, tmp_path: Path) -> None:
        options = render.resolve_options({"quality": "high", "fps": 60}, "zh")
        args = render.build_args("/py", tmp_path / "scene.py", "Demo", tmp_path / "media", options)
        assert args[:5] == ["/py", str(tmp_path / "mosael_runner.py"), "render", str(tmp_path / "scene.py"), "Demo"]
        joined = " ".join(args)
        for flag in ("--resolution 1920,1080", "--frame_rate 60", "--format mp4", "--disable_caching", "--silent",
                     "--renderer cairo", "--verbosity WARNING"):
            assert flag in joined, flag
        still = render.build_args("/py", tmp_path / "s.py", "D", tmp_path, render.resolve_options({"transparent": True}, "zh", still=True))
        assert "--save_last_frame" in still and "--transparent" in still and still[still.index("--format") + 1] == "png"


class Test进度:
    def test_读进度条与标记(self) -> None:
        bar = "\x1b[32mAnimation 3: Write(Text('你好')):  45%|████▌     | 9/20 [00:00<00:00, 25.0it/s]"
        assert render.parse_line(bar) == ("animation", (3, "Write(Text('你好'))", 45))
        assert render.parse_line('MOSAEL_MANIM {"kind": "segment", "index": 2}') == ("marker", {"kind": "segment", "index": 2})
        assert render.parse_line("MOSAEL_MANIM not json") is None and render.parse_line("random log") is None

    def test_重复的进度不再报(self) -> None:
        sent: list = []
        plugin_kit._last_progress[0] = None
        for _ in range(3):
            plugin_kit.progress(sent.append, 0.5, "x")
        plugin_kit.progress(sent.append, 0.6, "x")
        assert len(sent) == 2


class Test报错:
    def test_用户代码第几行哪句(self, tmp_path: Path) -> None:
        log = render.RenderLog(error={"type": "NameError", "message": "name 'Swapp' is not defined", "frames": [
            {"file": "/venv/manim/scene/scene.py", "line": 259, "code": "self.construct()"},
            {"file": str(tmp_path / "scene.py"), "line": 12, "code": "self.play(Swapp(a, b))"},
            {"file": "/venv/manim/animation/x.py", "line": 3, "code": "..."},
        ]}, returncode=1)
        assert render.explain_failure(log, tmp_path, "scene.py", "zh") == "第 12 行 `self.play(Swapp(a, b))`:NameError: name 'Swapp' is not defined"

    def test_没装LaTeX说怎么装(self, tmp_path: Path) -> None:
        log = render.RenderLog(error={"type": "FileNotFoundError", "message": "[Errno 2] No such file or directory: 'latex'", "frames": []})
        message = render.explain_failure(log, tmp_path, "scene.py", "zh")
        assert "没装 LaTeX" in message and ("MacTeX" in message or "MiKTeX" in message or "TeX Live" in message)

    def test_LaTeX报错取日志里感叹号那行(self, tmp_path: Path) -> None:
        tex_log = tmp_path / "media" / "Tex" / "abc.log"
        tex_log.parent.mkdir(parents=True)
        tex_log.write_text("This is pdfTeX\n! Undefined control sequence.\nl.8 \\fracc\n             {1}{2}\n", encoding="utf-8")
        log = render.RenderLog(error={"type": "ValueError", "frames": [],
                                      "message": f"latex error converting to dvi. See log output above or the log file: {tex_log}"})
        message = render.explain_failure(log, tmp_path, "scene.py", "zh")
        assert message == "公式排版失败(LaTeX 报错):Undefined control sequence.(\\fracc)"

    def test_没有结构化原因时不取尾巴(self, tmp_path: Path) -> None:
        log = render.RenderLog(returncode=1)
        log.tail.extend([f"File \"{tmp_path}/scene.py\", line 3", "ModuleNotFoundError: No module named 'cairo'",
                         "Animation 0: Write(x):  10%|█  | 1/10 [00:00<00:01]", "╰──────────╯"])
        assert render.explain_failure(log, tmp_path, "scene.py", "en") == "ModuleNotFoundError: No module named 'cairo'"

    def test_绝对路径换成相对的(self, tmp_path: Path) -> None:
        log = render.RenderLog(error={"type": "OSError", "message": f"cannot read {tmp_path}/media/x.svg", "frames": []})
        assert str(tmp_path) not in render.explain_failure(log, tmp_path, "scene.py", "en")


# ---------------------------------------------------------------- 自定义代码的护栏

SCENE = "from manim import *\n\nclass Demo(Scene):\n    def construct(self):\n        self.play(Create(Circle()))\n"


class Test自定义代码:
    def test_语法错误说第几行第几列(self) -> None:
        with pytest.raises(PluginError, match="第 2 行第 .* 列语法错误"):
            guard.check("from manim import *\nclass A(Scene)\n    pass\n", "", "zh")

    def test_场景类(self) -> None:
        with pytest.raises(PluginError, match="没有场景类"):
            guard.check("x = 1\n", "", "zh")
        two = SCENE + "\nclass Base(MovingCameraScene):\n    pass\n\nclass Child(Base):\n    pass\n"
        assert guard.scene_classes(__import__("ast").parse(two)) == ["Demo", "Base", "Child"]
        with pytest.raises(PluginError, match="用 scene 指定"):
            guard.check(two, "", "zh")
        with pytest.raises(PluginError, match="找不到场景「Nope」"):
            guard.check(two, "Nope", "zh")
        assert guard.check(two, "Child", "zh").scene == "Child"
        assert guard.check(SCENE, "", "zh").scene == "Demo"

    @pytest.mark.parametrize("snippet", [
        "import os", "import subprocess as sp", "from pathlib import Path", "open('/etc/passwd')",
        "__import__('os')", "eval('1')", "np.save('x', 1)", "().__class__.__bases__", "getattr(self, 'x')",
        "from . import x",
        # 不经 open 也能读文件的那几条路:把本机文件渲进画面(静帧会交回一张图)
        "Code(code_file='/Users/me/.ssh/id_rsa')", "SVGMobject('/etc/hosts')", "ImageMobject('~/Pictures/id.png')",
        r"MathTex(r'\input{/etc/passwd}')", r"Tex('\\openin5=/etc/passwd')",
        "np.lib.format.open_memmap('x', mode='w+')", "nx.write_edgelist(g, 'x')", "nx.read_gml('x')",
        "scipy.io.wavfile.write('x', 1, a)",
    ])
    def test_越界的写法挡住并说第几行(self, snippet: str) -> None:
        code = SCENE + f"\nX = 1\n{snippet}\n"
        with pytest.raises(PluginError, match="第 8 行"):
            guard.check(code, "", "zh")

    def test_画图的日常写法都放行(self) -> None:
        code = textwrap.dedent("""
            from manim import *
            import numpy as np
            from mosael import DATA
            import math, random

            class Base(Scene):
                def __init__(self, **kwargs):
                    super().__init__(**kwargs)

            class Demo(Base):
                def construct(self):
                    dot = Dot()
                    self.add(dot)
                    self.remove(dot)
                    label = "a-b".replace("-", "+")
                    self.play(Create(Circle(radius=math.sqrt(2))), run_time=np.pi / 3)
        """)
        assert guard.check(code, "Demo", "zh").scene == "Demo"

    def test_打开不限制之后不查(self) -> None:
        code = SCENE + "\nimport os\n"
        assert guard.check(code, "", "zh", unrestricted=True).scene == "Demo"


# ---------------------------------------------------------------- 假 Manim 跑通入口

FAKE_PYTHON = r'''#!{python}
"""冒充「装了 Manim 的 Python」:认 `-c <探测>` 和 `<runner> render <场景文件> <场景> …`。"""
import json, os, sys, time
from pathlib import Path

args = sys.argv[1:]
if args[:1] == ["-c"]:
    print(json.dumps({{"python": "3.13.0", "manim": "0.21.0"}}))
    sys.exit(0)
scene_file, scene = Path(args[2]), args[3]
media = Path(args[args.index("--media_dir") + 1])
fmt = args[args.index("--format") + 1]
source = scene_file.read_text(encoding="utf-8")
def say(**fields):
    sys.stderr.write("MOSAEL_MANIM " + json.dumps(fields) + "\n"); sys.stderr.flush()
if "SLOW" in source:
    (media.parent / "fake.pid").write_text(str(os.getpid()))
    for i in range(600):
        sys.stderr.write(f"Animation {{i}}: Wait(1.0):  50%|#   | 1/2 [00:00<00:00]\r"); sys.stderr.flush()
        time.sleep(0.1)
if "BOOM" in source:
    say(kind="error", type="ZeroDivisionError", message="division by zero",
        frames=[{{"file": str(scene_file), "line": 6, "name": "construct", "code": "x = 1 / 0  # BOOM"}}])
    sys.exit(1)
if scene == "MosaelExplainer":
    spec = json.loads((scene_file.parent / "spec.json").read_text(encoding="utf-8"))
    attempts = scene_file.parent.parent.parent / "attempts.log"
    with attempts.open("a") as handle:
        handle.write(("latex" if spec["use_latex"] else "plain") + "\n")
    if spec["segments"][0]["title"] == "CRASH":
        say(kind="error", type="RuntimeError", message="font 'LaTeX Sans' not found", frames=[])
        sys.exit(1)
    if spec["use_latex"] and any(part.get("formulas") for part in spec["segments"]):
        if "BADTEX" in json.dumps(spec):
            log = scene_file.parent / "media" / "Tex" / "x.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text("! Undefined control sequence.\nl.8 \\badtex\n", encoding="utf-8")
            say(kind="error", type="ValueError", message=f"latex error converting to dvi. See log output above or the log file: {{log}}", frames=[])
        else:
            say(kind="error", type="FileNotFoundError", message="[Errno 2] No such file or directory: 'dvisvgm'", frames=[])
        sys.exit(1)
    now = 0.0
    for index, part in enumerate(spec["segments"]):
        say(kind="segment", index=index, total=len(spec["segments"]), part=part["kind"], title=part.get("title", ""), time=now)
        sys.stderr.write(f"Animation {{index}}: FadeIn(Text):  40%|####  | 4/10 [00:00<00:00]\r")
        now += part["seconds"]
        say(kind="segment_end", index=index, time=now)
    say(kind="done", time=now)
if fmt == "png":
    target = media / "images" / scene_file.stem / f"{{scene}}_ManimCE_v0.21.0.png"
else:
    target = media / "videos" / scene_file.stem / "720p30" / f"{{scene}}.{{fmt}}"
    partial = media / "videos" / scene_file.stem / "720p30" / "partial_movie_files" / scene / f"{{scene}}.{{fmt}}"
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_bytes(b"partial")
target.parent.mkdir(parents=True, exist_ok=True)
target.write_bytes(b"fake-" + fmt.encode())
say(kind="rendered", time=2.5)
'''

pytestmark_posix = pytest.mark.skipif(sys.platform == "win32", reason="假 Python 靠 shebang 起")


@pytest.fixture()
def fake_env(tmp_path: Path) -> dict[str, str]:
    fake = tmp_path / "fakepython"
    fake.write_text(FAKE_PYTHON.format(python=sys.executable), encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    for name in ("data", "out"):
        (tmp_path / name).mkdir()
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "MOSAEL_PLUGIN_DATA_DIR": str(tmp_path / "data"),
        "MOSAEL_PLUGIN_OUTPUT_DIR": str(tmp_path / "out"),
        "MOSAEL_PLUGIN_CANCEL_FILE": str(tmp_path / "cancel"),
        "PYTHON_EXECUTABLE": str(fake),
    }


def _call(tool: str, payload: dict, env: dict[str, str], locale: str = "zh") -> tuple[dict, list[dict]]:
    done = subprocess.run([sys.executable, str(TOOLS / "main.py")], input=json.dumps({"tool": tool, "input": payload, "locale": locale}),
                          capture_output=True, text=True, timeout=60, env=env)
    lines = [json.loads(one) for one in done.stdout.splitlines() if one.strip()]
    return lines[-1], [one for one in lines if one.get("event") == "progress"]


@pytestmark_posix
class Test入口:
    def test_讲解视频_产出与每步时间与字幕(self, fake_env: dict[str, str]) -> None:
        payload = {"title": "勾股定理", "subtitles": True, "filename": "lesson",
                   "steps": [{"title": "定理", "narration": "两条直角边的平方和等于斜边的平方。", "formula": "a^2+b^2=c^2"},
                             {"title": "图像", "plot": {"expression": "x^2"}}]}
        final, progress = _call("manim_explainer", payload, fake_env)
        assert final["ok"] is True, final
        output = final["output"]
        assert output["artifacts"] == [{"path": "lesson.mp4", "media": "video"}, {"path": "lesson.srt", "media": "subtitles", "output": "subtitles"}]
        out = Path(fake_env["MOSAEL_PLUGIN_OUTPUT_DIR"])
        assert (out / "lesson.mp4").read_bytes() == b"fake-mp4" and "两条直角边" in (out / "lesson.srt").read_text(encoding="utf-8")
        assert [one["kind"] for one in output["steps"]] == ["title", "step", "step"]
        assert output["steps"][1]["start"] == output["steps"][0]["end"] > 0
        assert (output["width"], output["height"]) == (1280, 720)
        assert any("第 2/3 段" in one["message"] for one in progress)
        assert not list((Path(fake_env["MOSAEL_PLUGIN_DATA_DIR"]) / "jobs").iterdir()), "工作目录渲完即删"

    @pytest.fixture()
    def with_latex(self, fake_env: dict[str, str], tmp_path: Path) -> dict[str, str]:
        """PATH 上放一对假的 latex / dvisvgm:插件据此认为 LaTeX 在,讲解视频先按排版公式去渲。"""
        bin_dir = tmp_path / "texbin"
        bin_dir.mkdir()
        for name in ("latex", "dvisvgm"):
            (bin_dir / name).write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            (bin_dir / name).chmod(0o755)
        return {**fake_env, "PATH": f"{bin_dir}:{fake_env['PATH']}"}

    def _attempts(self, env: dict[str, str]) -> list[str]:
        return (Path(env["MOSAEL_PLUGIN_DATA_DIR"]) / "attempts.log").read_text().split()

    @pytest.mark.parametrize("formula", ["a^2+b^2=c^2", "BADTEX"])
    def test_LaTeX排不了公式时退成纯文字再出一次(self, with_latex: dict[str, str], formula: str) -> None:
        final, _ = _call("manim_explainer", {"title": "勾股定理", "steps": [{"title": "定理", "formula": formula}]}, with_latex)
        assert final["ok"] is True, final
        assert final["output"]["latex"] is False and "纯文字" in final["output"]["summary"]
        assert self._attempts(with_latex) == ["latex", "plain"]

    def test_不是LaTeX的失败不重试_哪怕报错里写着LaTeX(self, with_latex: dict[str, str]) -> None:
        """此前按报错文字里有没有「LaTeX」判断要不要退成纯文字 —— 一个恰好提到 LaTeX 的无关失败会白白再渲一遍。"""
        final, _ = _call("manim_explainer", {"title": "CRASH", "steps": [{"title": "a", "formula": "x^2"}]}, with_latex)
        assert final["ok"] is False and "LaTeX Sans" in final["error"]
        assert self._attempts(with_latex) == ["latex"]

    def test_自定义动画_数据与格式(self, fake_env: dict[str, str]) -> None:
        final, _ = _call("manim_animation", {"code": SCENE, "format": "webm", "filename": "circle.webm", "data": {"n": 3}}, fake_env)
        assert final["ok"] is True, final
        assert final["output"]["artifact"] == {"path": "circle.webm", "media": "video"} and final["output"]["seconds"] == 2.5
        assert (Path(fake_env["MOSAEL_PLUGIN_OUTPUT_DIR"]) / "circle.webm").read_bytes() == b"fake-webm"

    def test_静帧(self, fake_env: dict[str, str]) -> None:
        final, _ = _call("manim_still", {"code": SCENE, "transparent": True}, fake_env)
        assert final["ok"] is True and final["output"]["artifact"] == {"path": "frame.png", "media": "image"}

    def test_报错指出用户代码的那一行(self, fake_env: dict[str, str]) -> None:
        code = SCENE + "        x = 1 / 0  # BOOM\n"
        final, _ = _call("manim_animation", {"code": code}, fake_env)
        assert final == {"ok": False, "error": "渲染失败:第 6 行 `x = 1 / 0  # BOOM`:ZeroDivisionError: division by zero"}

    def test_准备环境_用配置的Python(self, fake_env: dict[str, str]) -> None:
        final, progress = _call("manim_setup", {}, fake_env, locale="en")
        assert final["ok"] is True, final
        assert final["output"]["manim"] == "0.21.0" and final["output"]["source"] == "configured"
        assert "PyAV" in final["output"]["ffmpeg"] and progress

    def test_没准备好时说去跑准备环境(self, fake_env: dict[str, str]) -> None:
        env = {key: value for key, value in fake_env.items() if key != "PYTHON_EXECUTABLE"}
        final, _ = _call("manim_animation", {"code": SCENE}, env)
        assert final["ok"] is False and "准备 Manim 环境" in final["error"]

    def test_取消真的停下Manim(self, fake_env: dict[str, str]) -> None:
        process = subprocess.Popen([sys.executable, str(TOOLS / "main.py")], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, env=fake_env)
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps({"tool": "manim_animation", "input": {"code": SCENE + "        # SLOW\n"}}))
        process.stdin.close()
        while True:  # 等它真的跑起来
            first = json.loads(process.stdout.readline())
            if "动画" in first.get("message", ""):
                break
        pid_file = next((Path(fake_env["MOSAEL_PLUGIN_DATA_DIR"]) / "jobs").glob("*/fake.pid"))
        child = int(pid_file.read_text())
        Path(fake_env["MOSAEL_PLUGIN_CANCEL_FILE"]).touch()
        rest = process.stdout.read()
        assert process.wait(timeout=15) == 0
        assert json.loads(rest.strip().splitlines()[-1]) == {"ok": False, "error": "已取消。"}
        with pytest.raises(ProcessLookupError):
            for _ in range(50):
                os.kill(child, 0)
                time.sleep(0.1)

    def test_宿主的流式协议收得到进度和产出(self, fake_env: dict[str, str], tmp_path: Path) -> None:
        """经宿主真正的 stream_tool 跑一次:NDJSON 进度进 on_progress,最后一行是结果。"""
        from app.domain.plugins.runtime import StreamHooks, stream_tool

        seen: list[tuple[float, str]] = []
        hooks = StreamHooks(on_progress=lambda f, m: seen.append((f, m)), on_task=lambda _t: None, is_cancelled=lambda: False)
        scratch = Path(fake_env["MOSAEL_PLUGIN_OUTPUT_DIR"])
        result = stream_tool(PLUGIN, "tools/main.py", "manim_animation", {"code": SCENE},
                             {"PYTHON_EXECUTABLE": fake_env["PYTHON_EXECUTABLE"]}, hooks=hooks, scratch_dir=scratch,
                             data_dir=Path(fake_env["MOSAEL_PLUGIN_DATA_DIR"]), timeout=60)
        assert result.output["artifact"]["path"] == "animation.mp4" and (scratch / "animation.mp4").is_file()
        assert seen and all(0 <= fraction <= 1 for fraction, _ in seen)


# ---------------------------------------------------------------- 插件自己的 venv 跟着解释器走

def _real_venv(data: Path, *, manim: str | None = None) -> Path:
    """用跑测试的这个解释器建一个真的 venv(不装 pip,一两秒),打上「装好了」的戳。"""
    venv = data / "venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True, timeout=120)
    (venv / manim_env.STAMP).write_text(json.dumps({"manim": manim or manim_env.MANIM_VERSION}), encoding="utf-8")
    return venv


def _rewrite_cfg(venv: Path, **values: str) -> None:
    lines = []
    for one in (venv / "pyvenv.cfg").read_text(encoding="utf-8").splitlines():
        key = one.partition("=")[0].strip()
        lines.append(f"{key} = {values[key]}" if key in values else one)
    (venv / "pyvenv.cfg").write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.mark.skipif(sys.platform == "win32", reason="venv 里的解释器在 POSIX 上是符号链接,这里造的是那一种坏法")
class Test环境跟着解释器走:
    """随包的 Python 会随 Mosael 升级换次版本、会随 .app 挪位置;插件的 venv 在持久目录里,跨更新都在。
    此前只认「venv/bin/python 在不在 + 戳上的 Manim 版本」:挪了位置说「还没装好」,换了次版本则说装好了,
    一渲就是 `No module named 'manim'`。"""

    @pytest.fixture()
    def data(self, tmp_path: Path, monkeypatch) -> Path:
        monkeypatch.setenv("MOSAEL_PLUGIN_DATA_DIR", str(tmp_path))
        monkeypatch.delenv("PYTHON_EXECUTABLE", raising=False)
        return tmp_path

    def test_好好的环境直接用(self, data: Path) -> None:
        venv = _real_venv(data)
        assert manim_env.venv_state(venv) == manim_env.READY
        assert manim_env.render_python("zh") == str(manim_env.venv_python(venv))

    def test_解释器挪了位置_自动接回去_装好的包还在(self, data: Path) -> None:
        venv = _real_venv(data)
        site = next(venv.glob("lib/python*/site-packages"))
        (site / "marker_pkg.py").write_text("X = 1\n", encoding="utf-8")
        gone = data / "old-app" / "bin"
        _rewrite_cfg(venv, home=str(gone))
        for one in (venv / "bin").glob("python*"):
            one.unlink()
            one.symlink_to(gone / "python3")
        assert manim_env.venv_state(venv) == manim_env.MOVED
        python = manim_env.render_python("zh")
        assert manim_env.venv_state(venv) == manim_env.READY
        done = subprocess.run([python, "-c", "import marker_pkg; print(marker_pkg.X)"], capture_output=True, text=True, timeout=30)
        assert done.stdout.strip() == "1", done.stderr

    def test_换了次版本_渲染说清楚要重装(self, data: Path) -> None:
        venv = _real_venv(data)
        _rewrite_cfg(venv, version="3.9.1")
        assert manim_env.venv_state(venv) == manim_env.OTHER_PYTHON
        with pytest.raises(PluginError, match=r"3\.9.*准备 Manim 环境"):
            manim_env.render_python("zh")

    def test_插件升级换了Manim版本_渲染说清楚要重装(self, data: Path) -> None:
        _real_venv(data, manim="0.18.0")
        with pytest.raises(PluginError, match=r"0\.18\.0.*准备 Manim 环境"):
            manim_env.render_python("zh")

    def test_准备环境遇到换了次版本的_不用勾重装也会重建(self, data: Path, monkeypatch) -> None:
        venv = _real_venv(data)
        _rewrite_cfg(venv, version="3.9.1")
        built: list[Path] = []
        monkeypatch.setattr(manim_env, "_build", lambda _send, _locale, where, _deadline: built.append(where))
        assert manim_env.install(lambda _event: None, "zh") is True and built == [venv]


# ---------------------------------------------------------------- 清单

class Test清单:
    def manifest(self) -> dict:
        return json.loads((PLUGIN / "mosael.plugin.json").read_text(encoding="utf-8"))

    def test_宿主读得懂(self) -> None:
        from app.domain.plugins.manifest import parse

        parsed = parse(self.manifest(), str(PLUGIN))
        assert parsed.id == "dev.mosael.manim" and {t["name"] for t in parsed.declared_tools} == {
            "manim_setup", "manim_explainer", "manim_animation", "manim_still"}

    def test_渲染工具的预算压在智能体的上限以内_插件自己先停(self) -> None:
        """智能体单次工具调用最多等 180 秒(agent-sidecar/src/tools.ts):超过的话它先断,后端还在白跑。"""
        tools = {t["name"]: t for t in self.manifest()["tools"]["declare"]}
        sidecar = (PLUGIN.parents[2] / "agent-sidecar" / "src" / "tools.ts").read_text(encoding="utf-8")
        agent_limit = int(re.search(r"TOOL_CALL_TIMEOUT_MS = ([\d_]+)", sidecar).group(1).replace("_", "")) / 1000
        for name in ("manim_explainer", "manim_animation", "manim_still"):
            assert render.RENDER_TIMEOUT < tools[name]["timeout_seconds"] < agent_limit, name
        assert manim_env.SETUP_TIMEOUT < tools["manim_setup"]["timeout_seconds"]
        assert all(tool.get("stream") is True for tool in tools.values()), "都要能报进度、能取消"

    def test_画板上只落成品_字幕是自己的一个口子(self) -> None:
        """没写 board_outputs 时画板把每个输出都落一格:讲解视频会多出「全部产出」「每步起止时间」两张 JSON 便签。"""
        nodes = {t["name"]: t["node"] for t in self.manifest()["tools"]["declare"]}
        assert nodes["manim_explainer"]["board_outputs"] == ["asset_id", "subtitles"]
        assert nodes["manim_explainer"]["output_types"]["subtitles"] == "asset"
        assert nodes["manim_animation"]["board_outputs"] == nodes["manim_still"]["board_outputs"] == ["asset_id"]
        assert nodes["manim_setup"]["board_outputs"] == ["summary"]

    def test_会执行代码的工具默认不开放(self) -> None:
        tools = self.manifest()["tools"]
        assert tools["expose"] == "selected"
        assert set(tools["recommended"]) == {"manim_setup", "manim_explainer"}
        assert not any(tool.get("read_only") for tool in tools["declare"])

    def test_README里写的版本和锁定的一致(self) -> None:
        assert f"Manim {manim_env.MANIM_VERSION}" in (PLUGIN / "README.md").read_text(encoding="utf-8")
