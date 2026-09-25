"""讲解视频的场景:**一份固定的代码**,内容全从同目录的 spec.json 读。

用户给的文字、公式、代码从来不拼进 Python 源码 —— 拼进去就得操心引号、换行、三引号怎么转义,
漏一处就是一段能执行的代码。这里的做法是:场景是插件自带的一份写死的文件,内容走 JSON,
文字进 `Text`(纯文本,不解析标记),公式进 `MathTex`(插件那一侧先挡掉 `\\input` 这类读写文件的命令),
函数曲线由 mosael_expr 解析成算式树求值(不经 `eval`)。

每一段开始、结束时往 stderr 写一行 `MOSAEL_MANIM {…}`(见 mosael_runner.say):插件据此报进度,
并交回每一步**实际**的起止时间,方便给旁白、字幕对时间。
"""

from __future__ import annotations

import json
from pathlib import Path

from manim import (
    BOLD, DOWN, LEFT, ORIGIN, RIGHT, UP, Axes, Code, Create, FadeIn, FadeOut, GrowFromCenter, Line, MathTex,
    Scene, SurroundingRectangle, Text, Transform, VGroup, VMobject, Write,
)

from mosael_expr import compile_function, format_tick, sample, segments, ticks
from mosael_runner import say
from mosael_text import latex_to_plain, wrap

SPEC = json.loads(Path(__file__).with_name("spec.json").read_text(encoding="utf-8"))

# 每个动作的时长(秒)。插件那一侧估算「这一步至少要多久」用的是同一组数(manim_explainer.BEATS)。
T_TITLE, T_CAPTION, T_FORMULA, T_AXES, T_CURVE, T_LABEL = 0.6, 0.4, 1.2, 0.8, 1.5, 0.4
T_CODE, T_HIGHLIGHT, T_BULLET, T_OUT = 0.8, 0.4, 0.5, 0.5


#: 没指定字体时按顺序挑第一款装了的:都是中英文都好看的无衬线体。不挑的话 Pango 的默认回退
#: 常把拉丁字母落到衬线体上,同一行里中文是黑体、英文是宋体。
FONT_CANDIDATES = ("PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Microsoft YaHei UI", "Noto Sans CJK SC",
                   "Noto Sans SC", "Source Han Sans SC", "WenQuanYi Micro Hei", "Arial Unicode MS")


def default_font() -> str:
    try:
        import manimpango

        installed = set(manimpango.list_fonts())
    except Exception:  # noqa: BLE001 —— 列不出字体就交给 Pango 的默认
        return ""
    return next((one for one in FONT_CANDIDATES if one in installed), "")


