#!/usr/bin/env python3
"""Capture the current Mosael UI, in both languages and themes, from the isolated demo environment.

Start the environment first (see docs/media/README.md):

  backend/.venv/bin/python website/scripts/seed-doc-demo.py up --dir /private/path/mosael-demo
  backend/.venv/bin/python website/scripts/record-doc-media.py --demo-dir /private/path/mosael-demo

No DOM replacement, fabricated agent responses, provider calls, or publishing actions. Screenshots are
native Playwright captures; GIFs and MP4s come from actual browser video of real clicks, typing, hovering
and dragging. A failed selector stops the run, so an old asset can never pass as a fresh recording.
Edits a scene makes for the camera (a typed prompt, a 3D keyframe) are undone before it ends, so every
language and theme starts from the same seeded data.

The token file is a JSON string and never enters the public capture manifest. `--out` writes a trial run
somewhere else without touching website/public/media or the manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "website/public/media"
VIEWPORT = {"width": 1440, "height": 900}
MESSAGES = ROOT / "frontend/src/app/messages"


def load_seed():
    """The seed script owns every demo title; read them from there so the two cannot drift."""
    spec = importlib.util.spec_from_file_location("seed_doc_demo", Path(__file__).with_name("seed-doc-demo.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SEED = load_seed()


class Labels:
    """Interface labels: the Chinese string written in a scene is looked up in the app's own message tables."""

    LINE = re.compile(r'^\s*(\w+): "((?:[^"\\]|\\.)*)",?\s*$')

    def __init__(self) -> None:
        self.zh, self.en = self.read("zh-CN"), self.read("en-US")
        self.by_zh: dict[str, set[str]] = {}
        for key, value in self.zh.items():
            self.by_zh.setdefault(value, set()).add(key)

    def read(self, locale: str) -> dict[str, str]:
        table: dict[str, str] = {}
        for file in sorted((MESSAGES / locale).glob("*.ts")):
            for line in file.read_text().splitlines():
                match = self.LINE.match(line)
                if match:
                    table[match.group(1)] = json.loads(f'"{match.group(2)}"')
        return table

    def english(self, zh: str) -> str:
        values = {self.en[k] for k in self.by_zh.get(zh, ()) if k in self.en}
        if len(values) != 1:
            raise KeyError(f"No single English label for {zh!r}: {sorted(values)}; pass it explicitly")
        return values.pop()


LABELS = Labels()


