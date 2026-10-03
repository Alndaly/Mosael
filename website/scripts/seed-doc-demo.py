#!/usr/bin/env python3
"""Start and seed the isolated demo environment used for documentation captures.

  backend/.venv/bin/python website/scripts/seed-doc-demo.py up --dir /private/path/mosael-demo
  backend/.venv/bin/python website/scripts/seed-doc-demo.py down --dir /private/path/mosael-demo

`up` prepares the licensed sample media, starts an isolated backend (port 8812, its own
MOSAEL_DATA_DIR under --dir) and a frontend dev server (port 5274) pointed at it, registers a
local demo administrator through the app's own sign-up flow and creates the sample content
through the backend's HTTP API. It writes two private files the capture scripts read:

  <dir>/token.json    the demo session token (a JSON string) — never commit it
  <dir>/fixture.json  workspace / project / sequence / board / workflow / scene / note / asset IDs

Nothing here talks to a personal backend: it refuses the default dev ports (8800 / 5173) and any
data directory inside ~/.mosael, and checks that the backend on the port is the one using --dir.
No provider keys are configured; AI pages show their real unconfigured state.

Sample footage: Big Buck Bunny trailer, (c) 2008 Blender Foundation, CC BY 3.0, downloaded directly
(proxy variables cleared) from https://media.w3.org/2010/05/bunny/trailer.mp4. Narration is
synthesized locally with macOS `say` (Samantha / Tingting).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
TRAILER_URL = "https://media.w3.org/2010/05/bunny/trailer.mp4"
API_PORT = 8812
APP_PORT = 5274
USERNAME = "creator"
DISPLAY_NAME = "Mosael Demo"
NO_PROXY_ENV = {key: "" for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")}

#: Excerpts cut from the trailer: (key, start, end). Only picture segments, no title cards.
EXCERPTS = [
    ("forest", 4.45, 6.3),
    ("bunny", 9.15, 11.1),
    ("rodents", 13.25, 16.55),
    ("ambush", 18.9, 22.7),
    ("butterfly", 24.97, 26.75),
    ("title", 26.9, 29.9),
]

#: Stills saved with the app's own "save this frame": (asset key, source excerpt, seconds into it).
FRAMES = [
    ("forest-frame", "forest", 1.2), ("bunny-frame", "bunny", 1.0), ("meadow-frame", "rodents", 0.3),
    ("closeup-frame", "rodents", 2.95), ("frank-frame", "butterfly", 0.35), ("bow-frame", "ambush", 0.3),
]

#: Narration sentences per language; each is synthesized separately so subtitle cues match exactly.
NARRATION = {
    "zh": ["从一个镜头开始。", "把它放上时间线。", "加上标题，调好声音。", "做成你自己的片子。"],
    "en": ["Start with a single shot.", "Place it on the timeline.", "Add a title, shape the sound.", "Make it your own."],
}
VOICE = {"zh": "Tingting", "en": "Samantha"}

#: Everything a viewer reads in the demo workspace, per interface language.
TEXT = {
    "zh": {
        "workspace": "演示工作区",
        "project": "Big Buck Bunny · 剪辑练习",
        "project2": "Big Buck Bunny · 竖屏版",
        "sequence": "主时间线",
        "assets": {
            "forest": "林间光影", "bunny": "主角登场", "rodents": "三只捣蛋鬼", "ambush": "森林伏击",
            "butterfly": "松鼠与蝴蝶", "title": "片名", "trailer": "Big Buck Bunny 预告片", "narration": "剪辑旁白",
            "forest-frame": "林间光影 · 第 1 帧", "bunny-frame": "角色参考 · 第 2 帧", "meadow-frame": "草地场景 · 第 3 帧",
            "closeup-frame": "大兔子 · 特写", "frank-frame": "弗兰克 · 参考", "bow-frame": "木弓 · 参考",
            "shotlist": "分镜脚本", "bunny-gif": "主角登场 · 动图",
        },
        "title_text": "大兔子的一天",
        "shotlist": {
            "title": "Big Buck Bunny · 分镜脚本",
            "subtitle": "剪辑练习用的分镜表 · 素材来自 Big Buck Bunny 预告片(© Blender Foundation,CC BY 3.0)",
            "head": ["镜头", "画面", "时长", "旁白 / 字幕"],
            "rows": [
                ["1", "林间光影:清晨的树洞与草坡", "1.9 秒", "从一个镜头开始。"],
                ["2", "主角登场:大兔子走出草地", "2.1 秒", "把它放上时间线。"],
                ["3", "三只捣蛋鬼:松鼠们的恶作剧", "3.4 秒", "加上标题，调好声音。"],
                ["4", "森林伏击:木弓、树林与追逐", "3.8 秒", "做成你自己的片子。"],
            ],
            "notes_title": "剪辑要点",
            "notes": ["画面和配乐放在一个链接组里,移动时一起走。", "字幕中英两条轨,导出时合成底部一框。", "片名用描边花字,停留 3.9 秒。"],
            "page2": "第 2 页 · 镜头参考",
        },
        "notes": [
            {"key": "brief", "title": "展厅影像 · 创作要求", "tags": ["展厅", "要求"], "markdown": (
                "# 展厅影像\n\n用一个连续镜头,串起三间不同色温的展厅。\n\n> 从暖光走到冷光,最后停在展台上的产品。\n\n"
                "## 创作要求\n\n- 保持人物与空间的真实比例\n- 主体始终清晰,镜头缓慢推进\n- 最后一间展厅突出产品与侧光\n\n"
                "## 镜头节奏\n\n| 段落 | 时长 | 机位 |\n| --- | --- | --- |\n| 第一间 | 3 秒 | 门口平视 |\n"
                "| 第二间 | 3 秒 | 穿门推进 |\n| 第三间 | 4 秒 | 绕到展台侧面 |\n")},
            {"key": "rhythm", "title": "剪辑节奏笔记", "tags": ["剪辑"], "markdown": (
                "# 剪辑节奏笔记\n\n预告片的节奏是「字卡 — 画面 — 字卡」交替,每个画面停留不到两秒。\n\n"
                "- 先放画面,再放旁白,最后对齐字幕\n- 配乐和画面放在同一个链接组\n- 片名停留时间要比一句旁白长\n\n"
                "```text\n00:00  林间光影\n00:02  主角登场\n00:04  三只捣蛋鬼\n```\n")},
            {"key": "voice", "title": "旁白稿", "tags": ["旁白"], "markdown": (
                "# 旁白稿\n\n1. 从一个镜头开始。\n2. 把它放上时间线。\n3. 加上标题，调好声音。\n4. 做成你自己的片子。\n\n"
                "旁白用 macOS 自带的 Tingting 声音在本机合成。\n")},
        ],
        "board": "镜头与灵感",
        "board_notes": ["镜头练习\n\n从一个镜头开始,\n把灵感变成一段故事。", "Big Buck Bunny\nBlender Foundation · CC BY 3.0\n\n参考画面 → 时间线 → 成片"],
        "board_draft": "让画面中的阳光缓缓移动",
        "board_image": "清晨逆光的林间草地,大兔子坐在树洞前",
        "board2": "展厅创作",
        "board3": "粗剪 · 三个镜头",
        "board2_shot": "沿着三间展厅缓缓推进",
        "board2_note": "以这份文档为参考,写一段简洁的展厅介绍。",
        "markers": ["开场", "结尾"],
        "entities": [
            {"key": "buck", "kind": "character", "name": "大兔子 Buck", "tags": ["主角"],
             "description": "温和的大个子兔子,被三只捣蛋鬼惹恼之后决定反击。",
             "prompt": "灰白色的大兔子,长耳朵,圆肚子,三维动画风格",
             "refs": [("bunny-frame", "front"), ("closeup-frame", "closeup")]},
            {"key": "frank", "kind": "character", "name": "弗兰克 Frank", "tags": ["反派"],
             "description": "三只捣蛋鬼里的飞鼠,最爱欺负弱小。", "prompt": "灰色飞鼠,眯眼坏笑,三维动画风格",
             "refs": [("frank-frame", "front")]},
            {"key": "meadow", "kind": "location", "name": "林间草地", "tags": ["外景"],
             "description": "大兔子树洞前的草坡,清晨逆光。", "prompt": "清晨逆光的林间草坡,树洞,野花",
             "refs": [("forest-frame", "wide"), ("meadow-frame", "concept")]},
            {"key": "bow", "kind": "prop", "name": "木弓", "tags": ["道具"],
             "description": "大兔子用树枝和藤蔓做的弓。", "prompt": "用树枝和藤蔓做成的简易木弓",
             "refs": [("bow-frame", "closeup")]},
        ],
        "roundup": {
            "name": "每天整理创作素材", "description": "把视频素材打上标签,列一份清单存成笔记。",
            "start": "设置标签与清单标题", "find": "找出全部视频素材", "tag": "给它们打上标签",
            "summary": "写一段清单", "save": "存成笔记", "output": "交付清单",
            "tag_value": "待剪", "report_title": "本周素材清单",
            "template": "本周共 {{find.count}} 段视频,都已打上「{{start.tag}}」标签。\n\n在素材库里按这个标签筛选就能找到它们。",
        },
        "schedule": "每天整理创作素材",
        "export_schedule": "每周一导出主时间线",
        "profile": "通用档案",
        "plugin_connection": "我的网盘",
        "agent_request": "把素材库里名叫「木弓 · 参考」的那张图片删掉。",
    },
    "en": {
        "workspace": "Demo workspace",
        "project": "Big Buck Bunny · Editing practice",
        "project2": "Big Buck Bunny · Vertical cut",
        "sequence": "Main timeline",
        "assets": {
            "forest": "Forest light", "bunny": "Enter the hero", "rodents": "Three troublemakers", "ambush": "Forest ambush",
            "butterfly": "Squirrel and butterfly", "title": "Title card", "trailer": "Big Buck Bunny trailer",
            "narration": "Edit narration", "forest-frame": "Forest light · Frame 1", "bunny-frame": "Character reference · Frame 2",
            "meadow-frame": "Meadow · Frame 3", "closeup-frame": "Big Buck · Close-up", "frank-frame": "Frank · Reference",
            "bow-frame": "Wooden bow · Reference", "shotlist": "Shot list", "bunny-gif": "Enter the hero · GIF",
        },
        "title_text": "A day with Big Buck",
        "shotlist": {
            "title": "Big Buck Bunny · Shot list",
            "subtitle": "Shot list for the editing exercise · footage from the Big Buck Bunny trailer (© Blender Foundation, CC BY 3.0)",
            "head": ["Shot", "Picture", "Length", "Narration / subtitle"],
            "rows": [
                ["1", "Forest light: the burrow and the slope at dawn", "1.9 s", "Start with a single shot."],
                ["2", "Enter the hero: Big Buck steps into the meadow", "2.1 s", "Place it on the timeline."],
                ["3", "Three troublemakers: the rodents' prank", "3.4 s", "Add a title, shape the sound."],
                ["4", "Forest ambush: the bow, the woods, the chase", "3.8 s", "Make it your own."],
            ],
            "notes_title": "Editing notes",
            "notes": ["Picture and music share a link group and move together.",
                      "Two subtitle tracks, English and Chinese, export as one box.",
                      "The outlined title stays on screen for 3.9 seconds."],
            "page2": "Page 2 · Shot references",
        },
        "notes": [
            {"key": "brief", "title": "Gallery film · Creative brief", "tags": ["gallery", "brief"], "markdown": (
                "# Gallery film\n\nOne continuous camera move through three rooms with different color temperatures.\n\n"
                "> From warm light to cool light, ending on the product on the plinth.\n\n"
                "## Creative brief\n\n- Keep a human sense of scale\n- Keep the subject clear; move slowly\n"
                "- Finish with the product and a side light in the last room\n\n"
                "## Shot rhythm\n\n| Part | Length | Camera |\n| --- | --- | --- |\n| Room one | 3 s | Eye level at the door |\n"
                "| Room two | 3 s | Push through the doorway |\n| Room three | 4 s | Around the side of the plinth |\n")},
            {"key": "rhythm", "title": "Editing rhythm notes", "tags": ["editing"], "markdown": (
                "# Editing rhythm notes\n\nThe trailer alternates title card, picture, title card; each picture stays for under two seconds.\n\n"
                "- Lay down the pictures first, then the narration, then align the subtitles\n"
                "- Keep music and picture in one link group\n- Hold the title longer than one line of narration\n\n"
                "```text\n00:00  Forest light\n00:02  Enter the hero\n00:04  Three troublemakers\n```\n")},
            {"key": "voice", "title": "Narration script", "tags": ["narration"], "markdown": (
                "# Narration script\n\n1. Start with a single shot.\n2. Place it on the timeline.\n3. Add a title, shape the sound.\n"
                "4. Make it your own.\n\nNarration synthesized locally with the macOS Samantha voice.\n")},
        ],
        "board": "Shots and ideas",
        "board_notes": ["Shot study\n\nStart with one shot\nand turn an idea into a story.",
                        "Big Buck Bunny\nBlender Foundation · CC BY 3.0\n\nReference → timeline → film"],
        "board_draft": "Let the sunlight move gently across the frame",
        "board_image": "A backlit forest meadow at dawn, Big Buck by the burrow",
        "board2": "Gallery story board",
        "board3": "Rough cut · three shots",
        "board2_shot": "A slow push through the three halls",
        "board2_note": "Write a concise gallery introduction using the brief.",
        "markers": ["Opening", "Finale"],
        "entities": [
            {"key": "buck", "kind": "character", "name": "Big Buck", "tags": ["lead"],
             "description": "A gentle, oversized rabbit who strikes back after three troublemakers push him too far.",
             "prompt": "large grey-white rabbit, long ears, round belly, 3D animation style",
             "refs": [("bunny-frame", "front"), ("closeup-frame", "closeup")]},
            {"key": "frank", "kind": "character", "name": "Frank", "tags": ["villain"],
             "description": "The flying squirrel of the three troublemakers; loves picking on the small.",
             "prompt": "grey flying squirrel with a sly grin, 3D animation style", "refs": [("frank-frame", "front")]},
            {"key": "meadow", "kind": "location", "name": "Forest meadow", "tags": ["exterior"],
             "description": "The grassy slope in front of Big Buck's burrow, backlit at dawn.",
             "prompt": "backlit forest meadow at dawn, a burrow under a tree, wild flowers",
             "refs": [("forest-frame", "wide"), ("meadow-frame", "concept")]},
            {"key": "bow", "kind": "prop", "name": "Wooden bow", "tags": ["prop"],
             "description": "The bow Big Buck makes from a branch and a vine.", "prompt": "simple bow made from a branch and a vine",
             "refs": [("bow-frame", "closeup")]},
        ],
        "roundup": {
            "name": "Daily asset roundup", "description": "Tag the video assets and save a list as a note.",
            "start": "Tag and list title", "find": "Find all video assets", "tag": "Tag them",
            "summary": "Write the list", "save": "Save as a note", "output": "Deliver the list",
            "tag_value": "to-edit", "report_title": "This week's assets",
            "template": "{{find.count}} videos this week, all tagged “{{start.tag}}”.\n\nFilter the asset library by that tag to find them.",
        },
        "schedule": "Daily asset roundup",
        "export_schedule": "Export the main timeline every Monday",
        "profile": "General profile",
        "plugin_connection": "My netdisk",
        "agent_request": "Delete the image called “Wooden bow · Reference” from the asset library. Please reply in English.",
    },
}

#: Official templates instantiated in each workspace (the graph's node names follow that workspace's language).
TEMPLATES = ["transcript_video_cleanup", "full_video_generation", "account_analysis", "viral_video_breakdown", "comment_insights"]

#: Example plugins from plugins/examples, copied into the demo plugins directory and picked up by the app's
#: own "scan plugins" (the same path as dropping a plugin folder there by hand).
EXAMPLE_PLUGINS = ["baidu-pan", "manim", "tikhub", "text-toolkit"]

#: The demo's generation connection: a placeholder (closed local port, placeholder key), named as such.
PLACEHOLDER_PROVIDER = "演示占位 · Placeholder"
#: With --local-chat, the agent talks to a model served by Ollama on this machine.
LOCAL_CHAT_PROVIDER = "本机 Ollama · Local"


# ------------------------------------------------------------------------------------------------ guards


def data_dir_id(path: Path) -> str:
    """Same fingerprint the backend reports on /api/health (app.core.lifeline.data_dir_id)."""
    return hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]


def check_isolated(base: Path) -> None:
    personal = (Path.home() / ".mosael").resolve()
    if base == personal or personal in base.parents:
        sys.exit("Refusing to use a directory inside ~/.mosael; pick a private scratch directory.")
    if ROOT in base.parents and not (ROOT / ".claude") in base.parents:
        # Inside the repository it must at least be an ignored location; a stray demo database must never be committed.
        ignored = subprocess.run(["git", "check-ignore", "-q", str(base)], cwd=ROOT).returncode == 0
        if not ignored:
            sys.exit(f"{base} is inside the repository but not git-ignored.")


def client(token: str | None = None, locale: str = "zh") -> httpx.Client:
    headers = {"Accept-Language": "zh-CN" if locale == "zh" else "en-US"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    # trust_env=False: loopback requests must not be sent to a developer's HTTP proxy.
    return httpx.Client(base_url=f"http://127.0.0.1:{API_PORT}/api", headers=headers, timeout=120, trust_env=False)


def ok(response: httpx.Response) -> dict | list:
    if response.status_code >= 400:
        raise SystemExit(f"{response.request.method} {response.request.url.path} -> {response.status_code}: {response.text[:600]}")
    return response.json() if response.content else {}


# ------------------------------------------------------------------------------------------------ media


def run(cmd: list[str], **kwargs) -> None:
    subprocess.run(cmd, check=True, **kwargs)


def prepare_media(media: Path) -> None:
    """Download the trailer once, cut excerpts, and synthesize the narration sentences."""
    media.mkdir(parents=True, exist_ok=True)
    trailer = media / "bbb-trailer.mp4"
    if not trailer.exists():
        print("Downloading the Big Buck Bunny trailer (CC BY 3.0)…", flush=True)
        run(["curl", "-sS", "-L", "--fail", "--noproxy", "*", "-o", str(trailer), TRAILER_URL], env={**os.environ, **NO_PROXY_ENV})
    for key, start, end in EXCERPTS:
        target = media / f"{key}.mp4"
        if target.exists():
            continue
        run(["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-to", str(end), "-i", str(trailer),
             "-vf", "scale=1280:720:flags=lanczos,fps=25", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(target)])
    for locale, sentences in NARRATION.items():
        target = media / f"narration-{locale}.m4a"
        timing = media / f"narration-{locale}.json"
        if target.exists() and timing.exists():
            continue
        parts, cues, cursor, gap = [], [], 0.4, 0.55
        silence = media / "gap.wav"
        run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", str(gap), str(silence)])
        lead = media / "lead.wav"
        run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "0.4", str(lead)])
        parts.append(lead)
        for index, sentence in enumerate(sentences):
            aiff = media / f"say-{locale}-{index}.aiff"
            wav = media / f"say-{locale}-{index}.wav"
            run(["say", "-v", VOICE[locale], "-o", str(aiff), sentence])
            run(["ffmpeg", "-v", "error", "-y", "-i", str(aiff), "-ar", "44100", "-ac", "1", str(wav)])
            duration = float(subprocess.check_output(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(wav)], text=True))
            cues.append({"start": round(cursor, 3), "end": round(cursor + duration, 3)})
            cursor += duration + gap
            parts += [wav, silence]
        listing = media / f"concat-{locale}.txt"
        listing.write_text("".join(f"file '{p.name}'\n" for p in parts))
        run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c:a", "aac", "-b:a", "128k", str(target)], cwd=media)
        timing.write_text(json.dumps(cues))


def srt(cues: list[dict], lines: list[str]) -> str:
    def stamp(seconds: float) -> str:
        ms = int(round(seconds * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    return "\n".join(f"{i + 1}\n{stamp(c['start'])} --> {stamp(c['end'])}\n{text}\n" for i, (c, text) in enumerate(zip(cues, lines)))


# ------------------------------------------------------------------------------------------------ processes


def start_servers(base: Path) -> None:
    logs = base / "logs"
    logs.mkdir(exist_ok=True)
    pids: dict[str, int] = {}
    data = (base / "data").resolve()
    env = {
        **os.environ,
        "MOSAEL_DATA_DIR": str(data),
        "MOSAEL_BACKEND_PORT": str(API_PORT),
        "MOSAEL_CORS_ORIGINS": f"http://127.0.0.1:{APP_PORT},http://localhost:{APP_PORT}",
        # No Feishu bots. The scheduler loop stays on: it is what settles a run record once the workflow it
        # started has finished (the seeded task is due at 21:00, outside a normal recording session).
        "MOSAEL_FEISHU_AUTOSTART": "0",
        "MOSAEL_LOCAL_DESKTOP": "1",
        "MOSAEL_APP_VERSION": json.loads((ROOT / "package.json").read_text())["version"],
    }
    if not healthy():
        backend = subprocess.Popen(
            [str(ROOT / "backend/.venv/bin/python"), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(API_PORT)],
            cwd=ROOT / "backend", env=env, stdout=open(logs / "backend.log", "ab"), stderr=subprocess.STDOUT, start_new_session=True)
        pids["backend"] = backend.pid
    if not app_up():
        vite = ROOT / "frontend/node_modules/.bin/vite"
        frontend = subprocess.Popen(
            [str(vite), "--host", "127.0.0.1", "--port", str(APP_PORT), "--strictPort"],
            cwd=ROOT / "frontend", stdout=open(logs / "frontend.log", "ab"), stderr=subprocess.STDOUT, start_new_session=True)
        pids["frontend"] = frontend.pid
    if pids:
        (base / "pids.json").write_text(json.dumps({**read_pids(base), **pids}))
    for _ in range(120):
        if healthy() and app_up():
            break
        time.sleep(1)
    else:
        sys.exit(f"Servers did not come up; see {logs}.")
    health = ok(client().get("/health"))
    if health.get("data_dir_id") != data_dir_id(data):
        sys.exit(f"The backend on port {API_PORT} is not using {data}; stop it first.")


def healthy() -> bool:
    try:
        return client().get("/health").status_code == 200
    except httpx.HTTPError:
        return False


def app_up() -> bool:
    try:
        return httpx.get(f"http://127.0.0.1:{APP_PORT}/", timeout=5, trust_env=False).status_code == 200
    except httpx.HTTPError:
        return False


def read_pids(base: Path) -> dict[str, int]:
    path = base / "pids.json"
    return json.loads(path.read_text()) if path.exists() else {}


def stop_servers(base: Path) -> None:
    for name, pid in read_pids(base).items():
        try:
            os.killpg(pid, signal.SIGTERM)
            print(f"Stopped {name} ({pid})")
        except ProcessLookupError:
            pass
    (base / "pids.json").unlink(missing_ok=True)


# ------------------------------------------------------------------------------------------------ seeding


class Seeder:
    def __init__(self, base: Path, token: str):
        self.base, self.token = base, token
        self.media = base / "media"
        self.fixture: dict = {"locales": {}}

    def api(self, locale: str) -> httpx.Client:
        return client(self.token, locale)

    def upload(self, api: httpx.Client, workspace: str, project: str | None, path: Path, name: str, mime: str) -> dict:
        with path.open("rb") as handle:
            data = {"workspace_id": workspace, "name": name}
            if project:
                data["project_id"] = project
            return ok(api.post("/assets/import", data=data, files={"file": (path.name, handle, mime)}))

    def seed_locale(self, locale: str) -> dict:
        text = TEXT[locale]
        api = self.api(locale)
        out: dict = {"assets": {}}
        workspace = ok(api.post("/workspaces", json={"name": text["workspace"]}))["id"]
        out["workspace"] = workspace
        project = ok(api.post("/projects", json={"workspace_id": workspace, "name": text["project"]}))["id"]
        out["project"] = project
        names = text["assets"]
        assets = out["assets"]
        # Imports, oldest first so the newest (frames) land at the top of the library.
        assets["trailer"] = self.upload(api, workspace, project, self.media / "bbb-trailer.mp4", names["trailer"], "video/mp4")["id"]
        for key, *_ in EXCERPTS:
            assets[key] = self.upload(api, workspace, project, self.media / f"{key}.mp4", names[key], "video/mp4")["id"]
        assets["narration"] = self.upload(api, workspace, project, self.media / f"narration-{locale}.m4a", names["narration"], "audio/mp4")["id"]
        self.wait_assets(api, workspace, list(assets.values()))
        # Frames are taken with the app's own "save this frame" action, so their source chain is real.
        for key, source, at in FRAMES:
            frame = ok(api.post(f"/assets/{assets[source]}/frame", json={"at": at, "project_id": project}))
            ok(api.patch(f"/assets/{frame['id']}", json={"name": names[key]}))
            assets[key] = frame["id"]
        out["sequence"] = self.timeline(api, workspace, project, locale, assets)
        out["project2"], out["sequence2"] = self.vertical_cut(api, workspace, locale, assets)
        # A GIF made with the app's own "convert to GIF" — another real source chain.
        job = ok(api.post(f"/assets/{assets['bunny']}/convert-gif", json={"fps": 12, "width": 480}))
        self.wait_job(api, job["id"])
        gif = next(a for a in ok(api.get("/assets", params={"workspace_id": workspace}))
                   if any(d["asset_id"] == assets["bunny"] and d["op"] == "gif" for d in a.get("derived_from") or []))
        ok(api.patch(f"/assets/{gif['id']}", json={"name": names["bunny-gif"]}))
        assets["bunny-gif"] = gif["id"]
        shotlist = self.shotlist_pdf(locale)
        assets["shotlist"] = self.upload(api, workspace, project, shotlist, names["shotlist"], "application/pdf")["id"]
        ok(api.get(f"/assets/{assets['shotlist']}/extractions"))  # the library parses documents locally on first open
        out["notes"] = {}
        for note in text["notes"]:
            created = ok(api.post("/notes", json={"workspace_id": workspace, "title": note["title"], "markdown": note["markdown"],
                                                  "tags": note["tags"], "project_id": project}))
            out["notes"][note["key"]] = created["id"]
        out["note"] = out["notes"]["brief"]
        out["entities"] = self.entities(api, workspace, locale, assets)
        out["scene"] = self.scene(workspace, locale)
        out["board"], out["board2"], out["board3"] = self.boards(api, workspace, locale, out)
        out["workflows"] = self.workflows(api, workspace, locale)
        out["workflow_names"] = {key: ok(api.get(f"/workflows/{wid}"))["name"] for key, wid in out["workflows"].items()}
        out["workflow"] = out["workflows"]["transcript_video_cleanup"]
        out["schedules"] = self.schedules(api, workspace, project, locale, out)
        ok(api.post("/browser/profiles", json={"workspace_id": workspace, "name": text["profile"]}))
        return out

    def wait_job(self, api: httpx.Client, job_id: str) -> dict:
        for _ in range(300):
            job = ok(api.get(f"/jobs/{job_id}"))
            if job["status"] in ("succeeded", "failed", "cancelled"):
                if job["status"] != "succeeded":
                    sys.exit(f"Job {job_id} ended {job['status']}: {job.get('error') or job.get('message')}")
                return job
            time.sleep(1)
        sys.exit(f"Job {job_id} did not finish")

    def vertical_cut(self, api: httpx.Client, workspace: str, locale: str, assets: dict) -> tuple[str, str]:
        """A second project: a 9:16 cut of three shots, reframed with the app's blurred-fill option."""
        text = TEXT[locale]
        project = ok(api.post("/projects", json={"workspace_id": workspace, "name": text["project2"]}))["id"]
        sequences = ok(api.get(f"/projects/{project}/sequences"))
        sequence = sequences[0] if sequences else ok(api.post("/sequences", json={
            "workspace_id": workspace, "project_id": project, "name": text["sequence"]}))
        sid = sequence["id"]
        for key in ("bunny", "butterfly", "title"):
            ok(api.post(f"/sequences/{sid}/append", json={"asset_id": assets[key]}))
        ok(api.patch(f"/sequences/{sid}/reframe", json={"width": 1080, "height": 1920, "fill_mode": "blur"}))
        return project, sid

    def shotlist_pdf(self, locale: str) -> Path:
        """A two-page shot list PDF made locally (Chromium print-to-PDF) from the excerpts' own frames."""
        from base64 import b64encode
        from playwright.sync_api import sync_playwright

        target = self.media / f"shotlist-{locale}.pdf"
        if target.exists():
            return target
        sheet = TEXT[locale]["shotlist"]
        images = []
        for key, *_ in EXCERPTS[:4]:
            still = self.media / f"still-{key}.jpg"
            if not still.exists():
                run(["ffmpeg", "-v", "error", "-y", "-ss", "0.5", "-i", str(self.media / f"{key}.mp4"), "-frames:v", "1",
                     "-vf", "scale=640:-2", str(still)])
            images.append("data:image/jpeg;base64," + b64encode(still.read_bytes()).decode())
        rows = "".join(f"<tr><td>{r[0]}</td><td>{r[1]}</td><td>{r[2]}</td><td>{r[3]}</td></tr>" for r in sheet["rows"])
        notes = "".join(f"<li>{n}</li>" for n in sheet["notes"])
        figures = "".join(f"<figure><img src='{src}'><figcaption>{row[0]} · {row[1]}</figcaption></figure>"
                          for src, row in zip(images, sheet["rows"]))
        html = f"""<html><head><meta charset='utf-8'><style>
          body{{font-family:-apple-system,'PingFang SC',sans-serif;margin:48px;color:#1f2430}}
          h1{{font-size:26px;margin:0 0 6px}} p.sub{{color:#5b6372;font-size:12px;margin:0 0 24px}}
          table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{border:1px solid #d5d9e0;padding:8px 10px;text-align:left}}
          th{{background:#eef1f6}} h2{{font-size:17px;margin:28px 0 8px}} li{{margin:4px 0;font-size:13px}}
          .page{{page-break-before:always}} figure{{display:inline-block;width:46%;margin:0 2% 18px 0;vertical-align:top}}
          img{{width:100%;border-radius:6px}} figcaption{{font-size:12px;color:#5b6372;margin-top:4px}}
        </style></head><body>
          <h1>{sheet['title']}</h1><p class='sub'>{sheet['subtitle']}</p>
          <table><tr>{''.join(f'<th>{h}</th>' for h in sheet['head'])}</tr>{rows}</table>
          <h2>{sheet['notes_title']}</h2><ul>{notes}</ul>
          <div class='page'><h1>{sheet['page2']}</h1><p class='sub'>{sheet['subtitle']}</p>{figures}</div>
        </body></html>"""
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            page.pdf(path=str(target), format="A4", print_background=True)
            browser.close()
        return target

    def entities(self, api: httpx.Client, workspace: str, locale: str, assets: dict) -> dict:
        out = {}
        for entity in TEXT[locale]["entities"]:
            created = ok(api.post("/entities", json={
                "workspace_id": workspace, "kind": entity["kind"], "name": entity["name"], "description": entity["description"],
                "prompt": entity["prompt"], "tags": entity["tags"]}))
            for index, (asset_key, role) in enumerate(entity["refs"]):
                ok(api.post(f"/entities/{created['id']}/references", json={"asset_id": assets[asset_key], "role": role, "cover": index == 0}))
            out[entity["key"]] = created["id"]
        return out

    def scene(self, workspace: str, locale: str) -> str:
        """The three-room gallery is the app's own example scene: create it with the page's button, as a user would."""
        from playwright.sync_api import sync_playwright

        app = f"http://127.0.0.1:{APP_PORT}"
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(app, wait_until="domcontentloaded")
            page.evaluate("""([api, token, locale, ws]) => {
                localStorage.setItem('mosael.server.url', api);
                localStorage.setItem('mosael.auth.token', token);
                localStorage.setItem('mosael.preferences', JSON.stringify({theme: 'light', locale, font: 'default'}));
                localStorage.setItem('mosael:workspace', ws);
            }""", [f"http://127.0.0.1:{API_PORT}", self.token, "zh-CN" if locale == "zh" else "en-US", workspace])
            page.goto(app + "/#/scenes", wait_until="networkidle")
            label = "打开三间展厅示例" if locale == "zh" else "Open the three-hall sample"
            page.get_by_role("button", name=label, exact=True).click()
            page.wait_for_function("location.hash.includes('scene=')", timeout=30000)
            scene_id = page.evaluate("new URLSearchParams(location.hash.split('?')[1]).get('scene')")
            browser.close()
        return scene_id

    def boards(self, api: httpx.Client, workspace: str, locale: str, out: dict) -> tuple[str, str, str]:
        text, assets, entities = TEXT[locale], out["assets"], out["entities"]
        # The story study: references, a character and an empty video cell waiting for its prompt.
        study = {
            "items": [
                {"id": "idea", "kind": "note", "x": 0, "y": 0, "width": 260, "height": 150, "text": text["board_notes"][0], "color": "blue"},
                {"id": "credit", "kind": "note", "x": 0, "y": 220, "width": 260, "height": 190, "text": text["board_notes"][1], "color": "yellow"},
                {"id": "reference-frame", "kind": "image", "x": 310, "y": 0, "width": 300, "height": 169, "asset_id": assets["forest-frame"]},
                {"id": "reference-clip", "kind": "video", "x": 310, "y": 220, "width": 300, "height": 169, "asset_id": assets["bunny"]},
                {"id": "draft-video", "kind": "video", "x": 670, "y": 0, "width": 300, "height": 169, "form": {"prompt": text["board_draft"]}},
                {"id": "draft-image", "kind": "image", "x": 670, "y": 220, "width": 300, "height": 169, "form": {"prompt": text["board_image"]}},
                {"id": "hero", "kind": "entity", "x": 1030, "y": 0, "width": 200, "height": 250, "entity_id": entities["buck"]},
            ],
            "edges": [
                {"source": "idea", "target": "reference-frame"},
                {"source": "reference-frame", "target": "draft-video"},
            ],
        }
        board = ok(api.post("/boards", json={"workspace_id": workspace, "name": text["board"], "canvas": study}))
        # The gallery: a note document, the 3D scene cell feeding an empty video cell, two viewport markers.
        note = ok(api.get(f"/notes/{out['notes']['brief']}", params={"workspace_id": workspace}))
        gallery = {
            "items": [
                {"id": "brief", "kind": "document", "x": 0, "y": 0, "width": 340, "height": 360,
                 "note_id": note["id"], "note_revision": note["revision"]},
                {"id": "prompt", "kind": "note", "x": 400, "y": 0, "width": 280, "height": 180, "text": text["board2_note"], "color": "yellow"},
                {"id": "scene", "kind": "scene", "x": 400, "y": 240, "width": 320, "height": 220, "scene_id": out["scene"]},
                {"id": "shot-video", "kind": "video", "x": 780, "y": 260, "width": 300, "height": 169, "form": {"prompt": text["board2_shot"]}},
            ],
            "edges": [{"source": "brief", "target": "prompt"}, {"source": "scene", "target": "shot-video"}],
            "markers": [
                {"id": "opening", "name": text["markers"][0], "x": -140, "y": 480, "shortcut": "1"},
                {"id": "finale", "name": text["markers"][1], "x": 1120, "y": 480, "shortcut": "2"},
            ],
        }
        board2 = ok(api.post("/boards", json={"workspace_id": workspace, "name": text["board2"], "canvas": gallery}))
        # The rough cut: three shots connected into a timeline cell (its own timeline in the board's project).
        board3 = ok(api.post("/boards", json={"workspace_id": workspace, "name": text["board3"], "canvas": {"items": [], "edges": []}}))
        timeline = ok(api.post(f"/boards/{board3['id']}/sequences", json={"workspace_id": workspace}))["sequence_id"]
        for key in ("bunny", "butterfly", "title"):
            ok(api.post(f"/sequences/{timeline}/append", json={"asset_id": assets[key]}))
        rough = {
            "items": [
                *({"id": f"shot-{i + 1}", "kind": "video", "x": 0, "y": i * 190, "width": 260, "height": 146, "asset_id": assets[key]}
                  for i, key in enumerate(("bunny", "butterfly", "title"))),
                {"id": "timeline", "kind": "sequence", "x": 340, "y": 20, "width": 560, "height": 400, "sequence_id": timeline},
            ],
            "edges": [{"source": f"shot-{i}", "target": "timeline"} for i in (1, 2, 3)],
        }
        ok(api.patch(f"/boards/{board3['id']}", json={"workspace_id": workspace, "base_revision": board3["revision"], "canvas": rough}))
        return board["id"], board2["id"], board3["id"]

    def workflows(self, api: httpx.Client, workspace: str, locale: str) -> dict:
        names = {t["id"]: t["name"] for t in ok(api.get("/workflows/templates"))}
        out = {}
        for template in TEMPLATES:
            out[template] = ok(api.post("/workflows", json={"workspace_id": workspace, "name": names[template], "template_id": template}))["id"]
        # A small workflow that runs entirely on this machine, so its run history and outputs are real.
        r = TEXT[locale]["roundup"]
        node = lambda nid, kind, name, x, config: {"id": nid, "type": kind, "name": name, "position": {"x": x, "y": 200}, "config": config}
        graph = {
            "nodes": [
                node("start", "start", r["start"], 0, {"params": {"tag": r["tag_value"], "report_title": r["report_title"]},
                                                       "required_params": ["tag"]}),
                node("find", "asset_query", r["find"], 290, {"kind": "video", "name_contains": "", "tags": "", "limit": 50}),
                node("tag", "asset_tag", r["tag"], 580, {"asset_ids": "{{find.ids}}", "tags": "{{start.tag}}", "mode": "add"}),
                node("summary", "template", r["summary"], 870, {"template": r["template"]}),
                node("save", "note_create", r["save"], 1160, {"title": "{{start.report_title}}", "markdown": "{{summary.text}}", "tags": "{{start.tag}}"}),
                node("output", "output", r["output"], 1450, {"values": {"note_id": "{{save.note_id}}", "count": "{{find.count}}"}}),
            ],
            "edges": [{"id": f"{a}-{b}", "source": a, "target": b} for a, b in
                      [("start", "find"), ("find", "tag"), ("tag", "summary"), ("summary", "save"), ("save", "output")]],
        }
        roundup = ok(api.post("/workflows", json={"workspace_id": workspace, "name": r["name"], "description": r["description"], "graph": graph}))
        out["roundup"] = roundup["id"]
        return out

    def schedules(self, api: httpx.Client, workspace: str, project: str, locale: str, out: dict) -> dict:
        text = TEXT[locale]
        timezone = "Asia/Shanghai" if locale == "zh" else "Europe/London"
        roundup = ok(api.post("/scheduled-tasks", json={
            "workspace_id": workspace, "project_id": project, "name": text["schedule"], "kind": "workflow", "trigger_type": "daily",
            "schedule": {"time": "21:00"}, "timezone": timezone, "enabled": True,
            "payload": {"workflow_id": out["workflows"]["roundup"], "params": {}}}))
        export = ok(api.post("/scheduled-tasks", json={
            "workspace_id": workspace, "project_id": project, "name": text["export_schedule"], "kind": "render", "trigger_type": "weekly",
            "schedule": {"time": "18:00", "weekday": 0}, "timezone": timezone, "enabled": False,
            "payload": {"sequence_id": out["sequence"]}}))
        # One real run through the scheduler's own "run now": the run record, the workflow's run history,
        # the tags on the videos and the saved list note all come from it.
        started = ok(api.post(f"/scheduled-tasks/{roundup['id']}/run"))
        self.wait_job(api, started["job"]["id"])
        for _ in range(60):
            runs = ok(api.get(f"/workflows/{out['workflows']['roundup']}/runs"))
            if runs and runs[0]["status"] in ("succeeded", "failed"):
                if runs[0]["status"] != "succeeded":
                    sys.exit(f"The roundup workflow failed: {runs[0].get('error')}")
                break
            time.sleep(1)
        # The scheduler loop copies the workflow's end state onto the task's run record.
        for _ in range(90):
            records = ok(api.get(f"/scheduled-tasks/{roundup['id']}/runs"))
            if records and records[0]["status"] in ("succeeded", "failed", "cancelled"):
                break
            time.sleep(1)
        else:
            sys.exit("The scheduled run record never settled; is the scheduler loop running?")
        return {"roundup": roundup["id"], "export": export["id"]}

    def plugins(self) -> None:
        """Copy the example plugins into the demo plugins directory and let the app scan them."""
        target = self.base / "data" / "plugins"
        target.mkdir(parents=True, exist_ok=True)
        for name in EXAMPLE_PLUGINS:
            if not (target / name).exists():
                shutil.copytree(ROOT / "plugins/examples" / name, target / name)
        api = self.api("zh")
        ok(api.post("/plugins/scan"))
        # One connection without credentials: the plugin page shows it as not signed in, which is the truth.
        ok(api.post("/plugins/dev.mosael.baidu-pan/instances", json={"name": "演示网盘 · Demo netdisk", "config": {}}))

    def placeholder_provider(self) -> None:
        """A generation connection that is configured but cannot run: its endpoint is a closed local port and its
        key is a placeholder string. Generation panels then show their configured, not-yet-run state (model picker,
        "N×"); nothing is ever generated, and the name says what it is."""
        api = self.api("zh")
        profile = ok(api.post("/settings/providers", json={
            "name": PLACEHOLDER_PROVIDER, "vendor": "alibaba",
            "config": {"api_key": "placeholder-not-a-key", "base_url": "http://127.0.0.1:9/compatible-mode/v1", "default_model": ""}}))
        # Image (up to four per run, so the board shows "N×"), text-to-video, talking photo and lip-sync models.
        for model in ("qwen-image", "wan2.7-t2v", "wan2.2-s2v", "videoretalk"):
            ok(api.post(f"/settings/providers/{profile['id']}/models", json={"model_id": model, "enabled": True}))
        for capability, model in (("image", "qwen-image"), ("video", "wan2.7-t2v")):
            ok(api.put(f"/settings/provider-defaults/{capability}", json={"provider_profile_id": profile["id"], "model": model}))

    def local_chat(self, model: str) -> None:
        """Optional: a real chat model served by Ollama on this machine, for the agent's confirmation-card scene.
        Its replies are genuine model output. Only the named model is enabled — Ollama's list can include
        `:cloud` models that would run on someone's Ollama account, and those stay off."""
        api = self.api("zh")
        profile = ok(api.post("/settings/providers", json={
            "name": LOCAL_CHAT_PROVIDER, "vendor": "openai-compatible",
            "config": {"api_key": "ollama", "base_url": "http://127.0.0.1:11434/v1", "default_model": model}}))
        for entry in ok(api.get(f"/settings/providers/{profile['id']}/models")):
            if entry["id"] != model and entry["enabled"]:
                ok(api.patch(f"/settings/providers/{profile['id']}/models/{entry['id']}", json={"enabled": False}))
        ok(api.put("/settings/provider-defaults/chat", json={"provider_profile_id": profile["id"], "model": model}))
        self.fixture["local_chat"] = model

    def wait_assets(self, api: httpx.Client, workspace: str, ids: list[str]) -> None:
        """Imports probe and thumbnail in the background; wait until every asset has its media info."""
        for _ in range(240):
            rows = {row["id"]: row for row in ok(api.get("/assets", params={"workspace_id": workspace}))}
            pending = [i for i in ids if not (rows.get(i, {}).get("media_info") or {}).get("duration") and rows.get(i, {}).get("kind") in ("video", "audio")]
            if not pending:
                return
            time.sleep(1)
        sys.exit(f"Assets never finished probing: {pending}")

    def timeline(self, api: httpx.Client, workspace: str, project: str, locale: str, assets: dict) -> str:
        text = TEXT[locale]
        sequences = ok(api.get(f"/projects/{project}/sequences"))
        if sequences:
            sequence = sequences[0]
            ok(api.patch(f"/sequences/{sequence['id']}", json={"name": text["sequence"]}))
        else:
            sequence = ok(api.post("/sequences", json={"workspace_id": workspace, "project_id": project, "name": text["sequence"],
                                                        "width": 1920, "height": 1080, "fps": 30}))
        sid = sequence["id"]
        for key, *_ in EXCERPTS:
            sequence = ok(api.post(f"/sequences/{sid}/append", json={"asset_id": assets[key]}))
        # Separate each shot's trailer music onto A1 with the app's own "detach audio": picture and
        # sound stay in one link group (the chain icon on the clips) and the music is turned down.
        for clip in self.clips(sequence, "video"):
            sequence = ok(api.post(f"/sequences/{sid}/clips/{clip['id']}/detach-audio"))
        for clip in self.clips(sequence, "audio"):
            sequence = ok(api.patch(f"/sequences/{sid}/clips/{clip['id']}/gain", json={"gain": 0.3, "muted": False}))
        # Narration on its own audio track.
        narration_track, sequence = self.add_track(api, sid, sequence, "audio")
        duration = self.duration(api, assets["narration"])
        sequence = ok(api.post(f"/sequences/{sid}/clips", json={
            "track_id": narration_track, "asset_id": assets["narration"], "timeline_start": 0.0, "src_in": 0.0, "src_out": duration}))
        # Bilingual subtitles: the interface language first, the other language as the second line.
        cues = json.loads((self.media / f"narration-{locale}.json").read_text())
        other = "en" if locale == "zh" else "zh"
        for lang in (locale, other):
            body = srt(cues, NARRATION[lang]).encode("utf-8")
            ok(api.post(f"/sequences/{sid}/subtitles/import", data={"track_id": ""},
                        files={"file": (f"narration.{lang}.srt", body, "application/x-subrip")}))
        # A styled title (花字) on its own video track above the picture.
        title_track, sequence = self.add_track(api, sid, sequence, "video")
        sequence = ok(api.post(f"/sequences/{sid}/text-clips", json={
            "track_id": title_track, "text": text["title_text"], "timeline_start": 0.0, "duration": 3.9}))
        title = next(c for c in self.clips(sequence, "video") if c["track_id"] == title_track)
        ok(api.patch(f"/sequences/{sid}/clips/{title['id']}/effects", json={"effects": {"text_style": {
            "font_size": 92, "color": "#ffe14d", "stroke_color": "#3a2a00", "stroke_width": 6, "shadow": 3,
            "bold": True, "italic": False, "align": "center", "font_family": "", "font_id": ""}}}))
        ok(api.patch(f"/sequences/{sid}/clips/{title['id']}/transform", json={"transform": {"scale": 1, "x": 0, "y": -0.62, "rotation": 0, "opacity": 1}}))
        return sid

    @staticmethod
    def add_track(api: httpx.Client, sid: str, sequence: dict, kind: str) -> tuple[str, dict]:
        before = {t["id"] for t in sequence["tracks"]}
        sequence = ok(api.post(f"/sequences/{sid}/tracks", json={"kind": kind}))
        return next(t["id"] for t in sequence["tracks"] if t["id"] not in before), sequence

    @staticmethod
    def clips(sequence: dict, kind: str) -> list[dict]:
        return [clip for track in sequence["tracks"] if track["kind"] == kind for clip in track["clips"]]

    @staticmethod
    def duration(api: httpx.Client, asset_id: str) -> float:
        return float(ok(api.get(f"/assets/{asset_id}"))["media_info"]["duration"])


