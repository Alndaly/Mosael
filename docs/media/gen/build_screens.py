"""把产品界面截成文档用的图 —— 可重复,而不是每次手动截一遍。

此前 `gen/screens/README.md` 写的是「把新的同名 png 丢进来」,也就是靠人工截图。于是截图会
**悄悄过时**:仓库里那批停在 2026-08-03,而两周里加了轨迹视图、字幕配音、平台专属发布选项,
文档配的还是旧界面。人工流程没错,只是没人会为了一次改动重截十二张。

规格对齐现有资产:视口 1440×760、`device_scale_factor=2` → 2880×1520(retina)。**布局按 1440
排版**,而不是把视口开到 2880 —— 后者出的图尺寸对,但界面是另一种排布,不是用户看到的那个。

登录态:直接向本机后端铸一个会话令牌塞进 localStorage。不走登录表单,是因为那需要密码;
而这台机器上的后端本来就属于运行这个脚本的人。

    python3 docs/media/gen/build_screens.py            # 全部
    python3 docs/media/gen/build_screens.py editor     # 只重截某几张

前置:前端 dev server(或打包后的静态站)在 `--base` 上跑着,后端在 8800 上跑着。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OUT_DOCS = REPO / "docs" / "media"
OUT_SITE = REPO / "website" / "public" / "media" / "screens"
#: 官网每张图都有明暗两套(`screens/` 与 `screens/dark/`)。只更新一半的话,切到暗色的读者
#: 看到的仍是旧界面 —— 而那恰恰是最不容易被发现的过时。
OUT_SITE_DARK = OUT_SITE / "dark"

WIDTH, HEIGHT, SCALE = 1440, 760, 2

#: 截图清单:文件名 → (页面路由, 进到那一屏还要做什么)。
#: `steps` 是一串在页面里跑的 JS,每条之间等一小会儿 —— 用 JS 而不是坐标点击,是因为坐标
#: 会随布局变,而这个脚本的价值正是「改了界面也还能重跑」。
SHOTS: dict[str, dict] = {
    "home": {"route": "#/home"},
    "media": {"route": "#/media"},
    "editor": {
        "route": "#/home",
        # 演示工程:干净的示例素材,不会把真实项目的内容带进文档。
        "steps": [
            "[...document.querySelectorAll('button,a')].find(e=>/宣传片/.test(e.textContent||''))?.click()",
            "[...document.querySelectorAll('button,a')].find(e=>/打开剪辑/.test(e.textContent||''))?.click()",
        ],
    },
    "subtitles": {
        "route": "#/home",
        "steps": [
            "[...document.querySelectorAll('button,a')].find(e=>/宣传片/.test(e.textContent||''))?.click()",
            "[...document.querySelectorAll('button,a')].find(e=>/打开剪辑/.test(e.textContent||''))?.click()",
            "[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='字幕')?.click()",
        ],
    },
    "ai-chat": {"route": "#/ai"},
    "agent-trace": {
        "route": "#/ai",
        # 轨迹视图:同一个会话的另一种读法(它做了什么、时间花在哪)。
        "steps": ["[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='轨迹')?.click()"],
    },
    "subtitle-dub": {
        "route": "#/home",
        "steps": [
            "[...document.querySelectorAll('button,a')].find(e=>/宣传片/.test(e.textContent||''))?.click()",
            "[...document.querySelectorAll('button,a')].find(e=>/打开剪辑/.test(e.textContent||''))?.click()",
            "[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='字幕')?.click()",
            "document.querySelector('button[aria-label=\"给这一条配音\"]')?.click()",
        ],
    },
    "url-import": {
        "route": "#/media",
        # 从链接导入:探测一条真实视频,让截图里有内容而不是空表单。
        "steps": [
            "[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='从链接导入')?.click()",
            """(() => {
              const input = [...document.querySelectorAll('input')].find(i => (i.placeholder||'').includes('链接'));
              const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
              setter.call(input, 'https://www.youtube.com/watch?v=aqz-KE-bpKQ');
              input.dispatchEvent(new Event('input', {bubbles: true}));
              [...document.querySelectorAll('button')].find(b => b.textContent.trim() === '获取列表')?.click();
            })()""",
        ],
        # 探测要出网,给它比别的截图更长的等待。
        "settle_ms": 14000,
    },
    "workflows": {"route": "#/workflows"},
    "publish": {"route": "#/publish"},
    "settings": {"route": "#/settings"},
}


def mint_token() -> str:
    """给这台机器的第一个用户铸一个会话令牌。"""
    sys.path.insert(0, str(REPO / "backend"))
    os.environ.setdefault("MOSAEL_DATA_DIR", str(Path.home() / ".mosael"))
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.db.models import User
    from app.core.security import mint_service_session

    with SessionLocal() as db:
        user = db.scalars(select(User).order_by(User.created_at)).first()
        if user is None:
            raise SystemExit("这个部署里还没有用户 —— 先在应用里注册一个再跑这个脚本")
        return mint_service_session(db, user.id)


def capture(base: str, token: str, names: list[str], theme: str = "light") -> None:
    from playwright.sync_api import sync_playwright

    OUT_DOCS.mkdir(parents=True, exist_ok=True)
    OUT_SITE.mkdir(parents=True, exist_ok=True)
    OUT_SITE_DARK.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": WIDTH, "height": HEIGHT},
            device_scale_factor=SCALE,
            locale="zh-CN",
            color_scheme=theme,
        )
        # 令牌和主题都要在页面脚本跑之前就位,否则会先闪一下登录页 / 浅色再切过去,
        # 而截图很可能正好落在那一下上。
        context.add_init_script(
            f"window.localStorage.setItem('mosael.auth.token', {token!r});"
            f"window.localStorage.setItem('mosael.preferences', "
            f"JSON.stringify({{theme: {theme!r}, locale: 'zh-CN'}}));"
        )
        page = context.new_page()
        for name in names:
            shot = SHOTS[name]
            page.goto(f"{base}/{shot['route']}", wait_until="networkidle")
            for step in shot.get("steps", []):
                page.evaluate(step)
                page.wait_for_timeout(900)
            # 网络静默之后再等一拍:图表、波形、缩略图是拿到数据之后才画的。
            # 要出网的那几张(探测链接)自己声明更长的等待 —— 写死一个大值会让每张都慢。
            page.wait_for_timeout(int(shot.get("settle_ms", 1200)))
            if theme == "dark":
                target = OUT_SITE_DARK / f"{name}.png"
                page.screenshot(path=str(target))
            else:
                target = OUT_DOCS / f"{name}.png"
                page.screenshot(path=str(target))
                (OUT_SITE / f"{name}.png").write_bytes(target.read_bytes())
            print(f"  {theme:5s} {name:12s} → {target.relative_to(REPO)}")
        browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="*", help="只截这几张(默认全部)")
    parser.add_argument("--base", default="http://127.0.0.1:5173", help="前端地址")
    args = parser.parse_args()

    names = args.names or list(SHOTS)
    unknown = [name for name in names if name not in SHOTS]
    if unknown:
        raise SystemExit(f"不认识这些名字:{unknown};可选:{list(SHOTS)}")
    print(f"截图 → {WIDTH}×{HEIGHT} @{SCALE}x = {WIDTH * SCALE}×{HEIGHT * SCALE}")
    token = mint_token()
    for theme in ("light", "dark"):
        capture(args.base.rstrip("/"), token, names, theme)


if __name__ == "__main__":
    main()
