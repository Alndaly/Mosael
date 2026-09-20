"""智能体在 Blender 里建模的那条路:看、做、收进场景 —— 以及不留一条不经确认的后门。

worker 在真 Blender 里的行为由 test_blender_worker_live.py 钉;这里钉宿主这一侧:连接怎么选、
Blender 回传的路径能不能照单全收、代码的错误怎么回到模型手里、导入之后场景长什么样,
以及跑代码只有确认卡这一条路。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Scene3D, User
from app.domain.blender import agent as blender_agent, bridge
from app.domain.blender.bridge import BlenderDomainError
from tests.test_blender_bridge import glb
from tests.test_scenes import setup_scene


@pytest.fixture
def fake_blender(monkeypatch, tmp_path):
    """一个假 Blender:记下每次调了什么操作,按操作名给结果。"""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(blender_agent, "resolve", lambda db, user, instance_id="": SimpleNamespace(id="local"))
    calls: list[tuple[str, dict]] = []
    replies: dict = {}

    def execute(db, instance, operation, payload, workspace_id):
        calls.append((operation, payload))
        reply = replies[operation]
        return reply(payload) if callable(reply) else reply

    monkeypatch.setattr(bridge, "execute", execute)
    return SimpleNamespace(calls=calls, replies=replies)


def _user(db):
    return db.scalar(select(User))


def test_look_把渲出来的图读成_base64_临时目录用完即删(fake_blender) -> None:
    def render(payload):
        folder = Path(payload["folder"])
        for view in payload["views"]:
            (folder / f"{view}.jpg").write_bytes(b"\xff\xd8jpeg")
        return {"scene_name": "S", "images": [{"view": v, "path": str(folder / f"{v}.jpg")} for v in payload["views"]]}

    fake_blender.replies["look"] = render
    setup_scene()
    with SessionLocal() as db:
        out = blender_agent.look(db, _user(db), "ws", views=["overview", "top", "overview"])
    assert [one["view"] for one in out["images"]] == ["overview", "top"], "重复的视角只渲一次"
    assert out["images"][0]["data"] == "/9hqcGVn"
    assert not Path(fake_blender.calls[0][1]["folder"]).exists()


def test_look_不读我们目录之外的文件(fake_blender, tmp_path) -> None:
    """路径是 Blender 那边回传的 —— 一个被改过的 Add-on 可以让它指向 ~/.ssh/id_rsa。"""
    secret = tmp_path / "secret.txt"
    secret.write_text("key")
    fake_blender.replies["look"] = {"images": [{"view": "top", "path": str(secret)}]}
    setup_scene()
    with SessionLocal() as db, pytest.raises(BlenderDomainError):
        blender_agent.look(db, _user(db), "ws", views=["top"])


def test_look_不认识的视角先拒_不去打扰_Blender(fake_blender) -> None:
    setup_scene()
    with SessionLocal() as db, pytest.raises(BlenderDomainError, match="camera"):
        blender_agent.look(db, _user(db), "ws", views=["fisheye"])
    assert fake_blender.calls == []


def test_代码出错时_traceback_作为失败原因回到模型(fake_blender, monkeypatch) -> None:
    from app.domain.agent.confirmable.registry import tool_spec

    monkeypatch.setattr(settings, "local_desktop", True)
    fake_blender.replies["execute"] = {"error": "Traceback…\nKeyError: 'Nope'", "printed": "step 1"}
    _, ws, _ = setup_scene()
    with SessionLocal() as db:
        confirmation = SimpleNamespace(workspace_id=ws, payload={"code": "bpy.data.objects['Nope']"})
        with pytest.raises(ValueError, match="KeyError: 'Nope'"):
            tool_spec("blender_execute").execute(db, confirmation, _user(db).id)


def test_导入_把导出的_GLB_作为一个模型物体加进场景(fake_blender) -> None:
    def export(payload):
        Path(payload["output_path"]).write_bytes(glb())
        return {"scene_name": "凉亭", "warnings": []}

    fake_blender.replies["export"] = export
    _, ws, initial = setup_scene()
    with SessionLocal() as db:
        scene = db.get(Scene3D, initial["id"])
        out = blender_agent.import_to_scene(db, _user(db), scene, base_revision=scene.revision,
                                            objects=["Roof", "Pillar"], position=[2, 0, -1])
        db.refresh(scene)
        added = next(o for o in scene.content["objects"] if o["id"] == out["object_id"])
    assert fake_blender.calls[0][1]["objects"] == ["Roof", "Pillar"]
    assert added["kind"] == "model" and added["name"] == "凉亭" and added["position"] == [2, 0, -1]
    assert out["revision"] == initial["revision"] + 1


def test_导入前先比修订_过期了不让_Blender_白导一趟(fake_blender) -> None:
    _, _, initial = setup_scene()
    with SessionLocal() as db:
        scene = db.get(Scene3D, initial["id"])
        with pytest.raises(bridge.BlenderConflict):
            blender_agent.import_to_scene(db, _user(db), scene, base_revision=scene.revision - 1)
    assert fake_blender.calls == []


def test_跑代码只有确认卡一条路_插件的原始入口不暴露() -> None:
    """Blender MCP 自带的 execute_blender_code 不经确认;它和 blender_execute 并存就是后门。"""
    import mcp_server
    from app.domain.agent import rules
    from app.domain.plugins.manifest import parse

    assert "blender_execute" in mcp_server.CONFIRMATION_TOOLS
    assert rules.evaluate("blender_execute", {}, rules.default_rules()).denied
    loose_host = {**rules.default_rules(), "run_host_code": "always"}
    assert rules.evaluate("blender_execute", {}, loose_host).denied, "放开不隔离执行不连带放开 Blender"

    path = Path(__file__).resolve().parents[2] / "plugins/examples/blender/mosael.plugin.json"
    manifest = parse(json.loads(path.read_text()), str(path.parent))
    assert manifest.overrides["execute_blender_code"].internal
    assert "execute_blender_code" not in manifest.recommended


def test_权限领域不认识_Blender_是什么() -> None:
    """档位由每张确认卡自己声明。此前 rules.py 手写着档位键和三份理由文案,于是接一个第三方
    软件要在权限领域里改四处 —— 而它不该知道 Blender、Docker 或任何具体东西叫什么。"""
    from app.domain.agent import rules

    source = Path(rules.__file__).read_text(encoding="utf-8")
    assert "blender" not in source.lower(), "权限领域里不该出现具体功能的名字"
    assert rules.gates()["blender"] == "Blender 建模", "档位和它的名字来自确认卡注册表"


def test_internal_工具不进智能体工具表_也不进插件页(monkeypatch) -> None:
    from app.domain.plugins import tools as plugin_tools

    instance = SimpleNamespace(id="i", name="Blender", package_id="dev.mosael.blender", enabled=True)
    monkeypatch.setattr(plugin_tools, "all_tools", lambda db, inst: [
        {"name": "execute_blender_code", "internal": True, "description": "", "input_schema": {}, "read_only": False},
        {"name": "get_scene_info", "internal": False, "description": "", "input_schema": {}, "read_only": True},
    ])
    monkeypatch.setattr(plugin_tools.inst, "blocked_reason", lambda db, i: None)
    monkeypatch.setattr(plugin_tools.inst, "exposed_tools", lambda db, i: {"execute_blender_code", "get_scene_info"})

    class FakeDb:
        def scalars(self, stmt):
            return [instance]

        def get(self, model, key):
            return SimpleNamespace(id="dev.mosael.blender")

    assert [tool["name"] for tool in plugin_tools.exposed(FakeDb(), "u")] == ["get_scene_info"]