class Capture:
    def __init__(self, page, locale: str, theme: str, fixture: dict, app: str, out: Path):
        self.page, self.locale, self.theme, self.app, self.out = page, locale, theme, app, out
        self.fixture, self.F = fixture, fixture["locales"][locale]
        self.T = SEED.TEXT[locale]
        self.outputs: list[Path] = []
        self.start: float | None = None

    # -- words and controls -------------------------------------------------------------------
    def word(self, zh: str, en: str | None = None) -> str:
        if self.locale == "zh":
            return zh
        return en if en is not None else LABELS.english(zh)

    def hold(self, ms: int = 850) -> None:
        self.page.wait_for_timeout(ms)

    def button(self, zh: str, en: str | None = None, exact: bool = True):
        return self.page.get_by_role("button", name=self.word(zh, en), exact=exact)

    def click(self, zh: str, en: str | None = None, *, last: bool = False, hold: int = 850) -> None:
        target = self.button(zh, en)
        (target.last if last else target.first).click()
        self.hold(hold)

    def tab(self, zh: str, en: str | None = None):
        return self.page.get_by_role("tab", name=self.word(zh, en), exact=True)

    def escape(self) -> None:
        self.page.keyboard.press("Escape")
        self.hold(550)

    # -- navigation ---------------------------------------------------------------------------
    def goto(self, view: str) -> None:
        self.page.goto(f"{self.app}/#/{view}", wait_until="networkidle")
        self.page.wait_for_function('document.fonts.status === "loaded"')
        self.hold(900)

    def warm(self, *views: str) -> None:
        """Visit the pages a recording will move to before it starts, like someone who has already opened them
        this session: their code and data are loaded, so the recording does not catch the page-level "Loading…"."""
        for view in views:
            self.goto(view)
            self.hold(1200)

    def editor(self) -> None:
        self.goto("editor?p=" + self.F["project"])
        self.page.get_by_role("button", name=re.compile(re.escape(self.T["assets"]["forest"]) + "$")).first.wait_for()
        self.hold(1200)

    def board(self, key: str = "board") -> None:
        # Through the board list, as a user switches boards (a page reload would flash an unstyled frame
        # into the recording).
        self.goto("boards")
        crumb = self.page.get_by_role("banner").get_by_role("button", name=self.word("创意画板", "Idea board"), exact=True)
        if crumb.count():  # a board is open: the breadcrumb leads back to the list
            crumb.click()
            self.hold(900)
        self.page.get_by_text(self.T[key], exact=True).first.click()
        self.page.locator(".react-flow__node").first.wait_for()
        self.hold(1400)

    def workflow(self, key: str) -> None:
        self.goto("workflows")
        crumb = self.page.get_by_role("banner").get_by_role("button", name=self.word("工作流", "Workflows"), exact=True)
        if crumb.count():  # an editor is open: the breadcrumb leads back to the list
            crumb.click()
            self.hold(900)
        self.page.get_by_role("button", name=self.F["workflow_names"][key], exact=True).first.click()
        self.page.locator(".react-flow__node").first.wait_for()
        self.hold(1200)
        self.click("适应画布", hold=1000)

    def node(self, node_id: str):
        return self.page.locator(f'.react-flow__node[data-id="{node_id}"]')

    # -- outputs ------------------------------------------------------------------------------
    def path(self, kind: str, name: str) -> Path:
        p = self.out / kind
        if self.locale == "en":
            p = p / "en"
        if self.theme == "dark":
            p = p / "dark"
        p.mkdir(parents=True, exist_ok=True)
        return p / name

    def shot(self, name: str) -> None:
        target = self.path("screens", name + ".png")
        self.page.screenshot(path=str(target))
        self.outputs.append(target)

    def begin(self) -> None:
        self.start = time.monotonic()
        self.hold(1000)


# ---------------------------------------------------------------------------------------------- scenes


def home(c: Capture) -> None:
    c.warm("editor?p=" + c.F["project"])
    c.goto("home")
    c.shot("home")
    c.begin()
    c.click("全部项目")
    c.hold()
    c.click("最近编辑")
    c.page.get_by_role("button", name=re.compile(re.escape(c.T["project"]))).first.click()
    c.hold(2200)


def media(c: Capture) -> None:
    c.goto("media")
    c.shot("media")
    c.begin()
    c.click("从链接导入")
    c.shot("url-import")
    c.hold(1300)
    c.escape()
    names = c.T["assets"]
    for key, name in [("forest", "media-video"), ("narration", "media-audio"), ("forest-frame", "media-image")]:
        c.page.get_by_role("button", name=names[key], exact=True).first.click()
        c.hold(1300)
        c.shot(name)
        c.hold(1200)
        c.escape()


def documents(c: Capture) -> None:
    c.goto("media")
    c.begin()
    c.page.get_by_role("button", name=re.compile("^" + c.word("文档", "Document") + r"\s*\d")).first.click()
    c.hold(1100)
    c.shot("media-documents")
    c.page.get_by_role("button", name=c.T["assets"]["shotlist"], exact=True).first.click()
    c.hold(2600)
    c.shot("document-reader")
    c.page.get_by_role("button", name=c.word("第 2 页", "pages 2"), exact=True).first.click()
    c.hold(1600)
    c.escape()


def timeline_edit(c: Capture) -> None:
    c.editor()
    c.shot("editor")
    c.begin()
    c.page.get_by_role("button", name=re.compile(re.escape(c.T["assets"]["rodents"]) + "$")).first.click()
    c.hold()
    c.shot("editor-inspector")
    c.click("播放 / 暂停 (Space)", hold=2600)
    c.click("播放 / 暂停 (Space)")