def register(base: Path) -> str:
    """Sign up the local demo administrator (first account on the empty demo backend) or sign back in."""
    secret_file = base / "credentials.json"
    if secret_file.exists():
        credentials = json.loads(secret_file.read_text())
        token = ok(client().post("/auth/login", json={"username": credentials["username"], "password": credentials["password"]}))["token"]
    else:
        credentials = {"username": USERNAME, "password": secrets.token_urlsafe(18)}
        token = ok(client().post("/auth/register", json={**credentials, "display_name": DISPLAY_NAME}))["token"]
        write_private(secret_file, json.dumps(credentials))
    write_private(base / "token.json", json.dumps(token))
    return token


def write_private(path: Path, content: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(content)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["up", "seed", "down"])
    parser.add_argument("--dir", type=Path, required=True, help="private directory for data, media, logs, token and fixture")
    parser.add_argument("--fresh", action="store_true", help="wipe the demo database first (keeps downloaded media)")
    parser.add_argument("--local-chat", default="", metavar="MODEL",
                        help="also connect a chat model served by Ollama on this machine (e.g. qwen3.5:latest); "
                             "the agent scene needs it")
    args = parser.parse_args()
    base = args.dir.expanduser().resolve()
    check_isolated(base)
    base.mkdir(parents=True, exist_ok=True)
    os.chmod(base, 0o700)
    if args.command == "down":
        stop_servers(base)
        return
    if args.fresh:
        stop_servers(base)
        shutil.rmtree(base / "data", ignore_errors=True)
        for name in ("credentials.json", "token.json", "fixture.json"):
            (base / name).unlink(missing_ok=True)
    prepare_media(base / "media")
    if args.command == "up":
        start_servers(base)
    elif not healthy():
        sys.exit(f"No demo backend on port {API_PORT}; run `up` instead.")
    fixture_path = base / "fixture.json"
    if fixture_path.exists():
        register(base)
        print(f"Already seeded; fixture at {fixture_path}. Use --fresh to rebuild.")
        return
    token = register(base)
    seeder = Seeder(base, token)
    seeder.plugins()
    seeder.placeholder_provider()
    if args.local_chat:
        if not (ROOT / "agent-sidecar/dist/sidecar.cjs").exists():
            sys.exit("The agent runs in agent-sidecar; build it first: pnpm install && pnpm --dir agent-sidecar build")
        seeder.local_chat(args.local_chat)
    for locale in ("zh", "en"):
        seeder.fixture["locales"][locale] = seeder.seed_locale(locale)
        print(f"Seeded {locale} workspace", flush=True)
    write_private(fixture_path, json.dumps(seeder.fixture, ensure_ascii=False, indent=2))
    print(f"Demo ready: app http://127.0.0.1:{APP_PORT}, api http://127.0.0.1:{API_PORT}")
    print(f"Token: {base / 'token.json'}  Fixture: {fixture_path}")


if __name__ == "__main__":
    main()
