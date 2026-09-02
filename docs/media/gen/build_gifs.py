"""把一段真实操作录成 GIF —— 逐帧截图,不是录视频。

录视频再转码会把界面糊掉(GIF 只有 256 色,视频编码的块效应转过来更脏),而且时序取决于机器
当时的快慢。逐帧截图则是:**每一帧都是一次确定的界面状态**,停留多久由重复帧数说了算,同一段
演示在任何机器上都录出同一个东西。

    python3 docs/media/gen/build_gifs.py              # 全部
    python3 docs/media/gen/build_gifs.py subtitle-dub # 只录一个

前置:前端 dev server 在 `--base` 上跑着,后端在 8800 上跑着,并且装了 ffmpeg。
规格对齐现有资产:2880×1520、10 fps。
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OUT_DOCS = REPO / "docs" / "media"
OUT_SITE = REPO / "website" / "public" / "media" / "gifs"
#: 官网的 gif 同样有明暗两套 —— 只更新一半,切到暗色的读者看到的仍是旧界面。
OUT_SITE_DARK = OUT_SITE / "dark"

WIDTH, HEIGHT, SCALE, FPS = 1440, 760, 2, 10

sys.path.insert(0, str(HERE))

#: 一段演示 = 一串 (在页面里跑的 JS, 这一步停留几帧)。
#: `None` 表示这一步什么都不做,只是让画面停一会儿 —— 观众需要时间看清刚发生了什么。
Step = tuple[str | None, int]

OPEN_DEMO_PROJECT: list[Step] = [
    ("[...document.querySelectorAll('button,a')].find(e=>/宣传片/.test(e.textContent||''))?.click()", 2),
    ("[...document.querySelectorAll('button,a')].find(e=>/打开剪辑/.test(e.textContent||''))?.click()", 8),
]

DEMOS: dict[str, dict] = {
    "subtitle-dub": {
        "route": "#/home",
        "steps": [
            *OPEN_DEMO_PROJECT,
            ("[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='字幕')?.click()", 8),
            ("document.querySelector('button[aria-label=\"给这一条配音\"]')?.click()", 10),
            # 打开「缩放到段落长度」——这一项是整个功能里唯一需要用户判断的地方。
            ("document.querySelector('[data-radix-popper-content-wrapper] [role=switch]')?.click()", 10),
        ],
    },
    "agent-trace": {
        "route": "#/ai",
        "steps": [
            (None, 6),
            ("[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='轨迹')?.click()", 12),
            # 切到「时长」投影:同一段轨迹换一种读法(时间都去哪了)。
            ("[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='时长')?.click()", 14),
        ],
    },
}


def record(base: str, token: str, name: str, theme: str = "light") -> Path:
    from playwright.sync_api import sync_playwright

    demo = DEMOS[name]
    frames = Path(tempfile.mkdtemp(prefix=f"os-gif-{name}-"))
    index = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": WIDTH, "height": HEIGHT},
            device_scale_factor=SCALE,
            locale="zh-CN",
            color_scheme=theme,
        )
        context.add_init_script(
            f"window.localStorage.setItem('mosael.auth.token', {token!r});"
            f"window.localStorage.setItem('mosael.preferences', "
            f"JSON.stringify({{theme: {theme!r}, locale: 'zh-CN'}}));"
        )
        page = context.new_page()
        page.goto(f"{base}/{demo['route']}", wait_until="networkidle")
        page.wait_for_timeout(1500)
        for script, hold in demo["steps"]:
            if script:
                page.evaluate(script)
            # 让这一步的界面先稳定下来,再开始留帧 —— 否则第一帧会拍到动画中途。
            page.wait_for_timeout(500)
            for _ in range(hold):
                page.screenshot(path=str(frames / f"{index:04d}.png"))
                index += 1
        browser.close()
    return frames


def to_gif(frames: Path, target: Path) -> None:
    """两趟 palettegen:一趟统计全局调色板,一趟按它抖动。

    一趟直出的话,界面里大片相近的浅灰会被量化成条带 —— 而产品截图恰恰全是这种大色块。
    """
    palette = frames / "palette.png"
    common = ["ffmpeg", "-y", "-v", "error", "-framerate", str(FPS), "-i", str(frames / "%04d.png")]
    subprocess.run([*common, "-vf", "palettegen=stats_mode=diff", str(palette)], check=True)
    subprocess.run(
        [*common, "-i", str(palette), "-lavfi", "paletteuse=dither=bayer:bayer_scale=3", str(target)],
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="*")
    parser.add_argument("--base", default="http://127.0.0.1:5173")
    args = parser.parse_args()

    if not shutil.which("ffmpeg"):
        raise SystemExit("需要 ffmpeg")
    names = args.names or list(DEMOS)
    unknown = [n for n in names if n not in DEMOS]
    if unknown:
        raise SystemExit(f"不认识:{unknown};可选:{list(DEMOS)}")

    from build_screens import mint_token

    token = mint_token()
    OUT_SITE.mkdir(parents=True, exist_ok=True)
    OUT_SITE_DARK.mkdir(parents=True, exist_ok=True)
    for theme in ("light", "dark"):
        for name in names:
            frames = record(args.base.rstrip("/"), token, name, theme)
            target = (OUT_DOCS if theme == "light" else OUT_SITE_DARK) / f"{name}.gif"
            to_gif(frames, target)
            if theme == "light":
                (OUT_SITE / f"{name}.gif").write_bytes(target.read_bytes())
            shutil.rmtree(frames, ignore_errors=True)
            print(f"  {theme:5s} {name:14s} → {target.relative_to(REPO)}  {target.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