def timeline_tools(c: Capture) -> None:
    c.editor()
    c.begin()
    c.click("放大时间线", hold=500)
    c.click("放大时间线", hold=700)
    clip = c.page.get_by_role("button", name=re.compile(re.escape(c.T["assets"]["rodents"]) + "$")).first
    clip.click()
    c.hold(900)
    c.shot("editor-linked")
    # Drag a shot over its neighbour in overwrite mode: the covered part is cut out live. Esc cancels the drag.
    moving = c.page.get_by_role("button", name=re.compile(re.escape(c.T["assets"]["butterfly"]) + "$")).first
    box = moving.bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    c.page.mouse.move(x, y)
    c.page.mouse.down()
    for step in range(1, 31):
        c.page.mouse.move(x - step * 5, y)
        c.page.wait_for_timeout(25)
    c.hold(700)
    c.shot("editor-overwrite")
    c.page.keyboard.press("Escape")
    c.page.mouse.up()
    c.hold(700)
    # Mark in / out on the ruler with I and O.
    c.page.keyboard.press("Home")
    for _ in range(6):
        c.page.keyboard.press("Shift+ArrowRight")
    c.page.keyboard.press("i")
    for _ in range(15):
        c.page.keyboard.press("Shift+ArrowRight")
    c.page.keyboard.press("o")
    c.hold(900)
    c.shot("editor-in-out")
    clip.click(button="right")
    c.hold(900)
    c.shot("editor-clip-menu")
    c.escape()
    c.click("快捷键", "Shortcuts", hold=1000)
    c.shot("editor-shortcuts")
    c.hold(1200)
    c.escape()
    c.page.keyboard.press("Alt+x")
    c.hold(500)


def subtitle_dub(c: Capture) -> None:
    c.editor()
    c.click("字幕")
    c.shot("subtitles")
    c.begin()
    c.page.get_by_role("toolbar").get_by_role("button", name=c.word("配音", "Voice"), exact=True).click()
    c.hold(1100)
    c.shot("subtitle-dub")
    c.hold(1500)
    c.click("逐字稿")
    c.shot("transcript")
    c.hold(1000)


def subtitle_panel(c: Capture) -> None:
    c.editor()
    c.click("字幕")
    c.begin()
    # The time range of a cue is a button that moves the playhead there: both tracks show in one box.
    c.page.get_by_role("button", name=re.compile(r"^00:00\.4 – ")).first.click()
    c.hold(1200)
    c.shot("subtitle-bilingual")
    c.click("改起止时间", hold=1000)
    c.shot("subtitle-timing")
    c.hold(800)
    c.escape()
    c.click("导入字幕文件", hold=1000)
    c.shot("subtitle-import")
    c.hold(800)
    c.escape()
    c.click("导出字幕文件", hold=1000)
    c.shot("subtitle-files")
    c.hold(800)
    c.escape()


def export(c: Capture) -> None:
    c.editor()
    c.begin()
    c.click("导出", "Export", hold=1200)
    c.shot("export-dialog")
    c.page.get_by_role("checkbox").first.click()
    c.hold(1200)
    c.page.get_by_role("checkbox").first.click()
    c.hold(800)
    c.escape()


def ai(c: Capture) -> None:
    c.goto("ai")
    c.shot("ai-chat")
    c.begin()
    c.tab("轨迹").click()
    c.hold()
    c.shot("agent-trace")
    c.hold(1300)
    c.tab("对话", "Conversation").last.click()
    c.hold()
    c.tab("生成", "Generate").click()
    c.hold()
    c.shot("ai-generate")
    c.hold(1300)
    c.tab("音频", "Audio").click()
    c.hold(1300)
    c.shot("ai-audio")
    c.tab("对话", "Chat").first.click()
    c.hold(800)


