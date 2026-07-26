#!/usr/bin/env python3
"""生成「框选 → 折叠为子图」演示 GIF(全程代码生成)。
帧:SVG 按时间参数 t 排版 → rsvg-convert → ffmpeg(palettegen/paletteuse)成 GIF。"""
import os, subprocess, math

HERE = os.path.dirname(os.path.abspath(__file__))
FR = os.path.join(HERE, "gif_frames"); os.makedirs(FR, exist_ok=True)
W, H = 1120, 560
BG0, BG1 = "#141218", "#1c1a23"
PANEL, BORDER, INK, MUTE = "#211d2a", "#3a3547", "#e9e6f0", "#9a93a8"
PRIMARY, GOOD = "#8a7bf0", "#4ec58a"
FONT = "PingFang SC, Hiragino Sans GB, sans-serif"
FPS, DUR = 20, 4.2


def ease(x):  # smoothstep
    x = max(0.0, min(1.0, x)); return x * x * (3 - 2 * x)


def lerp(a, b, t): return a + (b - a) * t


def node(x, y, w, h, label, op=1.0, scale=1.0, ring=False, fill=PANEL):
    cx, cy = x + w/2, y + h/2
    w2, h2 = w*scale, h*scale
    x2, y2 = cx - w2/2, cy - h2/2
    r = f'<rect x="{x2-6}" y="{y2-6}" width="{w2+12}" height="{h2+12}" rx="18" fill="none" stroke="{PRIMARY}" stroke-width="3" opacity="{op}"/>' if ring else ""
    return (f'<g opacity="{op:.2f}">{r}<rect x="{x2:.1f}" y="{y2:.1f}" width="{w2:.1f}" height="{h2:.1f}" rx="13" fill="{fill}" stroke="{BORDER}" stroke-width="1.5"/>'
            f'<circle cx="{x2+13:.1f}" cy="{cy:.1f}" r="4.5" fill="{PRIMARY}"/><circle cx="{x2+w2-13:.1f}" cy="{cy:.1f}" r="4.5" fill="{GOOD}"/>'
            f'<text x="{cx:.1f}" y="{cy+8:.1f}" font-family="{FONT}" font-size="{26*scale:.0f}" font-weight="600" fill="{INK}" text-anchor="middle">{label}</text></g>')


def edge(x1, y1, x2, y2, op=0.75):
    mx = (x1+x2)/2
    return f'<path d="M{x1:.0f} {y1:.0f} C{mx:.0f} {y1:.0f} {mx:.0f} {y2:.0f} {x2:.0f} {y2:.0f}" stroke="{PRIMARY}" stroke-width="2.5" fill="none" opacity="{op:.2f}"/>'


# 布局
NW, NH = 176, 66
START = (70, 247)
A = (360, 150); B = (360, 344); C = (620, 247)   # 待折叠三节点
OUT = (874, 247)
SEL = [A, B, C]
cxC = sum(p[0] for p in SEL)/3 + NW/2
cyC = sum(p[1] for p in SEL)/3 + NH/2
SGx, SGy = cxC - NW/2, cyC - NH/2  # 子图节点落位(选区质心)


