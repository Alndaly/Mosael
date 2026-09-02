#!/usr/bin/env python3
"""Mosael 宣传片生成器。

与上一版的根本区别:**上一版是九张纯 SVG 幻灯片,没有一帧真实产品画面**——观众看完不知道
这东西长什么样、能不能用。这一版反过来,真实素材占主体,生成的图形只做连接与强调:

  · 产品界面   gen/screens/*.png(优先)或官网 public/media 里的那套 —— 真实界面截图
  · 排版图形   本文件内的 SVG                       —— 开场、痛点、本地优先、收尾

节奏:痛点(0-6s)→ 四段能力(6-23s)→ 差异化(23-27s)→ CTA(27-30s)。
配色取 tokens.css 的浅色「暖纸面」主题,与真实截图一致。

用法:
    python3 docs/media/gen/build_promo.py            # → docs/media/mosael-promo.mp4
    python3 docs/media/gen/build_promo.py --preview  # 只出分镜联络图,快速看构图
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SHOTS = os.path.join(HERE, "shots")
#: 产品界面截图来源。优先用 gen/screens/(你自己截的最新界面),没有再回退到文档站那套。
#: 文档站那批是 2026-07-24 的,已经过时:智能体面板是空的、发布页是空状态、还带旧品牌名。
#: 想换成新的,把同名 png 丢进 gen/screens/ 重跑即可,不用改代码。
MEDIA = os.path.join(REPO, "docs", "media")
SCREENS_LOCAL = os.path.join(HERE, "screens")
SCREENS_FALLBACK = os.path.join(REPO, "website", "public", "media", "screens")


def screen(name: str) -> str:
    local = os.path.join(SCREENS_LOCAL, name)
    return local if os.path.isfile(local) else os.path.join(SCREENS_FALLBACK, name)

W, H, FPS = 1920, 1080, 30
XFADE = 0.35

# ---- 品牌配色(tokens.css 浅色「暖纸面」)----
BG = "#f6f4f0"
CARD = "#fdfcfa"
INK = "#2c2a33"
MUTE = "#756f80"
PRIMARY = "#6a5cd8"
ACCENT = "#ece9fb"
BORDER = "#e6e1d8"
WARN = "#c2410c"
FONT = "PingFang SC, Hiragino Sans GB, STHeiti, sans-serif"
MONO = "SF Mono, Menlo, monospace"


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"命令失败({proc.returncode}):{' '.join(cmd[:6])}…\n{proc.stderr[-800:]}")


# ---------------------------------------------------------------- SVG 基件


def svg(body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
        f"<defs>"
        f'<linearGradient id="warm" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{BG}"/><stop offset="1" stop-color="#efeae1"/></linearGradient>'
        f'<filter id="soft" x="-40%" y="-40%" width="180%" height="180%">'
        f'<feGaussianBlur stdDeviation="30"/></filter>'
        f"</defs>"
        f'<rect width="{W}" height="{H}" fill="url(#warm)"/>{body}</svg>'
    )


def logo(cx: float, cy: float, s: float = 1.0, glow: bool = True) -> str:
    """节点式 M:三竖两连,呼应工作流画布。"""
    u = 26 * s
    pts = [(-2.2, 0.9), (-1.1, -1.0), (0.0, 0.9), (1.1, -1.0), (2.2, 0.9)]
    out = ""
    for i in range(len(pts) - 1):
        x1, y1 = cx + pts[i][0] * u, cy + pts[i][1] * u
        x2, y2 = cx + pts[i + 1][0] * u, cy + pts[i + 1][1] * u
        out += (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                f'stroke="{PRIMARY}" stroke-width="{5*s:.1f}" stroke-linecap="round" opacity="0.5"/>')
    for px, py in pts:
        x, y = cx + px * u, cy + py * u
        if glow:
            out += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{17*s:.1f}" fill="{PRIMARY}" opacity="0.15"/>'
        out += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{8*s:.1f}" fill="{PRIMARY}"/>'
    return out


def centered(text: str, y: float, size: int, color: str = INK, weight: int = 700,
             spacing: float = 1, family: str = FONT) -> str:
    return (f'<text x="{W/2}" y="{y}" font-family="{family}" font-size="{size}" '
            f'font-weight="{weight}" fill="{color}" text-anchor="middle" '
            f'letter-spacing="{spacing}">{esc(text)}</text>')


def lower_third(kicker: str, line: str) -> str:
    """压在真实截图左下的字幕条。不铺满整宽——要让观众仍看得见界面。"""
    return (
        f'<g transform="translate(92,{H-278})">'
        f'<rect x="0" y="0" width="1216" height="184" rx="20" fill="{CARD}" opacity="0.95"/>'
        f'<rect x="0" y="0" width="8" height="184" rx="4" fill="{PRIMARY}"/>'
        f'<text x="48" y="64" font-family="{FONT}" font-size="27" fill="{PRIMARY}" '
        f'letter-spacing="4" font-weight="600">{esc(kicker)}</text>'
        f'<text x="48" y="134" font-family="{FONT}" font-size="50" font-weight="600" '
        f'fill="{INK}">{esc(line)}</text></g>'
    )


# ---------------------------------------------------------------- 分镜


def shot_open() -> str:
    return svg(
        f'<circle cx="{W/2}" cy="424" r="250" fill="{PRIMARY}" opacity="0.08" filter="url(#soft)"/>'
        + logo(W / 2, 424, 1.5)
        + centered("Mosael", 700, 104, spacing=2)
        + centered("本地优先的 AI 视频创作工作室", 774, 34, MUTE, 400, spacing=6)
    )


def shot_problem() -> str:
    tools = ["剪辑", "配音", "字幕", "分发"]
    cards = ""
    for i, name in enumerate(tools):
        x = 178 + i * 400
        cards += (
            f'<g transform="translate({x},432)">'
            f'<rect width="292" height="204" rx="20" fill="{CARD}" stroke="{BORDER}" stroke-width="2"/>'
            f'<text x="146" y="122" font-family="{FONT}" font-size="48" font-weight="600" '
            f'fill="{INK}" text-anchor="middle">{esc(name)}</text></g>'
        )
        if i < 3:
            ax = x + 292 + 22
            cards += (
                f'<path d="M{ax} 534 L{ax+64} 534" stroke="{WARN}" stroke-width="4" '
                f'stroke-dasharray="9 9" stroke-linecap="round" opacity="0.85"/>'
                f'<text x="{ax+32}" y="502" font-family="{FONT}" font-size="24" fill="{WARN}" '
                f'text-anchor="middle">导出</text>'
            )
    return svg(
        centered("四个软件,四次导出", 258, 78)
        + cards
        + centered("每一步之间都在等进度条", 800, 34, MUTE, 400)
    )


def shot_local() -> str:
    rings = "".join(
        f'<circle cx="{W/2}" cy="424" r="{292+i*88}" fill="none" stroke="{PRIMARY}" '
        f'stroke-width="1.5" opacity="{0.17-i*0.05:.2f}"/>'
        for i in range(3)
    )
    device = (
        f'<g transform="translate({W/2-152},318)">'
        f'<rect width="304" height="212" rx="22" fill="{CARD}" stroke="{BORDER}" stroke-width="3"/>'
        f'<rect x="26" y="26" width="252" height="142" rx="10" fill="{ACCENT}"/>'
        + logo(152, 97, 0.62, glow=False)
        + f'<rect x="114" y="184" width="76" height="12" rx="6" fill="{BORDER}"/></g>'
    )
    return svg(
        f'<circle cx="{W/2}" cy="424" r="220" fill="{PRIMARY}" opacity="0.09" filter="url(#soft)"/>'
        + rings + device
        + centered("素材、工程、登录态,都在你自己的机器上", 790, 56)
        + centered("离线可用 · 不上传 · 也可切到自己的服务器", 858, 31, MUTE, 400)
    )


def shot_cta() -> str:
    return svg(
        logo(W / 2, 396, 1.25)
        + centered("Mosael", 612, 90, spacing=2)
        + centered("mosael.team", 702, 42, PRIMARY, 600, spacing=2, family=MONO)
        + centered("macOS · Windows   |   源码可见", 792, 28, MUTE, 400, spacing=1)
    )


GRAPHIC_SHOTS = {
    "00-open": (2.6, shot_open),
    "01-problem": (3.6, shot_problem),
    "06-local": (3.6, shot_local),
    "07-cta": (3.4, shot_cta),
}

FOOTAGE_SHOTS = {
    "02-edit": (5.0, "editor.png", "in", "剪辑", "多轨、画中画、字幕,一条时间线做完"),
    "03-agent": (4.2, "ai-chat.png", "left", "智能体", "AI 直接改你的工程,每次改动先出确认卡"),
    "04-flow": (4.2, "workflows.png", "right", "工作流", "框选折叠成子图,整条流程可嵌套复用"),
    "05-publish": (3.8, "publish.png", "in", "分发", "一次导出,抖音 / B站 / 小红书 / 视频号"),
}

ORDER = ["00-open", "01-problem", "02-edit", "03-agent", "04-flow", "05-publish", "06-local", "07-cta"]


# ---------------------------------------------------------------- 渲染


def rasterize(name: str, markup: str, transparent: bool = False) -> str:
    svg_path = os.path.join(SHOTS, f"{name}.svg")
    png_path = os.path.join(SHOTS, f"{name}.png")
    with open(svg_path, "w", encoding="utf-8") as fh:
        fh.write(markup)
    run(["rsvg-convert", "-w", str(W), "-h", str(H), svg_path, "-o", png_path])
    return png_path


def _drift(src: str, dur: float, out: str, sw: int, sh: int, dx: float, dy: float) -> None:
    """把一张比画幅大的图铺在 1920×1080 上,逐帧位移 —— 缓慢漂移的运镜。

    不用 zoompan:它每帧都要重做超采样,8 个分镜跑了 17 分钟。overlay 的 x/y 支持逐帧表达式,
    只是整数平移,同样的活儿几秒钟就完了。代价是没有真正的缩放,但这种慢速推移本来也看不出。
    """
    x = f"(W-w)/2+({dx})*(t/{dur}-0.5)"
    y = f"(H-h)/2+({dy})*(t/{dur}-0.5)"
    fc = (f"[0:v]scale={sw}:{sh}[img];"
          f"color=c=0x{BG[1:]}:s={W}x{H}:d={dur}:r={FPS}[bgc];"
          f"[bgc][img]overlay=x='{x}':y='{y}':eval=frame,format=yuv420p[v]")
    run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", str(FPS), "-t", f"{dur}", "-i", src,
         "-filter_complex", fc, "-map", "[v]", "-t", f"{dur}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", out])


def clip_graphic(png: str, dur: float, out: str) -> None:
    """图形分镜:略微放大后极慢漂移,避免完全静止的呆板感。"""
    _drift(png, dur, out, int(W * 1.06), int(H * 1.06), 26, 16)


def clip_footage(png: str, dur: float, motion: str, overlay: str, out: str) -> None:
    """真实界面截图 → 漂移运镜 + 叠字幕条。

    截图放大到略宽于画幅,按 motion 决定漂移方向:横向漂移展示宽界面(时间线、画布),
    纵向微漂用于信息密集的页面。
    """
    dx, dy = {"in": (18, 12), "left": (-150, 0), "right": (150, 0)}[motion]
    tmp = out.replace(".mp4", "-bg.mp4")
    _drift(png, dur, tmp, int(W * 1.10), int(W * 1.10 * 0.625), dx, dy)
    fc = "[0:v][1:v]overlay=0:0:format=auto,format=yuv420p[v]"
    run(["ffmpeg", "-y", "-v", "error", "-i", tmp,
         "-loop", "1", "-framerate", str(FPS), "-t", f"{dur}", "-i", overlay,
         "-filter_complex", fc, "-map", "[v]", "-t", f"{dur}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", out])
    os.remove(tmp)


def build_shots() -> list[tuple[str, float]]:
    os.makedirs(SHOTS, exist_ok=True)
    made: list[tuple[str, float]] = []
    for name in ORDER:
        out = os.path.join(SHOTS, f"{name}.mp4")
        if name in GRAPHIC_SHOTS:
            dur, maker = GRAPHIC_SHOTS[name]
            clip_graphic(rasterize(name, maker()), dur, out)
        else:
            dur, src_name, motion, kicker, line = FOOTAGE_SHOTS[name]
            src = screen(src_name)
            if not os.path.isfile(src):
                raise SystemExit(f"缺少真实截图:{src}")
            ov = rasterize(f"{name}-ov",
                           f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}">'
                           f"{lower_third(kicker, line)}</svg>")
            clip_footage(src, dur, motion, ov, out)
        made.append((out, dur))
        print(f"  {name:12s} {dur:>4.1f}s")
    return made


def build() -> str:
    made = build_shots()
    inputs: list[str] = []
    for path, _ in made:
        inputs += ["-i", path]
    chain, prev, offset = "", "0:v", 0.0
    for i in range(1, len(made)):
        offset += made[i - 1][1] - XFADE
        chain += f"[{prev}][{i}:v]xfade=transition=fade:duration={XFADE}:offset={offset:.3f}[x{i}];"
        prev = f"x{i}"
    total = sum(d for _, d in made) - XFADE * (len(made) - 1)
    # 低频环境垫:三层正弦 + 缓慢颤音。无版权风险,也不喧宾夺主。
    audio = (f"aevalsrc=0.055*sin(2*PI*146.83*t)+0.04*sin(2*PI*220*t)+0.018*sin(2*PI*293.66*t):"
             f"s=44100:d={total:.2f},tremolo=f=0.13:d=0.45,lowpass=f=1100,"
             f"afade=t=in:st=0:d=1.4,afade=t=out:st={total-1.6:.2f}:d=1.6,volume=0.45[a]")
    out = os.path.join(MEDIA, "mosael-promo.mp4")
    run(["ffmpeg", "-y", "-v", "error", *inputs,
         "-filter_complex", chain.rstrip(";") + ";" + audio,
         "-map", f"[{prev}]", "-map", "[a]",
         "-c:v", "libx264", "-preset", "slow", "-crf", "19", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
         "-t", f"{total:.2f}", out])
    print(f"\n成片:{out}\n     {total:.1f}s  {os.path.getsize(out)/1e6:.1f} MB")
    return out


def contact_sheet() -> str:
    """分镜联络图(2×4):快速判断构图是否成立,不必看完整片。"""
    build_shots()
    frames = []
    for name in ORDER:
        dst = os.path.join(SHOTS, f"cs-{name}.png")
        run(["ffmpeg", "-y", "-v", "error", "-ss", "1", "-i", os.path.join(SHOTS, f"{name}.mp4"),
             "-frames:v", "1", "-vf", "scale=480:270", dst])
        frames.append(dst)
    inputs: list[str] = []
    for f in frames:
        inputs += ["-i", f]
    out = os.path.join(SHOTS, "contact.png")
    run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex",
         "[0][1][2][3]hstack=inputs=4[t];[4][5][6][7]hstack=inputs=4[b];[t][b]vstack",
         "-frames:v", "1", out])
    print("联络图:", out)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true", help="只出分镜联络图")
    args = ap.parse_args()
    for tool in ("rsvg-convert", "ffmpeg"):
        if not shutil.which(tool):
            sys.exit(f"缺少依赖:{tool}")
    contact_sheet() if args.preview else build()