def agent(c: Capture) -> None:
    """A real turn of a local model (Ollama, see seed --local-chat): it asks to delete an asset, the request
    stops on the confirmation card under the tool row, and we decline — nothing is deleted."""
    if not c.fixture.get("local_chat"):
        raise RuntimeError("The agent scene needs the demo seeded with --local-chat (a model served by local Ollama).")
    c.goto("ai")
    c.page.locator("[contenteditable=true]").last.click()
    c.page.keyboard.type(c.T["agent_request"], delay=20)
    c.page.keyboard.press("Enter")
    # The model's turn takes a minute or so locally; the recording starts once the card is on screen.
    c.button("拒绝", "Reject").first.wait_for(timeout=300_000)
    c.hold(1500)
    c.shot("agent-confirm")
    c.begin()
    c.page.get_by_text(c.word("原始数据"), exact=True).first.click()
    c.hold(1200)
    c.page.get_by_text(c.word("原始数据"), exact=True).first.click()
    c.hold(600)
    c.click("拒绝", "Reject", hold=600)
    # While the turn runs the composer shows "Stop" instead of "Send"; Send coming back means the reply is in.
    c.button("发送", "Send").wait_for(timeout=240_000)
    c.hold(1500)
    c.shot("agent-decided")
    c.hold(1200)


def workflows(c: Capture) -> None:
    c.goto("workflows")
    c.shot("workflow-list")
    c.workflow("transcript_video_cleanup")
    c.shot("workflows")
    c.begin()
    c.click("添加节点")
    c.shot("workflow-add-node")
    c.hold(1400)
    c.escape()
    c.node("verbatim_transcript").click()
    c.hold(1100)
    c.shot("workflow-node")
    c.hold(1400)


def workflow_editor(c: Capture) -> None:
    c.workflow("roundup")
    c.shot("workflow-references")
    c.begin()
    c.node("summary").click()
    c.hold(1200)
    c.shot("workflow-reference-tags")
    c.node("start").click()
    c.hold(1200)
    c.shot("workflow-start-params")
    c.escape()
    c.page.get_by_role("button", name=re.compile("^" + c.word("就绪检查") + "[:：]")).click()
    c.hold(1200)
    c.shot("workflow-readiness")
    c.escape()
    c.click("执行历史", hold=1400)
    c.shot("workflow-runs")
    c.hold(1200)
    c.escape()


def workflow_templates(c: Capture) -> None:
    c.goto("workflows")
    c.begin()
    c.click("工作流社区", hold=1600)
    c.shot("workflow-templates")
    c.page.get_by_role("dialog").get_by_role("button", name=c.F["workflow_names"]["account_analysis"], exact=True).click()
    c.hold(1600)
    c.shot("workflow-template-check")
    c.hold(1000)
    c.escape()
    c.escape()
    c.workflow("account_analysis")
    c.node("start").click()
    c.hold(1300)
    c.page.get_by_role("combobox").filter(has_text=c.word("选一个")).first.click()
    c.hold(1000)
    c.shot("workflow-start-options")
    c.hold(1000)
    c.escape()
    c.escape()
    # Readiness: what still blocks this template here (its required start parameters are empty).
    c.page.get_by_role("button", name=re.compile("^" + c.word("就绪检查") + "[:：]")).click()
    c.hold(1300)
    c.shot("workflow-readiness-blocked")
    c.hold(900)
    c.escape()
    c.workflow("full_video_generation")
    c.shot("workflow-full-video")
    c.hold(800)


def boards(c: Capture) -> None:
    c.board()
    c.click("适应画布", hold=1000)
    c.shot("boards")
    c.begin()
    c.node("draft-video").click()
    c.hold(1100)
    box = c.page.locator("[contenteditable=true]").last
    draft = c.T["board_draft"]
    box.click()
    c.page.keyboard.press("End")
    c.page.keyboard.type(c.word(",镜头慢慢推近", ", the camera slowly pushing in"), delay=90)
    c.hold()
    c.shot("board-form")
    c.page.keyboard.type(" @", delay=200)
    c.hold(1000)
    c.shot("board-mention")
    c.hold(1400)
    c.escape()
    # Put the seeded prompt back so every language and theme starts from the same board.
    c.page.locator("[contenteditable=true]").last.click()
    c.page.keyboard.press("Meta+a")
    c.page.keyboard.type(draft)
    c.hold()


