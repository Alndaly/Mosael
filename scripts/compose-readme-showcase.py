#!/usr/bin/env python3
"""把首页那三张原样截图叠成 README 顶部的一张图。

README 顶上那张图此前是**手工拼的**:拼完就是一个死文件,截图更新之后没有任何东西
会提醒谁,而它旁边写着「实拍截图拼接展示」。这个脚本把它变成可重放的一步 —— 用的
就是官网首页展示区那三张 1.2.0 的原始截图(`website/public/media/homepage/<locale>/`),
版式也照着首页那段布局(`website/src/components/home-showcase.tsx`)算,不另发明一套:

    boards  左后,-2°,top 2% / left 1% / width 57%
    editor  右后,+2°,top 6% / left 44% / width 55%
    scenes  前排,不转,top 25% / left 17% / width 70%

百分比都是相对「舞台」(aspect 1.52)算的,和首页那几个 Tailwind 类一一对得上。
截图本身**不做任何改动** —— 只有圆角、描边和投影是这里加的。

    python3 scripts/compose-readme-showcase.py

同一张图再按 1200×630 摆进一张分享卡片(`website/public/og/mosael-<locale>.png`):官网每一页的
Open Graph / Twitter 卡片都用它(见 website/src/lib/seo.ts 的 ogImage)。也只是缩放和留白,截图不动。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "website/public/media/homepage"

# 舞台宽高比与三扇窗的位置,来自 home-showcase.tsx 的 sm: 那一档。
STAGE_ASPECT = 1.52
LAYERS = [
    # (文件名, top%, left%, width%, 旋转角度)
    ("boards", 0.02, 0.01, 0.57, -2.0),
    ("editor", 0.06, 0.44, 0.55, 2.0),
    ("scenes", 0.25, 0.17, 0.70, 0.0),
]

# 首页是 rounded-xl(12px)配 1030px 左右的显示宽度;这里按舞台宽度等比放大。
RADIUS_RATIO = 12 / 1030
BORDER = (0, 0, 0, 20)  # border-black/8
# shadow-[0_18px_50px_-16px_rgba(26,17,48,0.4)]
SHADOW_COLOR = (26, 17, 48)
SHADOW_ALPHA = 102
SHADOW_OFFSET_RATIO = 18 / 1030
SHADOW_BLUR_RATIO = 50 / 1030
SHADOW_SPREAD_RATIO = -16 / 1030

BACKGROUND_TOP = (250, 246, 236)
BACKGROUND_BOTTOM = (251, 247, 241)


def rounded(image: Image.Image, radius: int) -> Image.Image:
    """圆角 + 1px 描边。描边画在里侧,免得旋转之后边缘出现半透明的锯齿带。"""
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, image.width - 1, image.height - 1), radius, fill=255)
    out = Image.new("RGBA", image.size, (0, 0, 0, 0))
    out.paste(image.convert("RGB"), (0, 0), mask)
    ImageDraw.Draw(out).rounded_rectangle((0, 0, image.width - 1, image.height - 1), radius, outline=BORDER, width=2)
    return out


def with_shadow(window: Image.Image, radius: int, stage_width: int) -> tuple[Image.Image, int, int]:
    """把窗和它的投影画进同一层,返回该层与它相对窗口左上角的偏移。"""
    offset = round(SHADOW_OFFSET_RATIO * stage_width)
    blur = round(SHADOW_BLUR_RATIO * stage_width)
    spread = round(SHADOW_SPREAD_RATIO * stage_width)
    pad = blur * 2 + abs(offset) + abs(spread) + 4
    layer = Image.new("RGBA", (window.width + pad * 2, window.height + pad * 2), (0, 0, 0, 0))

    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    box = (
        pad - spread,
        pad - spread + offset,
        pad + window.width + spread - 1,
        pad + window.height + spread + offset - 1,
    )
    ImageDraw.Draw(shadow).rounded_rectangle(box, radius, fill=(*SHADOW_COLOR, SHADOW_ALPHA))
    layer.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(blur / 2)))
    layer.alpha_composite(window, (pad, pad))
    return layer, pad, pad


def compose(locale: str, stage_width: int) -> Image.Image:
    stage_height = round(stage_width / STAGE_ASPECT)
    radius = max(2, round(RADIUS_RATIO * stage_width))
    # 先摊在一张够大的透明画布上,最后按内容裁 —— 旋转会把角甩到舞台外面,
    # 提前定死画布尺寸的话那几个角会被切掉。
    margin = stage_width // 4
    canvas = Image.new("RGBA", (stage_width + margin * 2, stage_height + margin * 2), (0, 0, 0, 0))

    for name, top, left, width, angle in LAYERS:
        source = Image.open(SHOTS / locale / f"{name}.png").convert("RGB")
        target_width = round(width * stage_width)
        target_height = round(target_width * source.height / source.width)
        window = rounded(source.resize((target_width, target_height), Image.LANCZOS), radius)
        layer, dx, dy = with_shadow(window, radius, stage_width)
        x = margin + round(left * stage_width) - dx
        y = margin + round(top * stage_height) - dy
        if angle:
            turned = layer.rotate(angle, resample=Image.BICUBIC, expand=True)
            x -= (turned.width - layer.width) // 2
            y -= (turned.height - layer.height) // 2
            layer = turned
        canvas.alpha_composite(layer, (x, y))

    box = canvas.getbbox()
    assert box, "空画布"
    pad = round(stage_width * 0.02)
    left, top, right, bottom = box
    canvas = canvas.crop((left - pad, top - pad, right + pad, bottom + pad))

    out = Image.new("RGB", canvas.size, BACKGROUND_TOP)
    gradient = Image.linear_gradient("L").resize(canvas.size, Image.BILINEAR)
    out = Image.composite(Image.new("RGB", canvas.size, BACKGROUND_BOTTOM), out, gradient)
    out.paste(canvas, (0, 0), canvas)
    return out


OG_SIZE = (1200, 630)


def og_card(showcase: Image.Image) -> Image.Image:
    """把叠好的截图等比缩进 1200×630,四周补同一段暖白渐变。各家分享卡片都按这个比例裁,不缩的话会被切掉两边。"""
    inset = 0.92
    scale = min(OG_SIZE[0] * inset / showcase.width, OG_SIZE[1] * inset / showcase.height)
    fitted = showcase.resize((round(showcase.width * scale), round(showcase.height * scale)), Image.LANCZOS)
    card = Image.new("RGB", OG_SIZE, BACKGROUND_TOP)
    gradient = Image.linear_gradient("L").resize(OG_SIZE, Image.BILINEAR)
    card = Image.composite(Image.new("RGB", OG_SIZE, BACKGROUND_BOTTOM), card, gradient)
    card.paste(fitted, ((OG_SIZE[0] - fitted.width) // 2, (OG_SIZE[1] - fitted.height) // 2))
    return card


def quantize(target: Path) -> None:
    # 和官网截图同一道量化(website/scripts/record-doc-media.py 的 PNGQUANT):分辨率不变,体积小一大截。
    if shutil.which("pngquant"):
        subprocess.run(["pngquant", "--quality=80-100", "--speed", "1", "--skip-if-larger", "--strip", "--force",
                        "--ext", ".png", str(target)], check=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locale", choices=["zh", "en", "both"], default="both")
    parser.add_argument("--stage-width", type=int, default=1560, help="舞台宽度(像素)")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "docs/media")
    parser.add_argument("--og-dir", type=Path, default=ROOT / "website/public/og")
    parser.add_argument("--only", choices=["readme", "og", "both"], default="both", help="只出 README 图或分享卡片")
    args = parser.parse_args()

    for locale in (["zh", "en"] if args.locale == "both" else [args.locale]):
        image = compose(locale, args.stage_width)
        targets = []
        if args.only in ("readme", "both"):
            targets.append((args.out_dir / f"readme-showcase.{locale}.png", image))
        if args.only in ("og", "both"):
            args.og_dir.mkdir(parents=True, exist_ok=True)
            targets.append((args.og_dir / f"mosael-{locale}.png", og_card(image)))
        for target, picture in targets:
            picture.save(target, optimize=True)
            quantize(target)
            print(f"{target.relative_to(ROOT)}  {picture.width}×{picture.height}  {target.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