def frame(t):
    s = f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}"><defs>'
    s += f'<radialGradient id="bg" cx="40%" cy="35%" r="90%"><stop offset="0%" stop-color="{BG1}"/><stop offset="100%" stop-color="{BG0}"/></radialGradient></defs>'
    s += f'<rect width="{W}" height="{H}" fill="url(#bg)"/>'
    for gy in range(40, H, 60):
        for gx in range(40, W, 60):
            s += f'<circle cx="{gx}" cy="{gy}" r="1.2" fill="{BORDER}" opacity="0.5"/>'

    # 阶段
    p_sel = ease((t-0.15)/0.20)   # 选框出现
    p_col = ease((t-0.42)/0.26)   # 折叠
    hold = t > 0.72

    # 边:折叠前 start→A,start→B,A→C,B→C,C→out;折叠后 start→SG→out
    e_pre = 1 - ease((t-0.42)/0.18)
    e_post = ease((t-0.60)/0.20)
    def c(p): return (p[0]+NW/2, p[1]+NH/2)
    s += edge(*c(START)[:1], c(START)[1], c(A)[0]-NW/2, c(A)[1], 0.7*e_pre) if False else ""
    s += edge(c(START)[0]+NW/2, c(START)[1], c(A)[0]-NW/2, c(A)[1], 0.7*e_pre)
    s += edge(c(START)[0]+NW/2, c(START)[1], c(B)[0]-NW/2, c(B)[1], 0.7*e_pre)
    s += edge(c(A)[0]+NW/2, c(A)[1], c(C)[0]-NW/2, c(C)[1], 0.7*e_pre)
    s += edge(c(B)[0]+NW/2, c(B)[1], c(C)[0]-NW/2, c(C)[1], 0.7*e_pre)
    s += edge(c(C)[0]+NW/2, c(C)[1], c(OUT)[0]-NW/2, c(OUT)[1], 0.7*e_pre)
    # 折叠后的新边
    s += edge(c(START)[0]+NW/2, c(START)[1], SGx-6, cyC, 0.8*e_post)
    s += edge(SGx+NW+6, cyC, c(OUT)[0]-NW/2, c(OUT)[1], 0.8*e_post)

    # 固定节点
    s += node(*START, NW, NH, "开始")
    s += node(*OUT, NW, NH, "发布")

    # 三个待折叠节点:折叠时向质心收拢 + 缩小 + 淡出
    for p in SEL:
        nx = lerp(p[0], SGx, p_col)
        ny = lerp(p[1], SGy, p_col)
        op = lerp(1.0, 0.0, ease((t-0.48)/0.18))
        sc = lerp(1.0, 0.72, p_col)
        ring = p_sel > 0.05 and p_col < 0.5
        lbl = {A: "AI 生成", B: "转写", C: "合成"}[p]
        s += node(nx, ny, NW, NH, lbl, op=max(op, 0), scale=sc, ring=ring)

    # 选框(dashed marquee)
    if 0.05 < p_sel and p_col < 0.55:
        mop = min(p_sel, 1-ease((t-0.42)/0.16))
        pad = 22
        mx0 = min(p[0] for p in SEL)-pad; my0 = min(p[1] for p in SEL)-pad
        mx1 = max(p[0] for p in SEL)+NW+pad; my1 = max(p[1] for p in SEL)+NH+pad
        s += (f'<rect x="{mx0}" y="{my0}" width="{mx1-mx0}" height="{my1-my0}" rx="16" fill="{PRIMARY}" opacity="{0.06*mop:.2f}"/>'
              f'<rect x="{mx0}" y="{my0}" width="{mx1-mx0}" height="{my1-my0}" rx="16" fill="none" stroke="{PRIMARY}" stroke-width="2.5" stroke-dasharray="9 7" opacity="{mop:.2f}"/>')

    # 子图节点(折叠后长出)
    if p_col > 0.15:
        sc = ease((p_col-0.15)/0.6)
        s += node(SGx, SGy, NW, NH, "", op=1, scale=sc, fill="#241f38")
        if sc > 0.6:
            # 子图图标 + 文字
            s += f'<text x="{SGx+NW/2}" y="{cyC+8}" font-family="{FONT}" font-size="25" font-weight="700" fill="{INK}" text-anchor="middle">📦 子图</text>'.replace("📦 ", "")
            s += f'<g transform="translate({SGx+30},{cyC})"><rect x="-11" y="-11" width="22" height="22" rx="5" fill="none" stroke="{PRIMARY}" stroke-width="2.5"/><rect x="-4" y="-4" width="22" height="22" rx="5" fill="none" stroke="{PRIMARY}" stroke-width="2.5" opacity="0.5"/></g>'

    # 顶部标签
    if hold:
        top = ease((t-0.72)/0.12)
        s += f'<g opacity="{top:.2f}"><rect x="{W/2-150}" y="34" width="300" height="52" rx="26" fill="{PANEL}" stroke="{PRIMARY}" stroke-width="1.5"/><text x="{W/2}" y="67" font-family="{FONT}" font-size="26" font-weight="700" fill="{PRIMARY}" text-anchor="middle">✓ 已折叠为子图</text></g>'
    else:
        cap = "框选节点" if t < 0.42 else "折叠为子图"
        s += f'<text x="{W/2}" y="60" font-family="{FONT}" font-size="26" font-weight="600" fill="{MUTE}" text-anchor="middle">{cap}</text>'
    return s + "</svg>"


def build():
    n = int(FPS*DUR)
    for i in range(n):
        t = i/(n-1)
        svg = os.path.join(FR, f"f{i:03d}.svg"); png = os.path.join(FR, f"f{i:03d}.png")
        open(svg, "w").write(frame(t))
        subprocess.run(["rsvg-convert", "-w", str(W), "-h", str(H), svg, "-o", png], check=True)
    out = os.path.join(HERE, "collapse.gif")
    pal = os.path.join(FR, "pal.png")
    subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", os.path.join(FR, "f%03d.png"),
                    "-vf", "scale=960:-1:flags=lanczos,palettegen=stats_mode=diff", pal], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", os.path.join(FR, "f%03d.png"), "-i", pal,
                    "-lavfi", "scale=960:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3",
                    "-loop", "0", out], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("OUT", out)


if __name__ == "__main__":
    build()