def board_cells(c: Capture) -> None:
    c.board()
    c.click("适应画布", hold=1000)
    c.begin()
    c.click("添加", hold=1000)
    c.shot("board-add-menu")
    c.escape()
    c.node("reference-frame").click()
    c.hold(1100)
    c.shot("board-abilities")
    c.node("idea").click(modifiers=["Shift"])
    c.node("reference-clip").click(modifiers=["Shift"])
    c.hold(1100)
    c.shot("board-selection")
    c.page.locator(".react-flow__pane").click(position={"x": 60, "y": 760})
    c.hold(800)
    c.node("draft-image").click()
    c.hold(1300)
    # "N×": how many cells one run lands (the placeholder image model returns up to four per run).
    c.page.get_by_role("combobox", name=c.word("一次落出几格")).click()
    c.hold(1000)
    c.shot("board-generate")
    c.hold(800)
    c.escape()
    c.escape()
    # Replacing an image cell's picture opens the picker: this board, the asset library, or upload / drop a file.
    c.node("reference-frame").click()
    c.hold(900)
    c.click("换一份", hold=1400)
    c.shot("board-picker")
    c.hold(800)
    c.escape()
    c.escape()
    # The gallery board: the 3D scene cell (two ways to produce) and the 3D reference it hands a video cell.
    c.board("board2")
    c.click("适应画布", hold=1000)
    c.node("scene").click()
    c.hold(1300)
    c.shot("board-scene-cell")
    c.node("shot-video").click()
    c.hold(1300)
    c.shot("board-scene-reference")
    c.escape()
    # The rough cut: shots connected into a timeline cell.
    c.board("board3")
    c.click("适应画布", hold=1600)
    c.shot("board-timeline")
    c.hold(800)


def annotations(c: Capture) -> None:
    c.board("board2")
    c.click("适应画布")
    c.shot("annotations")
    c.begin()
    c.click("标记模式")
    marker = lambda name: c.page.get_by_role("button", name=re.compile("^" + re.escape(name) + r"(\s|$)")).first
    marker(c.T["markers"][0]).click()
    c.hold()
    c.shot("marker-editor")
    marker(c.T["markers"][1]).click()
    c.hold()
    c.escape()
    c.click("隐藏标记", "Hide markers")
    c.hold()
    c.click("显示标记", "Show markers")
    c.click("评论模式", hold=1100)
    c.escape()
    c.hold()


def notes(c: Capture) -> None:
    c.goto("notes?note=" + c.F["note"])
    c.shot("notes")
    c.begin()
    # The note's own mode buttons, inside the page — in English the sidebar's "Edit" (the editor) has the same name.
    mode = lambda zh, en: c.page.get_by_role("main").get_by_role("button", name=c.word(zh, en), exact=True).first.click()
    mode("阅读", "Read")
    c.hold(1100)
    c.shot("notes-read")
    mode("Markdown", "Markdown")
    c.hold(1300)
    c.shot("notes-markdown")
    mode("编辑", "Edit")
    c.hold(1000)


def scenes(c: Capture) -> None:
    c.goto("scenes?scene=" + c.F["scene"])
    c.hold(1500)
    c.shot("scenes")
    c.begin()
    c.click("添加物体")
    c.shot("scene-add")
    c.hold(900)
    c.escape()
    c.click("机位视角")
    c.shot("scene-camera")
    c.hold(1100)
    c.click("俯瞰全场")
    c.click("播放镜头", hold=2200)
    c.click("暂停")
    c.shot("scene-observation")
    c.click("自由视角")
    c.click("回到起点")
    product = SEED_PRODUCT[c.locale]
    c.page.locator("button").filter(has_text=re.compile("^" + re.escape(product) + "$")).last.click()
    c.hold()
    c.page.keyboard.press("i")
    c.hold()
    c.click("跳到结尾", "Go to end")
    c.page.keyboard.press("i")
    c.hold()
    c.shot("scene-keyframes")
    # Take the two keyframes back out (the scene autosaves).
    c.click("撤销", hold=400)
    c.click("撤销", hold=900)


SEED_PRODUCT = {"zh": "产品占位球", "en": "Product placeholder"}


def plugins(c: Capture) -> None:
    c.goto("plugins")
    c.shot("plugins")
    c.begin()
    c.page.get_by_role("button", name=re.compile(c.word("百度网盘", "Baidu Netdisk"))).first.click()
    c.hold(1200)
    c.shot("plugin-detail")
    c.click("新建连接", hold=1200)
    c.shot("plugin-connection")
    c.escape()


