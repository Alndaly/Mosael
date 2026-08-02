#!/usr/bin/env python3
"""给文档录截图与 GIF —— 对着**真实界面**跑,不是画出来的。

为什么是脚本而不是手工录屏:配图会过期,而过期的配图比没有配图更糟 —— 用户照着一张老截图
找不到按钮,会以为是自己的问题。脚本化之后,界面改了就重跑一次,几分钟的事。

用法(需要先起好前端与一个**独立数据目录**的后端,别对着自己的真实数据录):

    OPEN_STUDIO_DATA_DIR=/tmp/demo-data backend/.venv/bin/python -m uvicorn app.main:app --port 8801
    pnpm --dir frontend dev                      # 5173,CORS 允许的源
    backend/.venv/bin/python scripts/record-doc-media.py --token <会话令牌>

产物落在 docs/media/。GIF 由帧序列经 ffmpeg 合成(调色板两遍法,否则渐变会脏)。
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
#: 三处媒体各有各的消费者,别合并:
#:   docs/media          仓库 README(GitHub 上直接渲染,只认仓库内相对路径)
#:   docs-site/src/assets 旧文档站(Astro 做尺寸优化,必须是 src/ 下的相对引用)
#:   website/public/media 新官网(Next 的 public/,按 URL 引用;next/image 自己做优化)
#: docs-site 正在被 website/ 取代(见 docs/WEBSITE_REBUILD.md)。迁移期间两边都写 ——
#: 少写一边的后果是某个站悄悄停在半年前的界面上,而这正是这个脚本存在的理由。
MEDIA = ROOT / "docs" / "media"
SITE_GIFS = ROOT / "docs-site" / "src" / "assets" / "gifs"
SITE_SHOTS = ROOT / "docs-site" / "src" / "assets" / "screens"
WEB_GIFS = ROOT / "website" / "public" / "media" / "gifs"
WEB_SHOTS = ROOT / "website" / "public" / "media" / "screens"

#: 录制视口。宽度按文档站正文宽度取,高度取到内容底边即可 —— 留一大片空白的截图在文档里
#: 会把正文推得很散,读者还得滚过去才看到下一段。
VIEWPORT = {"width": 1440, "height": 760}
#: GIF 帧率。界面演示不需要高帧率,10 帧足够看清每一步,体积只有 24 帧的四成。
FPS = 10


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


def publish(src: Path, name: str, *, gif: bool = False) -> None:
    """把一件产物分发到两个站点,同名落地。"""
    targets = [(SITE_GIFS if gif else SITE_SHOTS) / name, (WEB_GIFS if gif else WEB_SHOTS) / name]
    for target in targets:
        shutil.copy(src, target)
    print("  → " + " / ".join(str(t.relative_to(ROOT)) for t in targets))


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


def open_app(page: Page, base: str, api: str, token: str) -> None:
    page.goto(base, wait_until="domcontentloaded")
    page.evaluate(
        "([api, token]) => { localStorage.setItem('openstudio.server.url', api);"
        " localStorage.setItem('openstudio.auth.token', token); }",
        [api, token],
    )
    page.goto(base, wait_until="networkidle")


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True, help="演示实例的会话令牌")
    parser.add_argument("--base", default="http://localhost:5173")
    parser.add_argument("--api", default="http://127.0.0.1:8801")
    parser.add_argument("--only", default="", help="只录某一段(plugins/…)")
    args = parser.parse_args()

    for d in (MEDIA, SITE_GIFS, SITE_SHOTS, WEB_GIFS, WEB_SHOTS):
        d.mkdir(parents=True, exist_ok=True)
    scenes = {"home": record_home, "media": record_media,
              "plugins": record_plugins, "workflows": record_workflows,
              "agent": record_agent}
    if args.only:
        scenes = {k: v for k, v in scenes.items() if k == args.only}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2)
        open_app(page, args.base, args.api, args.token)
        for name, fn in scenes.items():
            print(f"录制 {name} …")
            with tempfile.TemporaryDirectory(prefix="os-doc-media-") as tmp:
                fn(page, Path(tmp))
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