class MosaelExplainer(Scene):
    def setup(self) -> None:
        self.colors = SPEC["colors"]
        self.camera.background_color = self.colors["background"]
        self.W = self.camera.frame_width
        self.H = self.camera.frame_height
        # 字号、间距都按画面**短边**缩放:Manim 的画面宽度固定(约 14.2),竖屏时是高度被拉长 ——
        # 不缩放的话,竖屏里的字和横屏一样大,相对手机屏幕就只有一小撮。
        self.s = min(self.W, self.H) / 8.0
        self.margin = 0.6 * self.s
        self.font = SPEC.get("font") or default_font()
        self.use_latex = bool(SPEC.get("use_latex"))
        self._unit_cache: dict[int, float] = {}

    # ------------------------------------------------------------ 文字

    def text(self, content: str, size: float, color: str, *, weight: str = "NORMAL") -> Text:
        kwargs = {"font_size": size * self.s, "color": color}
        if self.font:
            kwargs["font"] = self.font
        if weight != "NORMAL":
            kwargs["weight"] = weight
        return Text(content, **kwargs)

    def unit(self, size: float) -> float:
        """这个字号下一个「半角宽」多宽 —— 量出来的,不是猜的:字体不同,宽度就不同。"""
        key = int(size)
        if key not in self._unit_cache:
            sample_text = self.text("汉字汉字汉字汉字汉字", size, self.colors["text"])
            self._unit_cache[key] = max(sample_text.width / 20, 1e-3)
        return self._unit_cache[key]

    def block(self, content: str, size: float, color: str, width: float, *, weight: str = "NORMAL",
              max_lines: int = 0, align=LEFT) -> VGroup:
        """折好行的一段字,宽度不超过 width。"""
        lines = wrap(content, int(width / self.unit(size)))
        if max_lines and len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1].rstrip()[:-1] + "…"
        group = VGroup(*[self.text(line or " ", size, color, weight=weight) for line in lines])
        group.arrange(DOWN, aligned_edge=align, buff=0.18 * size / 32 * self.s)
        if group.width > width:
            group.scale_to_fit_width(width)
        return group

    def fit(self, mobject, width: float, height: float):
        if mobject.width > width:
            mobject.scale_to_fit_width(width)
        if mobject.height > height:
            mobject.scale_to_fit_height(height)
        return mobject

    # ------------------------------------------------------------ 内容块

    def formula(self, latex: str):
        if self.use_latex:
            return MathTex(latex, color=self.colors["text"], font_size=56 * self.s)
        return self.text(latex_to_plain(latex), 44, self.colors["text"])

    def plot(self, spec: dict, width: float, height: float) -> tuple[VGroup, VGroup, list]:
        x_min, x_max = spec["x_range"]
        y_min, y_max = spec["y_range"]
        axes = Axes(
            x_range=[x_min, x_max, spec["x_step"]], y_range=[y_min, y_max, spec["y_step"]],
            x_length=width * 0.9, y_length=height * 0.82, tips=False,
            axis_config={"color": self.colors["muted"], "stroke_width": 2},
        )
        labels = VGroup()
        for value in ticks(x_min, x_max, spec["x_step"]):
            if abs(value) > 1e-9:
                labels.add(self.text(format_tick(value), 20, self.colors["muted"]).next_to(axes.c2p(value, 0) if y_min <= 0 <= y_max else axes.c2p(value, y_min), DOWN, buff=0.12 * self.s))
        for value in ticks(y_min, y_max, spec["y_step"]):
            if abs(value) > 1e-9:
                labels.add(self.text(format_tick(value), 20, self.colors["muted"]).next_to(axes.c2p(x_min, value) if not x_min <= 0 <= x_max else axes.c2p(0, value), LEFT, buff=0.12 * self.s))
        f = compile_function(spec["expression"])
        curves = VGroup()
        for run in segments(sample(f, x_min, x_max, 600), y_min, y_max):
            clipped = [(x, min(max(y, y_min), y_max)) for x, y in run]
            curve = VMobject(color=self.colors["accent"], stroke_width=5)
            curve.set_points_as_corners([axes.c2p(x, y) for x, y in clipped])
            curves.add(curve)
        extras = []
        label_text = spec.get("label") or ""
        if label_text:
            label = self.text(label_text, 26, self.colors["accent"])
            label.next_to(axes, UP, buff=0.1 * self.s).align_to(axes, RIGHT)
            extras.append(label)
        return VGroup(axes, labels), curves, extras

    def code(self, spec: dict):
        style = SPEC.get("code_style") or "monokai"
        kwargs = dict(code_string=spec["code"], formatter_style=style, background="window",
                      add_line_numbers=True, paragraph_config={"font_size": 26 * self.s, "font": "Monospace"}, background_config={"fill_color": self.colors["panel"], "stroke_color": self.colors["muted"]})
        try:
            block = Code(language=spec.get("language") or "python", **kwargs)
        except Exception:  # noqa: BLE001 —— 认不出的语言:照样显示,只是不上色
            block = Code(language="text", **kwargs)
        return block

    # ------------------------------------------------------------ 各段

    def construct(self) -> None:
        parts = SPEC["segments"]
        for index, part in enumerate(parts):
            start = self.renderer.time
            say("segment", index=index, total=len(parts), part=part["kind"], title=part.get("title", ""), time=start)
            getattr(self, f"segment_{part['kind']}")(part)
            say("segment_end", index=index, time=self.renderer.time)
        say("done", time=self.renderer.time)

    def hold(self, seconds: float) -> None:
        if seconds > 0.02:
            self.wait(seconds)

    def segment_title(self, part: dict) -> None:
        width = self.W - 2 * self.margin
        title = self.block(part["title"], 64, self.colors["text"], width, weight=BOLD, align=ORIGIN)
        items = [title]
        label = subtitle = None
        if part.get("label"):
            label = self.block(part["label"], 28, self.colors["accent"], width, align=ORIGIN)
            items.insert(0, label)
        rule = Line(LEFT * min(2.5 * self.s, width / 3), RIGHT * min(2.5 * self.s, width / 3), color=self.colors["accent"], stroke_width=6)
        items.append(rule)
        if part.get("subtitle"):
            subtitle = self.block(part["subtitle"], 34, self.colors["muted"], width, align=ORIGIN)
            items.append(subtitle)
        group = VGroup(*items).arrange(DOWN, buff=0.45 * self.s)
        self.fit(group, width, self.H - 2 * self.margin).move_to([0, 0, 0])
        spent = 0.0
        if label is not None:
            self.play(FadeIn(label, shift=DOWN * 0.2), run_time=0.4)
            spent += 0.4
        self.play(Write(title), run_time=1.0)
        self.play(GrowFromCenter(rule), run_time=0.5)
        spent += 1.5
        if subtitle is not None:
            self.play(FadeIn(subtitle, shift=UP * 0.2), run_time=0.5)
            spent += 0.5
        self.hold(part["seconds"] - spent - T_OUT)
        self.play(FadeOut(group), run_time=T_OUT)

    def segment_summary(self, part: dict) -> None:
        width = self.W - 2 * self.margin
        heading = self.text(part["title"], 48, self.colors["accent"], weight=BOLD)
        rows = []
        for point in part["points"]:
            mark = self.text("✓", 34, self.colors["accent"])
            body = self.block(point, 34, self.colors["text"], width - 1.0 * self.s)
            row = VGroup(mark, body).arrange(RIGHT, buff=0.3 * self.s, aligned_edge=UP)
            mark.set_y(body[0].get_center()[1])
            rows.append(row)
        body = VGroup(*rows).arrange(DOWN, aligned_edge=LEFT, buff=0.35 * self.s)
        group = VGroup(heading, body).arrange(DOWN, buff=0.6 * self.s)
        self.fit(group, width, self.H - 2 * self.margin).move_to([0, 0, 0])
        self.play(FadeIn(heading, shift=DOWN * 0.2), run_time=T_TITLE)
        hold = max(0.0, part["seconds"] - T_TITLE - T_BULLET * len(rows) - T_OUT)
        each = hold / (len(rows) + 1)
        for row in rows:
            self.play(FadeIn(row, shift=RIGHT * 0.2), run_time=T_BULLET)
            self.hold(each)
        self.hold(each)
        self.play(FadeOut(group), run_time=T_OUT)

    def segment_step(self, part: dict) -> None:
        width = self.W - 2 * self.margin
        top = self.H / 2 - self.margin
        bottom = -self.H / 2 + self.margin
        spent = 0.0

        heading = self.block(part["title"], 44, self.colors["accent"], width, weight=BOLD, max_lines=2)
        heading.move_to([0, 0, 0]).to_edge(LEFT, buff=self.margin)
        heading.shift(UP * (top - heading.get_top()[1]))
        shown = [heading]
        self.play(FadeIn(heading, shift=RIGHT * 0.2), run_time=T_TITLE)
        spent += T_TITLE

        caption = None
        if part.get("narration") and SPEC.get("show_narration", True):
            caption = self.block(part["narration"], 28, self.colors["muted"], width, max_lines=4, align=ORIGIN)
            caption.move_to([0, bottom + caption.height / 2, 0])
            self.play(FadeIn(caption), run_time=T_CAPTION)
            shown.append(caption)
            spent += T_CAPTION

        area_top = heading.get_bottom()[1] - 0.45 * self.s
        area_bottom = (caption.get_top()[1] + 0.45 * self.s) if caption is not None else bottom
        area_height = max(1.0, area_top - area_bottom)
        area_center = (area_top + area_bottom) / 2

        has_visual = bool(part.get("formulas") or part.get("plot") or part.get("code"))
        bullets = part.get("bullets") or []
        side_by_side = has_visual and bullets and self.W / self.H > 1.2
        visual_width = width * (0.56 if side_by_side else 1.0)
        bullet_width = width * (0.40 if side_by_side else 1.0)
        visual_height = area_height if side_by_side or not bullets else area_height * 0.58
        bullet_height = area_height if side_by_side or not has_visual else area_height * 0.38

        # 要点先摆好位置(还不出现),视觉块按剩下的地方放
        bullet_rows = []
        for item in bullets:
            dot = self.text("•", 32, self.colors["accent"])
            body = self.block(item, 32, self.colors["text"], bullet_width - 0.6 * self.s)
            row = VGroup(dot, body).arrange(RIGHT, buff=0.25 * self.s, aligned_edge=UP)
            dot.set_y(body[0].get_center()[1])  # 圆点对齐第一行的中线,而不是顶边
            bullet_rows.append(row)
        bullet_group = VGroup(*bullet_rows).arrange(DOWN, aligned_edge=LEFT, buff=0.3 * self.s) if bullet_rows else None
        if bullet_group is not None:
            self.fit(bullet_group, bullet_width, bullet_height)

        reveals: list = []
        visual = None
        if part.get("formulas"):
            visual = VGroup(*[self.formula(one) for one in part["formulas"]]).arrange(DOWN, buff=0.45 * self.s)
            self.fit(visual, visual_width, visual_height)
            self.place(visual, bullet_group, side_by_side, width, area_center, visual_height, bullet_height)
            for one in visual:
                self.play(Write(one), run_time=T_FORMULA)
                spent += T_FORMULA
        elif part.get("plot"):
            frame, curves, extras = self.plot(part["plot"], visual_width, visual_height)
            visual = VGroup(frame, curves, *extras)
            self.fit(visual, visual_width, visual_height)
            self.place(visual, bullet_group, side_by_side, width, area_center, visual_height, bullet_height)
            self.play(Create(frame), run_time=T_AXES)
            self.play(*[Create(curve) for curve in curves], run_time=T_CURVE)
            spent += T_AXES + T_CURVE
            if extras:
                self.play(*[FadeIn(one) for one in extras], run_time=T_LABEL)
                spent += T_LABEL
        elif part.get("code"):
            code = self.code(part["code"])
            self.fit(code, visual_width, visual_height)
            self.place(code, bullet_group, side_by_side, width, area_center, visual_height, bullet_height)
            visual = VGroup(code)
            self.play(FadeIn(code), run_time=T_CODE)
            spent += T_CODE
            lines = code.code_lines
            for first, last in part["code"].get("highlight") or []:
                first, last = max(1, first), min(len(lines), last)
                if first > last:
                    continue
                reveals.append(("highlight", VGroup(*lines[first - 1:last])))
        elif bullet_group is not None:
            bullet_group.move_to([-width / 2 + bullet_group.width / 2, area_center, 0])

        if visual is not None:
            shown.append(visual)
        reveals.extend(("bullet", row) for row in bullet_rows)

        hold = max(0.0, part["seconds"] - spent - T_OUT - sum(T_HIGHLIGHT if kind == "highlight" else T_BULLET for kind, _ in reveals))
        each = hold / (len(reveals) + 1)
        marker = None
        for kind, target in reveals:
            if kind == "highlight":
                box = SurroundingRectangle(target, color=self.colors["accent"], buff=0.08 * self.s, stroke_width=3)
                box.set_fill(self.colors["accent"], opacity=0.14)
                if marker is None:
                    marker = box
                    self.play(Create(marker), run_time=T_HIGHLIGHT)
                    shown.append(marker)
                else:
                    self.play(Transform(marker, box), run_time=T_HIGHLIGHT)
            else:
                self.play(FadeIn(target, shift=RIGHT * 0.2), run_time=T_BULLET)
                shown.append(target)
            self.hold(each)
        self.hold(each)
        self.play(*[FadeOut(one) for one in shown], run_time=T_OUT)

    def place(self, visual, bullets, side_by_side: bool, width: float, center: float, visual_height: float, bullet_height: float) -> None:
        """视觉块和要点的摆法:横屏左右分栏(要点在左),竖屏 / 方形上下叠(视觉块在上)。"""
        if bullets is None:
            visual.move_to([0, center, 0])
            return
        if side_by_side:
            bullets.move_to([-width / 2 + bullets.width / 2, center, 0])
            visual.move_to([width / 2 - width * 0.56 / 2, center, 0])
            return
        total = visual_height + bullet_height
        visual.move_to([0, center + total / 2 - visual_height / 2, 0])
        bullets.next_to(visual, DOWN, buff=0.45 * self.s)
        bullets.set_x(-width / 2 + bullets.width / 2)