def plugin_market(c: Capture) -> None:
    c.goto("plugins")
    c.begin()
    c.click("浏览插件市场", hold=2200)
    c.shot("plugin-market")
    c.hold(1000)
    c.escape()


def publishing(c: Capture) -> None:
    c.warm("browser-pool")
    c.goto("publish")
    c.shot("publish")
    c.begin()
    c.click("新建发布")
    c.shot("publish-form")
    c.hold(1600)
    c.escape()
    c.goto("browser-pool")
    c.shot("browser-pool")
    c.click("添加账号")
    c.shot("browser-account")
    c.hold(1600)
    c.escape()


def scheduler(c: Capture) -> None:
    c.goto("scheduler")
    c.shot("scheduler")
    c.begin()
    c.page.get_by_role("button", name=re.compile(re.escape(c.T["schedule"]))).first.click()
    c.hold(1500)
    c.shot("scheduler-runs")
    c.click("新建任务")
    c.shot("scheduler-form")
    c.hold(1500)
    c.escape()


def providers(c: Capture) -> None:
    c.goto("settings")
    c.shot("settings")
    c.begin()
    c.click("AI 对话")
    c.shot("settings-models")
    c.hold(1300)
    c.click("AI 绘图", hold=1300)
    c.click("能力提供方", hold=1300)
    c.shot("settings-capabilities")
    c.page.mouse.wheel(0, 900)
    c.hold(1300)


def appearance(c: Capture) -> None:
    c.goto("settings")
    c.click("外观")
    c.shot("settings-appearance")
    c.begin()
    for zh, en in [("手写连笔 · Caveat", "Handwritten · Caveat"), ("手写笔记 · Kalam", "Notebook · Kalam"), ("默认 · Inter", "Default · Inter")]:
        c.page.locator("label").filter(has=c.page.get_by_role("radio", name=c.word(zh, en), exact=True)).click()
        c.hold(1500)
    c.shot("settings-fonts")
    # Background and frosted glass: a gradient preset, kept per device (this browser context only).
    c.click("渐变预设", hold=900)
    c.click("晨雾" if c.theme == "light" else "极光", hold=1200)
    c.page.get_by_role("heading", name=c.word("背景与磨玻璃")).scroll_into_view_if_needed()
    c.hold(900)
    c.shot("settings-background")
    c.page.get_by_role("navigation", name=c.word("主导航")).get_by_role("button", name=c.word("工作台"), exact=True).click()
    c.hold(1600)
    c.shot("appearance-glass")


def entities(c: Capture) -> None:
    c.goto("entities")
    c.shot("entities")
    c.begin()
    kinds = c.page.get_by_role("group", name=c.word("资产种类"))
    for zh, en in (("场景", "Location"), ("道具", "Prop"), ("人物", "Character")):
        kinds.get_by_role("button", name=re.compile("^" + c.word(zh, en) + r" \d")).click()
        c.hold(900)
    c.goto("entities?entity=" + c.F["entities"]["buck"])
    c.hold(800)
    c.shot("entity-detail")
    c.click("让它说话", hold=1200)
    c.shot("entity-speak")
    c.hold(1000)
    c.escape()


def admin(c: Capture) -> None:
    c.warm("statistics")
    c.goto("admin")
    c.shot("admin")
    c.begin()
    c.click("成员", "Members", hold=1200)
    c.shot("admin-members")
    c.click("引擎", "Engines", hold=1200)
    c.shot("admin-engines")
    # A long list: the app's top bar stays put while only the page content scrolls.
    c.page.mouse.move(900, 600)
    for _ in range(4):
        c.page.mouse.wheel(0, 500)
        c.hold(400)
    c.hold(600)
    c.click("部署设置", hold=1200)
    c.shot("admin-deployment")
    c.hold(900)
    c.page.get_by_role("navigation", name=c.word("主导航")).get_by_role("button", name=c.word("统计"), exact=True).click()
    c.hold(1800)
    c.shot("statistics")
    c.hold(900)


