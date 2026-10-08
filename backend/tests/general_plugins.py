"""三个「像真的」通用插件:形状照维护者开着的那几种造(工具数、说明长短、入参大小、长下拉),名字和内容都是编的,不拷真实清单。

维护者那里(2026-10-08,库的只读副本):一个 MCP 的 3D 软件连接 27 个工具约 3.1 万字符(大头是说明,入参都小)、一个出讲解视频的
4 个约 7.3K(一个大入参、一个长说明)、一个代码动画的 3 个约 3.2K。这里:

- `SCENE`:27 个工具,每个说明约 1K 字符、两三个小入参;一半只读,一个在本机跑代码;
- `EXPLAINER`:4 个,一个入参是嵌套的大表(约 3.5K)、一个配音下拉 200 项、一个说明 2.6K(超过说明上限,看截没截);
- `MOTION`:3 个,每个约 1K。

都是声明式工具(`tools.declare`),跑起来回显入参 —— 量的是定义,不是它们做什么。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: 回显入参的进程入口:{"tool", "echo"}。
ENTRY = """
import json, sys
req = json.loads(sys.stdin.read())
json.dump({"ok": True, "output": {"tool": req["tool"], "echo": req["input"]}}, sys.stdout)
"""

_SENTENCES = (
    "读取当前场景里与这一项有关的数据,按对象名列出类型、位置、尺寸和挂着的材质。",
    "Returns the matching objects with their transforms, bounding boxes and the materials assigned to each slot.",
    "对象名区分大小写;找不到时回一个空列表而不是报错,方便先查再改。",
    "Coordinates are in scene units with Z up; rotations are Euler angles in degrees, XYZ order.",
    "大场景里只回前两百个,另给总数;要看全部就按集合名分批取。",
    "Use the inspect tools before editing so the change lands on the object the user means.",
    "改动会进撤销栈,一次调用一步;用户在软件里按撤销就能退回去。",
    "Large meshes are summarised (vertex and face counts) rather than listed vertex by vertex.",
)


def _description(index: int, length: int) -> str:
    text, step = "", index
    while len(text) < length:
        text += _SENTENCES[step % len(_SENTENCES)] + " "
        step += 1
    return text.strip()


def _scene_effects(index: int) -> dict[str, Any]:
    """一个在本机跑代码;别的不花钱不出门,其中一半只读。"""
    if index == 1:
        return {"effects": "local-code"}
    return {"effects": "none", **({"read_only": True} if index % 2 == 0 else {})}


def _small_schema(index: int) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "object_name": {"type": "string", "description": "对象名(区分大小写)。"},
        "collection": {"type": "string", "description": "只看这个集合里的。"},
    }
    if index % 3 == 0:
        properties["limit"] = {"type": "integer", "minimum": 1, "maximum": 200, "default": 50}
    return {"type": "object", "properties": properties}


SCENE: dict[str, Any] = {
    "id": "dev.fake.scene3d",
    "name": "3D 软件(测试)",
    "version": "1.0.0",
    "runtime": {"kind": "process", "entry": "main.py"},
    "tools": {
        "expose": "all",
        "declare": [
            {
                "name": f"scene_step_{index:02d}",
                "label": {"zh": f"场景操作 {index:02d}", "en": f"Scene step {index:02d}"},
                "description": _description(index, 1_000),
                "input_schema": _small_schema(index),
                **_scene_effects(index),
            }
            for index in range(27)
        ],
    },
}

#: 讲解视频那个插件的大入参:每一步一个对象,几样可选的画面。
_STEP = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "这一步的标题,最多 40 字。"},
        "narration": {"type": "string", "description": "旁白,按朗读时长决定这一步多长;同时作为字幕。"},
        "points": {"type": "array", "items": {"type": "string"}, "description": "逐条出现的要点,最多 5 条。"},
        "formula": {"type": "string", "description": "一行 LaTeX 公式;没装 LaTeX 时写成纯文字。"},
        "plot": {
            "type": "object",
            "description": "函数图像:表达式和取值范围。",
            "properties": {
                "expression": {"type": "string", "description": "用 x 写的表达式,如 sin(x) * x。"},
                "x_range": {"type": "array", "items": {"type": "number"}, "description": "[起, 止, 步长]"},
                "y_range": {"type": "array", "items": {"type": "number"}, "description": "[起, 止, 步长]"},
                "color": {"type": "string", "enum": ["blue", "green", "red", "yellow", "purple", "white"]},
            },
        },
        "code": {
            "type": "object",
            "description": "逐处高亮的代码。",
            "properties": {
                "source": {"type": "string", "description": "代码原文。"},
                "language": {"type": "string", "enum": ["python", "javascript", "typescript", "rust", "go", "c", "cpp"]},
                "highlights": {"type": "array", "items": {"type": "array", "items": {"type": "integer"}},
                               "description": "每一拍高亮哪几行,如 [[1, 2], [4]]。"},
            },
        },
    },
    "required": ["title", "narration"],
}

EXPLAINER: dict[str, Any] = {
    "id": "dev.fake.explainer",
    "name": "讲解视频(测试)",
    "version": "1.0.0",
    "runtime": {"kind": "process", "entry": "main.py"},
    "tools": {
        "expose": "all",
        "declare": [
            {
                "name": "explainer_video",
                "label": {"zh": "讲解视频", "en": "Explainer video"},
                "description": _description(3, 1_100),
                "effects": "none",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "标题页的大标题,最多 80 字。"},
                        "subtitle": {"type": "string", "description": "标题页的副标题,一句话。"},
                        "steps": {"type": "array", "items": _STEP, "description": "一步一步讲,最多 12 步。"},
                        "takeaways": {"type": "array", "items": {"type": "string"}, "description": "最后的要点回顾。"},
                        "quality": {"type": "string", "enum": ["draft", "720p", "1080p", "production", "4k"],
                                    "default": "720p", "description": "画质;智能体调用时别选 production / 4k。"},
                        "srt": {"type": "boolean", "default": False, "description": "同时出一份 .srt 字幕。"},
                    },
                    "required": ["title", "steps"],
                },
            },
            {
                "name": "explainer_voice",
                "label": {"zh": "配音", "en": "Voice-over"},
                "description": _description(5, 400),
                "effects": "paid",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "要读的文字。"},
                        "voice": {"type": "string", "enum": [f"voice-{index:03d}" for index in range(200)],
                                  "description": "音色。"},
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "explainer_scene_code",
                "label": {"zh": "自定义动画", "en": "Custom animation"},
                "description": _description(6, 2_600),
                "effects": "local-code",
                "input_schema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]},
            },
            {
                "name": "explainer_setup",
                "label": {"zh": "准备环境", "en": "Prepare"},
                "description": _description(7, 300),
                "effects": "none",
                "input_schema": {"type": "object", "properties": {}},
            },
        ],
    },
}

MOTION: dict[str, Any] = {
    "id": "dev.fake.motion",
    "name": "代码动画(测试)",
    "version": "1.0.0",
    "runtime": {"kind": "process", "entry": "main.py"},
    "tools": {
        "expose": "all",
        "declare": [
            {
                "name": f"motion_{kind}",
                "label": {"zh": f"代码动画 · {kind}", "en": f"Motion · {kind}"},
                "description": _description(index, 700),
                "effects": "external" if kind == "publish" else "none",
                "input_schema": {"type": "object", "properties": {
                    "content": {"type": "string", "description": "要讲的内容,结构化的 JSON 字符串。"},
                    "width": {"type": "integer", "default": 1280}, "height": {"type": "integer", "default": 720},
                    "fps": {"type": "integer", "enum": [24, 25, 30, 60], "default": 30},
                }},
            }
            for index, kind in enumerate(("explainer", "animation", "publish"))
        ],
    },
}

ALL = (SCENE, EXPLAINER, MOTION)


def install(client) -> dict[str, str]:
    """把三个包写进插件目录(不动随应用带的 ComfyUI)、扫描、启用它们的默认连接。回 {包 id: 连接 id}。"""
    from app.core.config import settings
    from app.core.db import SessionLocal
    from app.db.models import User
    from app.domain.plugins import install as installer

    plugins_dir = Path(settings.plugins_dir)

    for manifest in ALL:
        directory = plugins_dir / manifest["id"].rsplit(".", 1)[-1]
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "mosael.plugin.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        (directory / "main.py").write_text(ENTRY, encoding="utf-8")
    with SessionLocal() as db:
        me = db.query(User).order_by(User.created_at).first()
        installer.sync(db, plugins_dir, owner_user_id=me.id if me else "")
    connections: dict[str, str] = {}
    for package in client.get("/api/plugins").json():
        if package["id"] in {manifest["id"] for manifest in ALL}:
            instance = package["instances"][0]["id"]
            assert client.patch(f"/api/plugins/instances/{instance}", json={"enabled": True}).status_code == 200
            connections[package["id"]] = instance
    assert len(connections) == len(ALL), connections
    return connections


__all__ = ["ALL", "ENTRY", "EXPLAINER", "MOTION", "SCENE", "install"]
