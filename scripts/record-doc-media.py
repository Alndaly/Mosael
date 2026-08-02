#!/usr/bin/env python3
"""给文档录截图与 GIF —— 对着**真实界面**跑,不是画出来的。

为什么是脚本而不是手工录屏:配图会过期,而过期的配图比没有配图更糟 —— 用户照着一张老截图
找不到按钮,会以为是自己的问题。脚本化之后,界面改了就重跑一次,几分钟的事。

用法(需要先起好前端与一个**独立数据目录**的后端,别对着自己的真实数据录):

    OPEN_STUDIO_DATA_DIR=/tmp/demo-data backend/.venv/bin/python -m uvicorn app.main:app --port 8801
    pnpm --dir frontend dev                      # 5173,CORS 允许的源
    backend/.venv/bin/python scripts/record-doc-media.py --token <会话令牌>

产物落在 docs/media/,并分发到官网的 public/(见下面的 publish)。
GIF 由帧序列经 ffmpeg 合成(调色板两遍法,否则渐变会脏)。

**默认两套都录**(`--theme both`)。站点按当前主题选图:浅色页面配浅色截图,深色页面配
深色截图 —— 一张浅色截图贴在深色版面里,会像是从别处抠来的。深色那套落在输出目录的
`dark/` 子目录,文件名与浅色一致。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
#: 两处媒体各有各的消费者,别合并:
#:   docs/media           仓库 README(GitHub 上直接渲染,只认仓库内相对路径)
#:   website/public/media 官网(Next 的 public/,按 URL 引用;next/image 自己做优化)
MEDIA = ROOT / "docs" / "media"
WEB_GIFS = ROOT / "website" / "public" / "media" / "gifs"
WEB_SHOTS = ROOT / "website" / "public" / "media" / "screens"

#: 录制视口。宽度按文档站正文宽度取,高度取到内容底边即可 —— 留一大片空白的截图在文档里
#: 会把正文推得很散,读者还得滚过去才看到下一段。
VIEWPORT = {"width": 1440, "height": 760}
#: GIF 帧率。界面演示不需要高帧率,10 帧足够看清每一步,体积只有 24 帧的四成。
FPS = 10
#: 剪辑页的面板宽度。素材栏取 320 而不是默认的 252:窄栏下四个中文页签放不下,会滚掉
#: 「配音」半个字 —— 那是正常行为(见 EditorView 的 LeftTabs),但配图里一个被截断的页签
#: 只会让人以为界面坏了。和视口、主题一样,这是"以什么状态开拍"的一部分。
EDITOR_PANELS = {"left": {"media": 320, "transcript": 420, "subtitle": 320, "voice": 320}, "right": 264, "timeline": 252}


def gif_from_frames(frames: Path, out: Path, fps: int = FPS) -> None:
    """帧序列 → GIF。两遍法:先统计调色板再编码,否则渐变和阴影会出现色带。"""
    palette = frames / "palette.png"
    common = ["-y", "-loglevel", "error", "-framerate", str(fps)]
    subprocess.run(
        ["ffmpeg", *common, "-i", str(frames / "%04d.png"), "-vf", "palettegen=stats_mode=diff", str(palette)],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg", *common, "-i", str(frames / "%04d.png"), "-i", str(palette),
            "-lavfi", "paletteuse=dither=bayer:bayer_scale=3",
            str(out),
        ],
        check=True,
    )
    print(f"  → {out.relative_to(ROOT)}  {out.stat().st_size // 1024} KB")


#: 当前这一轮录的是哪套主题。深色那套落在各目录的 `dark/` 子目录里,浅色留在原地 ——
#: 于是所有既有的引用(文档正文里的 `/media/screens/x.png`)不用改一个字,而站点在夜档下
#: 去同名的 `dark/` 里找一张同名图,找不到就退回浅色那张。
CURRENT_THEME = "light"


def publish(src: Path, name: str, *, gif: bool = False) -> None:
    """把一件产物送进官网的 public/。深色那套进 `dark/` 子目录。"""
    target = (WEB_GIFS if gif else WEB_SHOTS) / ("dark" if CURRENT_THEME == "dark" else "") / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, target)
    print(f"  → {target.relative_to(ROOT)}")


class Recorder:
    """按步录制:每 `hold` 帧重复一张截图,让观众有时间看清这一步。"""

    def __init__(self, page: Page, frames: Path) -> None:
        self.page = page
        self.frames = frames
        self.index = 0

    def shot(self, hold: int = 6) -> None:
        self.index += 1
        first = self.frames / f"{self.index:04d}.png"
        self.page.screenshot(path=str(first))
        for _ in range(hold - 1):
            self.index += 1
            shutil.copy(first, self.frames / f"{self.index:04d}.png")


def open_app(page: Page, base: str, api: str, token: str, theme: str) -> None:
    """把服务器地址、令牌和主题一次性写进 localStorage,再重载让应用带着它们启动。

    主题写的是 `openstudio.preferences`(见 frontend/src/app/preferences.tsx)——
    不能只靠 Playwright 的 `color_scheme`:应用自己存偏好,默认 light,系统色不参与。
    """
    page.goto(base, wait_until="domcontentloaded")
    page.evaluate(
        "([api, token, theme, panels]) => { localStorage.setItem('openstudio.server.url', api);"
        " localStorage.setItem('openstudio.auth.token', token);"
        " localStorage.setItem('openstudio.preferences', JSON.stringify({ theme, locale: 'zh-CN' }));"
        " localStorage.setItem('openstudio.editor.panels.v2', panels); }",
        [api, token, theme, json.dumps(EDITOR_PANELS)],
    )
    page.goto(base, wait_until="networkidle")
    # 主题切换会给 <html> 加 class,等它落定再拍 —— 否则第一帧可能还是浅色。
    if theme == "dark":
        page.wait_for_function("() => document.documentElement.classList.contains('dark')", timeout=5000)
    page.wait_for_timeout(400)


def record_plugins(page: Page, tmp: Path) -> None:
    """插件:包 → 连接 → 能力 三层,以及"默认不开放"的勾选。"""
    frames = tmp / "plugins"
    frames.mkdir()
    rec = Recorder(page, frames)

    page.goto(page.url.split("#")[0] + "#/plugins", wait_until="networkidle")
    page.wait_for_timeout(600)
    rec.shot(10)  # 三层结构:已安装的包 / 这个包的连接 / 连接下的能力

    toggle = page.get_by_role("switch").first
    if toggle.count():
        toggle.click()
        page.wait_for_timeout(700)
        rec.shot(10)  # 启用之后,工具才真正暴露给智能体与工作流

    page.screenshot(path=str(MEDIA / "plugins-overview.png"))
    print(f"  → {(MEDIA / 'plugins-overview.png').relative_to(ROOT)}")

    search = page.get_by_placeholder("搜索").first
    if search.count():
        search.click()
        for ch in "hash":
            search.type(ch, delay=90)
            rec.shot(1)
        page.wait_for_timeout(500)
        rec.shot(12)  # 工具多的时候靠搜索找,不靠翻

    gif_from_frames(frames, MEDIA / "plugins-three-layers.gif")
    publish(MEDIA / "plugins-three-layers.gif", "plugins.gif", gif=True)
    publish(MEDIA / "plugins-overview.png", "plugins.png")


def record_workflows(page: Page, tmp: Path) -> None:
    """工作流画布:节点分组面板、连线、执行历史。"""
    frames = tmp / "workflows"
    frames.mkdir()
    rec = Recorder(page, frames)

    page.goto(page.url.split("#")[0] + "#/workflows", wait_until="networkidle")
    page.wait_for_timeout(1200)
    # 先「适应视图」:默认缩放下节点挤在中间一小块,截图里大半是空画布。
    fit = page.locator("button.react-flow__controls-fitview")
    if fit.count():
        fit.click()
        page.wait_for_timeout(800)
    rec.shot(10)

    # 打开节点面板 —— 分组 + 每行一句说明是这一轮改的重点
    add = page.get_by_role("button", name=re.compile("添加节点|节点")).first
    if add.count():
        add.click()
        page.wait_for_timeout(700)
        rec.shot(14)
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        rec.shot(6)

    gif_from_frames(frames, MEDIA / "workflows-canvas.gif")
    publish(MEDIA / "workflows-canvas.gif", "workflows.gif", gif=True)
    page.screenshot(path=str(MEDIA / "workflows-canvas.png"))
    publish(MEDIA / "workflows-canvas.png", "workflows.png")


def record_home(page: Page, tmp: Path) -> None:
    """首页概览:项目/素材/任务/用量一屏。"""
    page.goto(page.url.split("#")[0] + "#/", wait_until="networkidle")
    page.wait_for_timeout(1000)
    page.screenshot(path=str(MEDIA / "home.png"))
    publish(MEDIA / "home.png", "home.png")


def record_media(page: Page, tmp: Path) -> None:
    """素材库:导入进来的片段。"""
    page.goto(page.url.split("#")[0] + "#/media", wait_until="networkidle")
    page.wait_for_timeout(1000)
    page.screenshot(path=str(MEDIA / "media.png"))
    publish(MEDIA / "media.png", "media.png")


def record_agent(page: Page, tmp: Path) -> None:
    """智能体页。

    **不造假对话**:演示实例没有配供应商,跑不出真实回答,而往库里插几条假消息去凑一张
    "看起来很能干"的截图,是在文档里说一件没发生的事。这里拍的是真实的初始状态 —— 那也正是
    新用户第一次打开时看到的东西。能力面板渲染自工具清单,不依赖对话,是这一轮变化最大的部分。
    """
    page.goto(page.url.split("#")[0] + "#/ai", wait_until="networkidle")
    page.wait_for_timeout(1200)
    page.screenshot(path=str(MEDIA / "agent.png"))
    publish(MEDIA / "agent.png", "ai-chat.png")


def _goto(page: Page, view: str, wait: int = 1200) -> None:
    """切到某个视图,并**强制重新挂载**。

    路由是 hash 式的(见 frontend/src/app/App.tsx 的 readHash)。只改 hash 时浏览器不会重新
    加载文档,`wait_until="networkidle"` 于是立刻返回 —— 上一段场景留下的界面状态和正在飞的
    请求都还在,下一段就可能拍到一个半渲染的页面,或者压根找不到要点的按钮。
    多花一次重载换一个干净的起点,值得。
    """
    page.goto(page.url.split("#")[0] + f"#/{view}", wait_until="domcontentloaded")
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(wait)


def _timeline_clips(page: Page) -> list:
    """时间线上的片段,按左到右排好。

    片段是带 title 的 `div[role=button]`(见 timeline/TimelineClip.tsx),但左侧素材池的
    卡片也是这个形状 —— 只按这个选择器取会点到素材、把素材列表滚走,而片段一个都没选中。
    时间线根节点带 `data-tool`(select / blade),用它限定范围:那是个功能属性,不是样式,
    改版面不会把它顺手删掉。
    """
    found = []
    for handle in page.locator('[data-tool] div[role="button"][title]').all():
        box = handle.bounding_box()
        if box and box["width"] > 12:
            found.append((box["x"], handle))
    return [handle for _, handle in sorted(found, key=lambda item: item[0])]


def record_editor(page: Page, tmp: Path) -> None:
    """剪辑页 —— 官网首屏那张大图,也是文档里最常出现的一张。

    **从首页点进去**,不写死项目 id:id 是每台机器上各自生成的,写死等于这个脚本只能在
    录制过的那台机器上跑。
    """
    _goto(page, "home")
    card = page.get_by_role("button", name=re.compile("打开剪辑|Open editor")).first
    try:
        card.wait_for(state="visible", timeout=8000)
    except Exception:
        print("  跳过 editor:首页没有项目卡片")
        return
    card.click()
    page.wait_for_timeout(2500)  # 等时间线和监看器把首帧解出来

    # **先选中一个片段**:右侧检查器只在选中时才占栏(EditorView 的 showInspector),
    # 不选就拍出一张"左栏 + 监看器 + 时间线"的图,而编辑器真正在用的时候是四栏都在。
    clips = _timeline_clips(page)
    if clips:
        clips[0].click()
        page.wait_for_timeout(900)
    else:
        print("  editor:时间线上没有片段,右侧检查器不会出现")

    page.screenshot(path=str(MEDIA / "editor.png"))
    publish(MEDIA / "editor.png", "editor.png")

    frames = tmp / "timeline"
    frames.mkdir()
    rec = Recorder(page, frames)
    rec.shot(12)  # 起手:素材 / 监看器 / 时间线 / 检查器 四栏都在

    # 逐个点过去 —— 这段录屏要说明的是"选中谁,右边就跟着换成谁的参数"。
    for clip in clips[1:4]:
        clip.click()
        page.wait_for_timeout(500)
        rec.shot(9)

    gif_from_frames(frames, MEDIA / "timeline-edit.gif")
    publish(MEDIA / "timeline-edit.gif", "timeline-edit.gif", gif=True)


def record_kb(page: Page, tmp: Path) -> None:
    """知识库:数据集与文档列表。"""
    _goto(page, "kb")
    page.screenshot(path=str(MEDIA / "kb.png"))
    publish(MEDIA / "kb.png", "kb.png")


def record_publish(page: Page, tmp: Path) -> None:
    """发布页:发布记录与账号矩阵两个页签。"""
    _goto(page, "publish")
    page.screenshot(path=str(MEDIA / "publish.png"))
    publish(MEDIA / "publish.png", "publish.png")


def record_settings(page: Page, tmp: Path) -> None:
    """设置页,以及「AI 绘图」那一段的默认模型 + 供应商列表。

    两张图都来自设置页,分两次拍:一张是整页的样子,一张是模型分区 —— 文档里
    「配置模型服务商」那一节讲的就是后者。
    """
    _goto(page, "settings")
    page.screenshot(path=str(MEDIA / "settings.png"))
    publish(MEDIA / "settings.png", "settings.png")

    entry = page.get_by_role("button", name=re.compile("AI 绘图|AI 对话")).first
    if entry.count():
        entry.click()
        page.wait_for_timeout(900)
    page.screenshot(path=str(MEDIA / "settings-models.png"))
    publish(MEDIA / "settings-models.png", "settings-models.png")


def record_ai_generate(page: Page, tmp: Path) -> None:
    """AI 工作台的生成模式:结果流 + 右侧引擎参数。

    对话模式那张由 record_agent 负责;这里只切到生成模式。切不过去就跳过 ——
    宁可少一张图,也不要发一张停在对话模式、却在文档里被说成"生成模式"的截图。
    """
    _goto(page, "ai")
    toggle = page.get_by_role("tab", name=re.compile("^生成$|^Generate$")).first
    try:
        toggle.wait_for(state="visible", timeout=8000)
    except Exception:
        print("  跳过 ai-generate:没找到切到生成模式的入口")
        return
    toggle.click()
    page.wait_for_timeout(1200)
    page.screenshot(path=str(MEDIA / "ai-generate.png"))
    publish(MEDIA / "ai-generate.png", "ai-generate.png")


def record_home_to_editor(page: Page, tmp: Path) -> None:
    """首页 → 剪辑:一步直达,中间不弹任何对话框。"""
    frames = tmp / "home"
    frames.mkdir()
    rec = Recorder(page, frames)

    _goto(page, "home")
    rec.shot(12)  # 工作区总览:统计、图表、项目列表
    card = page.get_by_role("button", name=re.compile("打开剪辑|Open editor")).first
    try:
        card.wait_for(state="visible", timeout=8000)
    except Exception:
        print("  跳过 home.gif:首页没有项目卡片")
        return
    card.hover()
    rec.shot(5)
    card.click()
    page.wait_for_timeout(2200)
    rec.shot(14)  # 落进编辑器

    gif_from_frames(frames, MEDIA / "home.gif")
    publish(MEDIA / "home.gif", "home.gif", gif=True)


def _settings_section(page: Page, pattern: str):
    """设置页左栏的分区入口。各分区是按钮,名字就是分区名。"""
    return page.get_by_role("button", name=re.compile(pattern)).first


def record_providers(page: Page, tmp: Path) -> None:
    """设置 → 各能力分区的供应商配置入口。"""
    frames = tmp / "providers"
    frames.mkdir()
    rec = Recorder(page, frames)

    _goto(page, "settings")
    rec.shot(8)
    for name in ("AI 对话|AI chat", "AI 绘图|AI image", "AI 音频|AI audio"):
        entry = _settings_section(page, name)
        if not entry.count():
            continue
        entry.click()
        page.wait_for_timeout(800)
        rec.shot(12)  # 每个分区各自的默认模型 + 供应商列表

    gif_from_frames(frames, MEDIA / "providers.gif")
    publish(MEDIA / "providers.gif", "providers.gif", gif=True)


def record_asr_models(page: Page, tmp: Path) -> None:
    """设置 → 本地转写模型:按需下载,不是开箱就占几个 G。"""
    frames = tmp / "asr"
    frames.mkdir()
    rec = Recorder(page, frames)

    _goto(page, "settings")
    entry = _settings_section(page, "声音克隆|转写|语音|ASR|Speech")
    if not entry.count():
        print("  跳过 asr-models.gif:设置里没找到转写分区")
        return
    entry.click()
    page.wait_for_timeout(900)
    rec.shot(16)
    page.mouse.wheel(0, 400)
    page.wait_for_timeout(600)
    rec.shot(12)

    page.screenshot(path=str(MEDIA / "settings-asr.png"))
    gif_from_frames(frames, MEDIA / "asr-models.gif")
    publish(MEDIA / "asr-models.gif", "asr-models.gif", gif=True)


def record_publishing(page: Page, tmp: Path) -> None:
    """发布页:发布记录 ↔ 账号矩阵两个页签。"""
    frames = tmp / "publishing"
    frames.mkdir()
    rec = Recorder(page, frames)

    _goto(page, "publish")
    rec.shot(12)
    for name in ("账号矩阵|Accounts", "发布记录|Records|History"):
        tab = page.get_by_role("tab", name=re.compile(name)).first
        if not tab.count():
            tab = page.get_by_role("button", name=re.compile(name)).first
        if not tab.count():
            continue
        tab.click()
        page.wait_for_timeout(800)
        rec.shot(12)

    gif_from_frames(frames, MEDIA / "publishing.gif")
    publish(MEDIA / "publishing.gif", "publishing.gif", gif=True)


def record_knowledge_base(page: Page, tmp: Path) -> None:
    """知识库:数据集 → 文档 → 召回测试。"""
    frames = tmp / "kb"
    frames.mkdir()
    rec = Recorder(page, frames)

    _goto(page, "kb")
    rec.shot(12)
    for name in ("文档|Documents", "召回测试|Retrieval", "知识图谱|Graph"):
        tab = page.get_by_role("tab", name=re.compile(name)).first
        if not tab.count():
            tab = page.get_by_role("button", name=re.compile(name)).first
        if not tab.count():
            continue
        tab.click()
        page.wait_for_timeout(700)
        rec.shot(10)

    gif_from_frames(frames, MEDIA / "knowledge-base.gif")
    publish(MEDIA / "knowledge-base.gif", "knowledge-base.gif", gif=True)


def record_ai_studio(page: Page, tmp: Path) -> None:
    """AI 工作台:对话 ↔ 生成两个模式,并在生成模式里敲一句提示词。

    **只敲不发**:发出去要真的调用供应商,既费钱也让这段录屏依赖网络。
    """
    frames = tmp / "ai-studio"
    frames.mkdir()
    rec = Recorder(page, frames)

    _goto(page, "ai")
    rec.shot(10)
    tab = page.get_by_role("tab", name=re.compile("^生成$|^Generate$")).first
    try:
        tab.wait_for(state="visible", timeout=8000)
    except Exception:
        print("  跳过 ai-studio.gif:没找到切到生成模式的入口")
        return
    tab.click()
    page.wait_for_timeout(1000)
    rec.shot(12)

    box = page.get_by_role("textbox").first
    if box.count():
        box.click()
        for ch in "黄昏的海边,一个人走过":
            box.type(ch, delay=70)
            rec.shot(1)
        page.wait_for_timeout(500)
        rec.shot(14)

    gif_from_frames(frames, MEDIA / "ai-studio.gif")
    publish(MEDIA / "ai-studio.gif", "ai-studio.gif", gif=True)


def record_login(page: Page, tmp: Path) -> None:
    """登录页 —— 新用户看到的第一屏。

    **临时把令牌摘掉再装回去**:登录态存在 localStorage 里,不清掉就永远进不到这一屏。
    放在场景表的最后,并且拍完立刻还原 —— 否则后面的场景全都会被踢回登录页。
    """
    base = page.url.split("#")[0]
    token = page.evaluate("() => localStorage.getItem('openstudio.auth.token')")
    frames = tmp / "login"
    frames.mkdir()
    rec = Recorder(page, frames)

    try:
        page.evaluate("() => localStorage.removeItem('openstudio.auth.token')")
        page.goto(base, wait_until="networkidle")
        page.wait_for_timeout(1200)
        page.screenshot(path=str(MEDIA / "login.png"))
        publish(MEDIA / "login.png", "login.png")

        rec.shot(14)
        user = page.get_by_role("textbox").first
        if user.count():
            user.click()
            for ch in "demo":
                user.type(ch, delay=110)
                rec.shot(1)
            page.wait_for_timeout(400)
            rec.shot(12)
        gif_from_frames(frames, MEDIA / "login.gif")
        publish(MEDIA / "login.gif", "login.gif", gif=True)
    finally:
        # 还原登录态。放在 finally 里:中间任何一步抛错都不能把这台机器留在登出状态。
        if token:
            page.evaluate("(t) => localStorage.setItem('openstudio.auth.token', t)", token)
        page.goto(base, wait_until="networkidle")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True, help="演示实例的会话令牌")
    parser.add_argument("--base", default="http://localhost:5173")
    parser.add_argument("--api", default="http://127.0.0.1:8801")
    parser.add_argument("--only", default="", help="只录某一段(plugins/…)")
    #: 配图统一走深色。官网、README、文档三处的版面都是深底为主,而浅色截图贴进去会像
    #: 从别处抠来的 —— 而且应用本身的重点(时间线、监看器、画布)在深色下对比更好读。
    #: 默认**两套都录**。站点按当前主题选图:浅色页面配浅色截图,深色页面配深色截图 ——
    #: 一张浅色截图贴在深色版面里,会像是从别处抠来的。
    parser.add_argument("--theme", default="both", choices=["both", "dark", "light"], help="录制用的应用主题")
    args = parser.parse_args()

    for d in (MEDIA, WEB_GIFS, WEB_SHOTS):
        d.mkdir(parents=True, exist_ok=True)
    scenes = {"home": record_home, "media": record_media, "editor": record_editor,
              "plugins": record_plugins, "workflows": record_workflows,
              "agent": record_agent, "ai-generate": record_ai_generate,
              "kb": record_kb, "publish": record_publish, "settings": record_settings,
              "home-gif": record_home_to_editor, "providers": record_providers,
              "asr": record_asr_models, "publishing": record_publishing,
              "knowledge-base": record_knowledge_base, "ai-studio": record_ai_studio,
              # login 必须排最后:它会临时清掉登录态。
              "login": record_login}
    if args.only:
        scenes = {k: v for k, v in scenes.items() if k == args.only}

    themes = ["light", "dark"] if args.theme == "both" else [args.theme]
    global CURRENT_THEME

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for theme in themes:
            CURRENT_THEME = theme
            print(f"=== {theme} ===")
            page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2, color_scheme=theme)
            open_app(page, args.base, args.api, args.token, theme)
            for name, fn in scenes.items():
                print(f"录制 {name} …")
                with tempfile.TemporaryDirectory(prefix="os-doc-media-") as tmp:
                    fn(page, Path(tmp))
            page.close()
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