def login(c: Capture) -> None:
    c.page.evaluate('localStorage.removeItem("mosael.auth.token")')
    c.page.reload(wait_until="networkidle")
    c.hold(1200)
    c.shot("login")
    c.begin()
    c.page.get_by_role("textbox").first.fill(SEED.USERNAME)
    c.hold(1800)


#: Scene name → (function, editor panel sizes). The name is the GIF / MP4 file name.
SCENES = {
    "home": home,
    "media-preview": media,
    "documents": documents,
    "timeline-edit": timeline_edit,
    "timeline-tools": timeline_tools,
    "subtitle-dub": subtitle_dub,
    "subtitle-panel": subtitle_panel,
    "export": export,
    "ai-studio": ai,
    "agent": agent,
    "workflows": workflows,
    "workflow-editor": workflow_editor,
    "workflow-templates": workflow_templates,
    "boards": boards,
    "board-cells": board_cells,
    "annotations": annotations,
    "notes": notes,
    "scenes": scenes,
    "entities": entities,
    "plugins": plugins,
    "plugin-market": plugin_market,
    "publishing": publishing,
    "scheduler": scheduler,
    "providers": providers,
    "appearance": appearance,
    "admin": admin,
    "login": login,
}

#: Scenes that show the Home greeting ("早上好" / "Good morning"), which follows the wall clock. With --clock
#: they all show the same time of day, whenever the batch happens to run.
CLOCK_SCENES = {"home", "appearance"}

#: Timeline height per scene: tall enough to show the subtitle tracks, short enough that the shortcut
#: sheet (anchored to the timeline toolbar) fits in a 900-pixel window.
TIMELINE_HEIGHT = {"timeline-tools": 262}


