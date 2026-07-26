#!/usr/bin/env python3
"""Mibu 宣传片生成器 —— 全程用代码生成,不依赖录屏/截屏。

流程:每张幻灯片用 SVG 排版(品牌配色 + 节点式 M logo)→ rsvg-convert 渲成 PNG →
ffmpeg 逐片加缓慢推近(Ken Burns)+ 交叉溶解(xfade)+ 低音环境垫 → 输出 promo.mp4。
改文案/配色/时长只改这一个文件重跑即可。
"""
from __future__ import annotations
import os, subprocess, math, textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
SLIDES = os.path.join(HERE, "slides")
os.makedirs(SLIDES, exist_ok=True)
W, H = 1920, 1080

# ---- 品牌配色(取自 frontend/src/design/tokens.css 暗色主题)----
BG0, BG1 = "#141218", "#1c1a23"
PANEL, PANEL2 = "#1c1a23", "#232029"
BORDER = "#332f3d"
INK = "#e9e6f0"       # 主文字
MUTE = "#9a93a8"      # 次文字
PRIMARY = "#8a7bf0"   # 品牌紫
PRIMARY_D = "#6a5cd8"
GOOD = "#4ec58a"
FONT = "PingFang SC, Hiragino Sans GB, STHeiti, sans-serif"
MONO = "SF Mono, Menlo, monospace"

# 平台色
PLAT = [("抖音", "#111"), ("B站", "#fb7299"), ("小红书", "#ff2442"), ("视频号", "#07c160")]


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def node_m(cx: float, cy: float, s: float, color: str, glow: bool = True) -> str:
    """节点式 M(5 个节点连成 M)。原始 viewBox 22 26 76 72,中心约 (60,62)。"""
    def P(px, py):
        return f"{cx + (px - 60) * s:.1f} {cy + (py - 62) * s:.1f}"
    sw = 9 * s
    r = 10 * s
    pts = [(34, 38), (60, 62), (86, 38), (34, 86), (86, 86)]
    circles = "".join(f'<circle cx="{cx+(px-60)*s:.1f}" cy="{cy+(py-62)*s:.1f}" r="{r:.1f}"/>' for px, py in pts)
    filt = ' filter="url(#glow)"' if glow else ""
    return f'''<g{filt}>
      <path d="M{P(34,86)} L{P(34,38)} L{P(60,62)} L{P(86,38)} L{P(86,86)}"
            stroke="{color}" stroke-width="{sw:.1f}" fill="none" stroke-linejoin="round" stroke-linecap="round" opacity="0.55"/>
      <g fill="{color}">{circles}</g>
    </g>'''


def new_badge(x: float = 1618, y: float = 150) -> str:
    return f'''<g>
      <rect x="{x}" y="{y}" width="102" height="46" rx="23" fill="none" stroke="{PRIMARY}" stroke-width="2"/>
      <circle cx="{x+26}" cy="{y+23}" r="5" fill="{PRIMARY}"/>
      <text x="{x+62}" y="{y+31}" font-family="{FONT}" font-size="22" font-weight="700" fill="{PRIMARY}" text-anchor="middle" letter-spacing="1">NEW</text>
    </g>'''


def head(defs_extra: str = "") -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<defs>
  <radialGradient id="bg" cx="38%" cy="30%" r="90%">
    <stop offset="0%" stop-color="{BG1}"/><stop offset="100%" stop-color="{BG0}"/>
  </radialGradient>
  <linearGradient id="violet" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0%" stop-color="{PRIMARY}"/><stop offset="100%" stop-color="{PRIMARY_D}"/>
  </linearGradient>
  <filter id="glow" x="-60%" y="-60%" width="220%" height="220%">
    <feGaussianBlur stdDeviation="10" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <filter id="soft" x="-40%" y="-40%" width="180%" height="180%"><feDropShadow dx="0" dy="10" stdDeviation="22" flood-color="#000" flood-opacity="0.45"/></filter>
  {defs_extra}