def encode(src: Path, target: Path, start: float, duration: float, gif: bool) -> None:
    base = ["ffmpeg", "-y", "-v", "error", "-ss", str(max(0, start)), "-i", str(src), "-t", str(duration), "-an"]
    if gif:
        base += ["-filter_complex", "fps=10,scale=960:-2:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=3", "-loop", "0"]
    else:
        base += ["-vf", "scale=1280:-2", "-c:v", "libx264", "-crf", "24", "-preset", "fast", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    subprocess.run(base + [str(target)], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--demo-dir", type=Path, help="the seed script's --dir (reads token.json and fixture.json)")
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--api", default=f"http://127.0.0.1:{SEED.API_PORT}")
    parser.add_argument("--app", default=f"http://127.0.0.1:{SEED.APP_PORT}")
    parser.add_argument("--theme", choices=["light", "dark", "both"], default="both")
    parser.add_argument("--locale", choices=["zh", "en", "both"], default="both")
    parser.add_argument("--only", default="", help="comma-separated scene names")
    parser.add_argument("--out", type=Path, help="trial run: write here, leave the public media and manifest alone")
    parser.add_argument("--clock", default="", help="wall-clock time for the scenes whose greeting depends on it (Home), e.g. 2026-10-04T10:30")
    args = parser.parse_args()
    for url in (args.api, args.app):
        if urlparse(url).hostname not in ("127.0.0.1", "localhost") or urlparse(url).port in (8800, 5173):
            parser.error("Capture only the isolated local demo environment (not the 8800 / 5173 dev servers).")
    token_file = args.token_file or (args.demo_dir / "token.json" if args.demo_dir else None)
    fixture_file = args.fixture or (args.demo_dir / "fixture.json" if args.demo_dir else None)
    if not token_file or not fixture_file:
        parser.error("Pass --demo-dir, or --token-file and --fixture.")
    token = json.loads(token_file.read_text())
    fixture = json.loads(fixture_file.read_text())
    only = [s for s in args.only.split(",") if s]
    unknown = [s for s in only if s not in SCENES]
    if unknown:
        parser.error(f"Unknown scenes: {unknown}")
    themes = ["light", "dark"] if args.theme == "both" else [args.theme]
    locales = ["zh", "en"] if args.locale == "both" else [args.locale]
    out = args.out or PUBLIC
    trial = args.out is not None
    clock = datetime.fromisoformat(args.clock) if args.clock else None
    manifest = PUBLIC / "capture-manifest.json"
    data = json.loads(manifest.read_text()) if manifest.exists() else {"captures": {}}
    version = json.loads((ROOT / "package.json").read_text())["version"]
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    captured_at = datetime.now(timezone.utc).isoformat()
    if not trial:
        data.update({"version": version, "documentedVersion": version, "sourceCommit": commit, "capturedAt": captured_at,
                     "viewport": VIEWPORT,
                     "note": "Live interface captures from an isolated demo backend seeded by website/scripts/seed-doc-demo.py. "
                             "Licensed sample footage and manually prepared editing exercise; no simulated AI replies, "
                             "tool successes or publishing successes."})
    with sync_playwright() as p, tempfile.TemporaryDirectory(prefix="mosael-record-") as tmp:
        browser = p.chromium.launch()
        for locale in locales:
            for theme in themes:
                for name, fn in SCENES.items():
                    if only and name not in only:
                        continue
                    print(f"{locale}/{theme}/{name}", flush=True)
                    context = browser.new_context(viewport=VIEWPORT, device_scale_factor=2, color_scheme=theme,
                                                  record_video_dir=tmp, record_video_size=VIEWPORT,
                                                  locale="zh-CN" if locale == "zh" else "en-US")
                    page = context.new_page()
                    if clock and name in CLOCK_SCENES:
                        page.clock.set_system_time(clock)
                    origin = time.monotonic()
                    page.goto(args.app, wait_until="domcontentloaded")
                    panels = {"left": {"media": 290, "transcript": 360, "subtitle": 380, "voice": 300}, "right": 280,
                              "timeline": TIMELINE_HEIGHT.get(name, 330)}
                    page.evaluate("""([api, token, theme, locale, workspace, panels]) => {
                        localStorage.setItem('mosael.server.url', api);
                        localStorage.setItem('mosael.auth.token', token);
                        localStorage.setItem('mosael.preferences', JSON.stringify({theme, locale, font: 'default'}));
                        localStorage.setItem('mosael:workspace', workspace);
                        localStorage.setItem('mosael.sidebar.collapsed', 'false');
                        localStorage.setItem('mosael.editor.panels.v2', JSON.stringify(panels));
                    }""", [args.api, token, theme, "zh-CN" if locale == "zh" else "en-US",
                           fixture["locales"][locale]["workspace"], panels])
                    page.reload(wait_until="networkidle")
                    c = Capture(page, locale, theme, fixture, args.app, out)
                    try:
                        fn(c)
                    except Exception:
                        failure = Path(tempfile.gettempdir()) / f"mosael-capture-failure-{locale}-{theme}-{name}"
                        page.screenshot(path=f"{failure}.png")
                        Path(f"{failure}.txt").write_text(page.locator("body").inner_text())
                        print(f"Failure screenshot: {failure}.png", flush=True)
                        raise
                    duration = time.monotonic() - c.start
                    video = page.video
                    context.close()
                    raw = Path(video.path())
                    for kind, ext in [("gifs", "gif"), ("videos", "mp4")]:
                        target = c.path(kind, f"{name}.{ext}")
                        encode(raw, target, c.start - origin, duration, ext == "gif")
                        c.outputs.append(target)
                    raw.unlink(missing_ok=True)
                    if name == "agent":
                        # Each language and theme starts from an empty conversation list again.
                        api = SEED.client(token, locale)
                        workspace = fixture["locales"][locale]["workspace"]
                        for session in SEED.ok(api.get("/agent/sessions", params={"workspace_id": workspace})):
                            SEED.ok(api.delete(f"/agent/sessions/{session['id']}"))
                    if trial:
                        continue
                    for target in c.outputs:
                        rel = str(target.relative_to(PUBLIC))
                        data["captures"][rel] = {
                            "scene": name, "locale": locale, "theme": theme, "version": version, "sourceCommit": commit,
                            "capturedAt": captured_at, "bytes": target.stat().st_size,
                            "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
                    manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        browser.close()
    print("Trial captures written to " + str(out) if trial else "Capture manifest saved.", flush=True)


if __name__ == "__main__":
    main()