</defs>
<rect width="{W}" height="{H}" fill="url(#bg)"/>
<g opacity="0.5">{dot_grid()}</g>'''


def dot_grid() -> str:
    d = []
    for gy in range(80, H, 96):
        for gx in range(80, W, 96):
            d.append(f'<circle cx="{gx}" cy="{gy}" r="1.4" fill="{BORDER}"/>')
    return "".join(d)


def kicker(x, y, text, color=PRIMARY):
    return (f'<rect x="{x}" y="{y-22}" width="30" height="4" rx="2" fill="{color}"/>'
            f'<text x="{x+44}" y="{y-9}" font-family="{FONT}" font-size="24" font-weight="600" '
            f'letter-spacing="3" fill="{color}">{esc(text)}</text>')


def pill(x, y, w, h, label, fill=PANEL, stroke=BORDER, tcolor=INK, fs=30, icon=None):
    ic = f'<text x="{x+34}" y="{y+h/2+11}" font-size="{fs+4}" text-anchor="middle">{icon}</text>' if icon else ""
    tx = x + (58 if icon else w/2)
    anchor = "start" if icon else "middle"
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h/2}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>'
            f'{ic}<text x="{tx}" y="{y+h/2+11}" font-family="{FONT}" font-size="{fs}" font-weight="600" fill="{tcolor}" text-anchor="{anchor}">{esc(label)}</text>')


def foot() -> str:
    return "</svg>"


# ---------------- 幻灯片 ----------------

def slide_hero():
    return head() + f'''
    {node_m(W/2, 400, 3.4, PRIMARY)}
    <text x="{W/2}" y="640" font-family="{FONT}" font-size="132" font-weight="800" fill="{INK}" text-anchor="middle" letter-spacing="2">Mibu</text>
    <text x="{W/2}" y="712" font-family="{FONT}" font-size="34" font-weight="500" fill="{PRIMARY}" text-anchor="middle" letter-spacing="6">AI NATIVE VIDEO STUDIO</text>
    <text x="{W/2}" y="800" font-family="{FONT}" font-size="30" fill="{MUTE}" text-anchor="middle">本地优先 · 一个桌面应用,跑通 从素材到矩阵发布 的全链路</text>
    ''' + foot()


def flow_arrow(x, y, w=54):
    return f'<path d="M{x} {y} l{w-14} 0 m-16 -9 l16 9 l-16 9" stroke="{PRIMARY}" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'


def slide_pipeline():
    steps = ["素材导入", "逐字剪辑", "AI 成片", "矩阵发布"]
    y = 520; bw = 320; bh = 150; gap = 96; x0 = (W - (bw*4 + gap*3))/2
    boxes = []
    for i, label in enumerate(steps):
        x = x0 + i*(bw+gap)
        cx = x + bw/2
        boxes.append(f'''<g filter="url(#soft)"><rect x="{x}" y="{y}" width="{bw}" height="{bh}" rx="22" fill="{PANEL}" stroke="{BORDER}" stroke-width="1.5"/>
          <circle cx="{cx}" cy="{y+56}" r="28" fill="{PRIMARY}" opacity="0.16"/>
          <text x="{cx}" y="{y+67}" font-family="{FONT}" font-size="32" font-weight="800" fill="{PRIMARY}" text-anchor="middle">{i+1}</text>
          <text x="{cx}" y="{y+124}" font-family="{FONT}" font-size="32" font-weight="700" fill="{INK}" text-anchor="middle">{label}</text></g>''')
        if i < 3:
            boxes.append(flow_arrow(x+bw+21, y+bh/2, gap-42))
    return head() + f'''
    {kicker(x0, 380, "END-TO-END")}
    <text x="{x0}" y="452" font-family="{FONT}" font-size="72" font-weight="800" fill="{INK}">从素材到发布,一条流水线</text>
    {"".join(boxes)}
    <text x="{W/2}" y="740" font-family="{FONT}" font-size="28" fill="{MUTE}" text-anchor="middle">可由工作流与定时触发器全自动串起来 —— 一次搭好,持续产出</text>
    ''' + foot()


def slide_nle():
    # 迷你时间线
    tx, ty, tw = 200, 470, 1520
    tracks = [("#8a7bf0", [(0,340),(360,300),(700,480)]), ("#4ec58a", [(120,520),(680,360)]), ("#e0a44b", [(0,1180)])]
    rows = []
    for ti,(col,clips) in enumerate(tracks):
        ry = ty + ti*96
        rows.append(f'<rect x="{tx}" y="{ry}" width="{tw}" height="78" rx="10" fill="{PANEL2}"/>')
        for cx,cw in clips:
            rows.append(f'<rect x="{tx+16+cx}" y="{ry+10}" width="{cw}" height="58" rx="9" fill="{col}" opacity="0.9"/>')
    playhead = tx + 540
    return head() + f'''
    {kicker(tx, 360, "NLE 内核")}
    <text x="{tx}" y="432" font-family="{FONT}" font-size="72" font-weight="800" fill="{INK}">专业剪辑,不必学时间线</text>
    <g filter="url(#soft)"><rect x="{tx-24}" y="{ty-30}" width="{tw+48}" height="360" rx="20" fill="{PANEL}" stroke="{BORDER}" stroke-width="1.5"/></g>
    {"".join(rows)}
    <line x1="{playhead}" y1="{ty-14}" x2="{playhead}" y2="{ty+300}" stroke="{PRIMARY}" stroke-width="3"/>
    <circle cx="{playhead}" cy="{ty-14}" r="9" fill="{PRIMARY}"/>
    <text x="{tx}" y="890" font-family="{FONT}" font-size="30" fill="{MUTE}">多轨时间线 · 逐字剪辑 · 关键帧调色 · 恒定帧率一键导出</text>
    ''' + foot()


def slide_ai():
    px, py, pw, ph = 200, 430, 900, 430
    bubbles = [
        (PRIMARY, "把这段素材剪成 30 秒高光,配字幕", "#fff", True),
        (PANEL2, "已读懂 6 段素材情绪,自动分割 + 转场 + 花字 ✨", INK, False),
    ]
    by = py+40; bl = []
    for col, txt, tc, right in bubbles:
        bw = 620; bx = px+pw-bw-40 if right else px+40
        bl.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="90" rx="20" fill="{col}"/>'
                  f'<text x="{bx+30}" y="{by+55}" font-family="{FONT}" font-size="27" fill="{tc}">{esc(txt)}</text>')
        by += 130
    return head() + f'''
    {kicker(px, 340, "AI 应用中心 + 创作型智能体")}
    <text x="{px}" y="412" font-family="{FONT}" font-size="66" font-weight="800" fill="{INK}">动动嘴,就把片子剪了</text>
    <g filter="url(#soft)"><rect x="{px}" y="{py}" width="{pw}" height="{ph}" rx="24" fill="{PANEL}" stroke="{BORDER}" stroke-width="1.5"/></g>
    {"".join(bl)}
    <g transform="translate(1320,560)">{node_m(0,0,2.2,PRIMARY)}</g>
    <text x="1320" y="740" font-family="{FONT}" font-size="27" fill="{MUTE}" text-anchor="middle">文生图 · 图生视频 · 配音</text>
    <text x="1320" y="778" font-family="{FONT}" font-size="27" fill="{MUTE}" text-anchor="middle">智能体直接操作时间线</text>
    ''' + foot()


def graph_node(x, y, label, col=PANEL, tc=INK, w=190, h=70):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{col}" stroke="{BORDER}" stroke-width="1.5"/>'
            f'<circle cx="{x+14}" cy="{y+h/2}" r="5" fill="{PRIMARY}"/><circle cx="{x+w-14}" cy="{y+h/2}" r="5" fill="{GOOD}"/>'
            f'<text x="{x+w/2}" y="{y+h/2+9}" font-family="{FONT}" font-size="25" font-weight="600" fill="{tc}" text-anchor="middle">{esc(label)}</text>')


def edge(x1,y1,x2,y2):
    mx=(x1+x2)/2
    return f'<path d="M{x1} {y1} C{mx} {y1} {mx} {y2} {x2} {y2}" stroke="{PRIMARY}" stroke-width="2.5" fill="none" opacity="0.7"/>'


def slide_workflow():
    ox, oy = 200, 300
    # 主图 + 一个折叠成的子图节点
    n = []
    n.append(edge(390,460,560,400)); n.append(edge(390,460,560,540))
    n.append(edge(750,400,910,460)); n.append(edge(750,540,910,460))
    n.append(edge(1100,460,1270,460))
    body = (graph_node(200,425,"开始") + graph_node(560,365,"AI 生成") + graph_node(560,505,"转写")
            + graph_node(910,425,"子图 · 成片", col="#241f38", tc=INK) + graph_node(1270,425,"调用工作流·发布", w=250))
    # 折叠虚线框
    fold = f'<rect x="890" y="405" width="230" height="110" rx="16" fill="none" stroke="{PRIMARY}" stroke-width="2" stroke-dasharray="7 6"/>'
    return head() + f'''
    {kicker(ox, 250, "工作流引擎")} {new_badge()}
    <text x="{ox}" y="322" font-family="{FONT}" font-size="70" font-weight="800" fill="{INK}">把创作编排成流程</text>
    <g filter="url(#soft)"><rect x="150" y="360" width="1620" height="300" rx="22" fill="{PANEL}" stroke="{BORDER}" stroke-width="1.5" opacity="0.5"/></g>
    {"".join(n)}{body}{fold}
    <text x="{ox}" y="760" font-family="{FONT}" font-size="30" fill="{MUTE}">框选「折叠为子图」· 调用工作流(工作流即工具)· 循环 · 条件分支 · 定时触发</text>
    <text x="{ox}" y="806" font-family="{FONT}" font-size="24" fill="{PRIMARY}">参考 ComfyUI 与 dify,子图可任意嵌套,循环体与顶层同一套并行引擎</text>
    ''' + foot()


def slide_pool():
    ox = 200
    # 左:两类档案;中:池;右:被 工作流/智能体 复用
    prof = [("发布账号 · B站", PRIMARY, "已登录"), ("发布账号 · 抖音", PRIMARY, "已登录"), ("通用档案 · 任意站点", GOOD, "可复用")]
    cards = []
    for i,(name,col,tag) in enumerate(prof):
        y = 380 + i*128
        cards.append(f'''<g filter="url(#soft)"><rect x="{ox}" y="{y}" width="560" height="104" rx="18" fill="{PANEL}" stroke="{BORDER}" stroke-width="1.5"/>
          <circle cx="{ox+52}" cy="{y+52}" r="22" fill="{col}" opacity="0.25"/><circle cx="{ox+52}" cy="{y+52}" r="9" fill="{col}"/>
          <text x="{ox+100}" y="{y+48}" font-family="{FONT}" font-size="30" font-weight="700" fill="{INK}">{name}</text>
          <text x="{ox+100}" y="{y+82}" font-family="{FONT}" font-size="22" fill="{MUTE}">{tag} · 持久登录</text></g>''')
    def icon_flow(cx, cy):
        return (f'<g stroke="{PRIMARY}" stroke-width="3.5" fill="{PRIMARY}" stroke-linecap="round">'
                f'<line x1="{cx-16}" y1="{cy-18}" x2="{cx+14}" y2="{cy}"/><line x1="{cx+14}" y1="{cy}" x2="{cx-16}" y2="{cy+18}"/>'
                f'<circle cx="{cx-16}" cy="{cy-18}" r="7"/><circle cx="{cx+14}" cy="{cy}" r="7"/><circle cx="{cx-16}" cy="{cy+18}" r="7"/></g>')
    reuse = []
    for i, lab in enumerate(["工作流复用", "智能体复用"]):
        y = 430 + i*180
        ico = icon_flow(1340, y+65) if i == 0 else node_m(1340, y+65, 0.62, PRIMARY, glow=False)
        reuse.append(f'''<g filter="url(#soft)"><rect x="1280" y="{y}" width="440" height="130" rx="20" fill="{PANEL}" stroke="{BORDER}" stroke-width="1.5"/></g>
          {ico}
          <text x="1400" y="{y+62}" font-family="{FONT}" font-size="30" font-weight="700" fill="{INK}">{lab}</text>
          <text x="1400" y="{y+96}" font-family="{FONT}" font-size="22" fill="{MUTE}">复用登录态跑任务</text>''')
        reuse.append(edge(830, 490, 1280, y+65))
    return head() + f'''
    {kicker(ox, 300, "浏览器池")} {new_badge()}
    <text x="{ox}" y="352" font-family="{FONT}" font-size="66" font-weight="800" fill="{INK}">统一你的登录身份</text>
    {"".join(cards)}
    {"".join(reuse)}
    <text x="{ox}" y="920" font-family="{FONT}" font-size="29" fill="{MUTE}">发布账号 + 任意站点登录,一处管理;工作流与智能体都能安全复用 —— 不再只服务自媒体</text>
    ''' + foot()


def slide_matrix():
    ox = 200
    badges = []
    x = ox
    for name,col in PLAT:
        w = 260
        badges.append(f'''<g filter="url(#soft)"><rect x="{x}" y="470" width="{w}" height="150" rx="22" fill="{PANEL}" stroke="{BORDER}" stroke-width="1.5"/>
          <circle cx="{x+w/2}" cy="530" r="30" fill="{col}"/>
          <text x="{x+w/2}" y="600" font-family="{FONT}" font-size="34" font-weight="700" fill="{INK}" text-anchor="middle">{name}</text></g>''')
        x += w + 60
    return head() + f'''
    {kicker(ox, 380, "自媒体矩阵发布")}
    <text x="{ox}" y="452" font-family="{FONT}" font-size="72" font-weight="800" fill="{INK}">一次成片,全平台分发</text>
    {"".join(badges)}
    <text x="{W/2}" y="740" font-family="{FONT}" font-size="30" fill="{MUTE}" text-anchor="middle">内嵌浏览器执行器自动上传;标题/简介/封面一次填好,矩阵账号并发投稿</text>
    ''' + foot()


def slide_security():
    ox = 200
    card_x, card_y = 1120, 400
    return head() + f'''
    {kicker(ox, 330, "安全 · 可控")} {new_badge()}
    <text x="{ox}" y="404" font-family="{FONT}" font-size="66" font-weight="800" fill="{INK}">你的登录,你说了算</text>
    <text x="{ox}" y="500" font-family="{FONT}" font-size="34" fill="{MUTE}">智能体能用你的登录身份跑任务,</text>
    <text x="{ox}" y="556" font-family="{FONT}" font-size="34" fill="{MUTE}">但每次都要你在确认卡上<tspan fill="{PRIMARY}" font-weight="700">显式授权</tspan>。</text>
    <text x="{ox}" y="640" font-family="{FONT}" font-size="27" fill="{MUTE}">· 未授权的身份,它一个都动不了</text>
    <text x="{ox}" y="686" font-family="{FONT}" font-size="27" fill="{MUTE}">· 页面内容只当数据,绝不输入密码 / 支付</text>
    <text x="{ox}" y="732" font-family="{FONT}" font-size="27" fill="{MUTE}">· 发帖 / 提交前,先跟你说清楚</text>
    <g filter="url(#soft)"><rect x="{card_x}" y="{card_y}" width="600" height="290" rx="24" fill="{PANEL}" stroke="{PRIMARY}" stroke-width="2"/>
      <text x="{card_x+40}" y="{card_y+70}" font-size="40">🔐</text>
      <text x="{card_x+110}" y="{card_y+78}" font-family="{FONT}" font-size="30" font-weight="700" fill="{INK}">授权请求</text>
      <line x1="{card_x+40}" y1="{card_y+110}" x2="{card_x+560}" y2="{card_y+110}" stroke="{BORDER}"/>
      <text x="{card_x+40}" y="{card_y+165}" font-family="{FONT}" font-size="26" fill="{INK}">⚠️ 智能体请求复用你的浏览器</text>
      <text x="{card_x+40}" y="{card_y+205}" font-family="{FONT}" font-size="26" fill="{INK}">档案「B站主号」的登录身份跑任务</text>
      <rect x="{card_x+300}" y="{card_y+235}" width="120" height="46" rx="23" fill="{PANEL2}"/>
      <text x="{card_x+360}" y="{card_y+265}" font-family="{FONT}" font-size="24" fill="{MUTE}" text-anchor="middle">拒绝</text>
      <rect x="{card_x+440}" y="{card_y+235}" width="120" height="46" rx="23" fill="{PRIMARY}"/>
      <text x="{card_x+500}" y="{card_y+265}" font-family="{FONT}" font-size="24" fill="#fff" text-anchor="middle">允许</text></g>
    ''' + foot()


def slide_cta():
    return head() + f'''
    {node_m(W/2, 380, 2.6, PRIMARY)}
    <text x="{W/2}" y="600" font-family="{FONT}" font-size="88" font-weight="800" fill="{INK}" text-anchor="middle">Mibu</text>
    <text x="{W/2}" y="676" font-family="{FONT}" font-size="34" fill="{MUTE}" text-anchor="middle">本地优先 · 全链路 AI 视频创作工作室</text>
    <rect x="{W/2-230}" y="760" width="460" height="72" rx="36" fill="none" stroke="{BORDER}" stroke-width="1.5"/>
    <text x="{W/2}" y="806" font-family="{MONO}" font-size="28" fill="{PRIMARY}" text-anchor="middle">1142704468@qq.com</text>
    ''' + foot()


SLIDE_FUNCS = [
    ("01_hero", slide_hero, 3.6),
    ("02_pipeline", slide_pipeline, 3.8),
    ("03_nle", slide_nle, 3.6),
    ("04_ai", slide_ai, 3.8),
    ("05_workflow", slide_workflow, 4.2),
    ("06_pool", slide_pool, 4.4),
    ("07_matrix", slide_matrix, 3.6),
    ("08_security", slide_security, 4.4),
    ("09_cta", slide_cta, 4.0),
]
XFADE = 0.7  # 交叉溶解时长


def render_slides():
    pngs = []
    for name, fn, _ in SLIDE_FUNCS:
        svg_path = os.path.join(SLIDES, name + ".svg")
        png_path = os.path.join(SLIDES, name + ".png")
        with open(svg_path, "w") as f:
            f.write(fn())
        subprocess.run(["rsvg-convert", "-w", str(W*2), "-h", str(H*2), svg_path, "-o", png_path], check=True)
        pngs.append((png_path, dict(SLIDE_FUNCS_D)[name]))
    return pngs


SLIDE_FUNCS_D = {n: d for n, _, d in SLIDE_FUNCS}


def build_video():
    pngs = render_slides()
    out = os.path.join(HERE, "mibu-promo.mp4")
    # 每片:loop 成时长 dur 的片段 + 缓慢推近(zoompan)。fps 30。
    inputs = []
    filters = []
    for i, (png, dur) in enumerate(pngs):
        inputs += ["-loop", "1", "-t", f"{dur}", "-i", png]
        frames = int(dur * 30)
        # 轻微推近:1.0 → 1.06
        filters.append(
            f"[{i}:v]scale={W*2}:{H*2},zoompan=z='min(zoom+0.0006,1.06)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps=30,"
            f"setsar=1,format=yuv420p[v{i}]"
        )
    # xfade 链
    chain = ""
    prev = "v0"
    offset = 0.0
    for i in range(1, len(pngs)):
        dur_prev = pngs[i-1][1]
        offset += dur_prev - XFADE
        outp = f"x{i}"
        chain += f"[{prev}][v{i}]xfade=transition=fade:duration={XFADE}:offset={offset:.3f}[{outp}];"
        prev = outp
    total = sum(d for _, d in pngs) - XFADE * (len(pngs) - 1)
    fc = ";".join(filters) + ";" + chain.rstrip(";")
    # 音频:两层低频正弦做柔和垫底 + 整体淡入淡出
    audio_fc = (f"aevalsrc=0.06*sin(2*PI*146.83*t)+0.045*sin(2*PI*220*t):s=44100:d={total:.2f},"
                f"tremolo=f=0.15:d=0.5,afade=t=in:st=0:d=1.2,afade=t=out:st={total-1.5:.2f}:d=1.5,"
                f"lowpass=f=900,volume=0.5[a]")
    cmd = ["ffmpeg", "-y", *inputs,
           "-filter_complex", fc + ";" + audio_fc,
           "-map", f"[{prev}]", "-map", "[a]",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "160k",
           "-t", f"{total:.2f}", out]
    subprocess.run(cmd, check=True)
    print("OUT", out, f"{total:.1f}s")
    return out


if __name__ == "__main__":
    build_video()
