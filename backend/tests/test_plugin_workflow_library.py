"""工作流库(ADR 0035):认领 `workflow_library` 的连接,宿主替它列工作流、取原文、改那台服务器上的工作流文件。

钉住的是**框架**,不是 ComfyUI(那个在 test_comfyui_plugin_workflow_library.py):

- 目录类能力:认领它的工具不进工具表,能力词表里叫得出名字;
- 列出来的是插件报的那一份,宿主规整字段(路径不对的、坏条目丢掉,图摘要的连线只留指着节点的);
- 宿主补上它在 Mosael 里的样子:是不是这个连接下的生成模型(用它生成要它)、这个工作区里最近一次用它生成的产出;
- 写操作(复制、改名、挪进 / 挪出回收目录):路径先在宿主这里过一遍(不合格的不交给插件);撞名回 409 带建议名、
  不覆盖;改成了让这个连接的目录马上重拉一遍。
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.core.db import SessionLocal
from app.db.models import PluginPackage
from app.domain.plugins import runtime
from tests.util import fresh_client

PACKAGE_ID = "test.workflows"

PLUGIN = r'''
import json, os, sys
from pathlib import Path

request = json.loads(sys.stdin.read())
payload = request["input"]
data = Path(os.environ["MOSAEL_PLUGIN_DATA_DIR"])
data.mkdir(parents=True, exist_ok=True)


def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


op = payload.get("op")
with (data / "ops.jsonl").open("a", encoding="utf-8") as log:
    log.write(json.dumps(payload, ensure_ascii=False) + "\n")
if op == "models":
    emit({"ok": True, "output": {"models": [{"id": "portrait.json", "label": "portrait", "kind": "image"}]}})
elif op == "workflows":
    emit({"ok": True, "output": {
        "workflows": [
            {"path": "portrait.json", "size": 19334, "modified": 1776098682.9, "kind": "image", "node_count": 3,
             "graph": {"nodes": [{"x": 0, "y": 0, "w": 300, "h": 120, "role": "model", "title": "Load Checkpoint"},
                                 {"x": 400, "y": 0, "w": 200, "h": 80, "role": "sampler", "muted": True},
                                 {"x": "bad"},
                                 {"x": 700, "y": 40, "w": 0, "h": 0, "role": "weird"}],
                       "links": [[0, 1], [1, 2], [0, 9], ["a", 1]],
                       "groups": [{"x": -20, "y": -40, "w": 680, "h": 200, "title": "生成", "color": "#3f789e"},
                                  {"x": 1, "y": 1, "w": 1, "h": 1, "color": "red;background:url(x)"}]},
             "inputs": [{"node": "10", "title": "参考图", "media": "image", "role": "reference_image"}],
             "parameters": [{"key": "3.steps", "title": "步数", "type": "integer"}],
             "outputs": [{"node": "9", "title": "保存图像", "media": "image"}],
             "models": [{"folder": "checkpoints", "name": "sdxl.safetensors", "present": True},
                        {"folder": "vae", "name": "ae.safetensors", "present": False}, {"folder": ""}],
             "missing_nodes": [{"type": "CR Prompt Text", "count": 2,
                                "packs": [{"id": "ComfyUI_Comfyroll_CustomNodes", "title": "Comfyroll", "installed": False}]}],
             "missing_models": [{"folder": "vae", "name": "ae.safetensors",
                                 "url": "https://huggingface.co/x/y/resolve/main/ae.safetensors"}]},
            {"path": "sub/sketch.json", "problem": "缺节点:CR Prompt Text"},
            {"path": "../outside.json"},
            {"path": "sub/.hidden.json"},
            "not a dict",
        ],
        "others": [{"path": "pack.zip", "reason": "这是一个压缩包"}],
        "trash": [{"path": ".mosael-trash/workflows/20261005-101500/old/one.json", "deleted_at": 1791000000.0},
                  {"path": ".mosael-trash/elsewhere/x.json"}],
        "manager": {"version": "V4.2.1"},
    }})
elif op == "workflow":
    emit({"ok": True, "output": {"content": {"nodes": [], "links": [], "path_seen": payload["path"]}}})
elif op in ("copy_workflow", "rename_workflow", "restore_workflow"):
    if payload["new_path"] == "taken.json":
        emit({"ok": True, "output": {"conflict": True, "suggestion": "taken (1).json"}})
    else:
        emit({"ok": True, "output": {"path": payload["new_path"]}})
elif op == "trash_workflow":
    emit({"ok": True, "output": {"path": ".mosael-trash/workflows/20261005-101500/" + payload["path"]}})
else:
    emit({"ok": False, "error": f"unknown op {op}"})
'''


def _manifest(path: Path) -> dict[str, Any]:
    return {
        "id": PACKAGE_ID,
        "name": "测试工作流库",
        "version": "1.0.0",
        "manifest_version": 1,
        "runtime": {"kind": "process", "entry": "main.py"},
        "provides": ["generation", "workflow_library"],
        "permissions": ["network:test"],
        "instance": {
            "multiple": True,
            "name_template": "测试工作流库 · {SERVER}",
            "config": [{"key": "SERVER", "label": "服务器", "type": "string", "required": True}],
        },
        "tools": {
            "declare": [
                {"name": "host", "provides": ["generation", "workflow_library"], "timeout_seconds": 60,
                 "input_schema": {"type": "object"}},
                {"name": "ping", "description": "普通工具", "input_schema": {"type": "object"}},
            ]
        },
        "_path": str(path),
    }


@pytest.fixture
def library(tmp_path: Path):
    shutil.rmtree(runtime.data_dir_for(PACKAGE_ID), ignore_errors=True)
    client = fresh_client()
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    (plugin / "main.py").write_text(PLUGIN, encoding="utf-8")
    with SessionLocal() as db:
        db.add(PluginPackage(id=PACKAGE_ID, name="测试工作流库", version="1.0.0", manifest=_manifest(plugin)))
        db.commit()
    created = client.post(f"/api/plugins/{PACKAGE_ID}/instances", json={"config": {"SERVER": "s1"}})
    assert created.status_code == 200, created.text
    instance_id = created.json()["id"]
    assert client.patch(f"/api/plugins/instances/{instance_id}/permissions",
                        json={"grants": {"network:test": True}}).status_code == 200
    assert client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True}).status_code == 200
    yield client, instance_id
    shutil.rmtree(runtime.data_dir_for(PACKAGE_ID), ignore_errors=True)


def _ops() -> list[dict[str, Any]]:
    log = runtime.data_dir_for(PACKAGE_ID) / "ops.jsonl"
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


def test_工作流库是目录类能力_认领它的工具不进工具表(library) -> None:
    client, instance_id = library
    from app.db.models import PluginInstance
    from app.domain.plugins import tools

    with SessionLocal() as db:
        by_name = {tool["name"]: tool for tool in tools.all_tools(db, db.get(PluginInstance, instance_id))}
        assert by_name["host"]["internal"] is True
        assert by_name["ping"]["internal"] is False
    terms = {one["name"]: one for one in client.get("/api/plugins/capabilities").json()}
    assert terms["workflow_library"]["label"] and terms["workflow_library"]["label"] != "workflow_library"


def test_列出插件报的工作流_宿主规整字段_补上它在Mosael里是哪个生成模型(library) -> None:
    client, instance_id = library
    response = client.get(f"/api/plugins/instances/{instance_id}/workflow-library")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [one["path"] for one in body["workflows"]] == ["portrait.json", "sub/sketch.json"], \
        "跳出 workflows/ 的、隐藏的、坏的条目丢掉"
    portrait, sketch = body["workflows"]
    assert portrait["label"] == "portrait" and portrait["folder"] == ""
    assert sketch["label"] == "sketch" and sketch["folder"] == "sub" and sketch["problem"] == "缺节点:CR Prompt Text"
    graph = portrait["graph"]
    assert [node["role"] for node in graph["nodes"]] == ["model", "sampler", "other"], "坏节点丢掉,认不出的种类算 other"
    assert graph["nodes"][1]["muted"] is True
    assert graph["nodes"][2]["w"] >= 20 and graph["nodes"][2]["h"] >= 20, "没有大小的节点也画得出来"
    assert graph["links"] == [[0, 1], [1, 2]], "连线只留指着节点的"
    assert [group["color"] for group in graph["groups"]] == ["#3f789e", ""], "颜色只认 #RGB,不让别的东西进样式"
    assert portrait["models"] == [{"folder": "checkpoints", "name": "sdxl.safetensors", "present": True},
                                  {"folder": "vae", "name": "ae.safetensors", "present": False}]
    assert portrait["missing_nodes"] == [{"type": "CR Prompt Text", "count": 2, "packs": [
        {"id": "ComfyUI_Comfyroll_CustomNodes", "title": "Comfyroll", "installed": False}]}]
    assert portrait["missing_models"][0]["url"].startswith("https://huggingface.co/")
    assert portrait["generation"]["model"] == "portrait.json" and portrait["generation"]["kind"] == "image"
    assert sketch["generation"] is None, "不是这个连接下的生成模型(转不过来)就不能「用它生成」"
    assert body["others"] == [{"path": "pack.zip", "reason": "这是一个压缩包"}]
    assert body["trash"] == [{"path": ".mosael-trash/workflows/20261005-101500/old/one.json", "original": "old/one.json",
                              "label": "one", "deleted_at": 1791000000.0}], "不是回收目录形状的不认"
    assert body["manager"] == {"version": "V4.2.1"}


def test_最近一次的产出_只看这个工作区里用它生成的(library) -> None:
    client, instance_id = library
    workspace = client.post("/api/workspaces", json={"name": "工作流"}).json()["id"]
    other = client.post("/api/workspaces", json={"name": "别的"}).json()["id"]
    body = client.get(f"/api/plugins/instances/{instance_id}/workflow-library").json()
    profile_id = body["workflows"][0]["generation"]["provider_profile_id"]
    from app.db.models import Asset, GenerationJob

    with SessionLocal() as db:
        for ws, name in ((workspace, "这里的.png"), (other, "别处的.png")):
            asset = Asset(workspace_id=ws, name=name, original_filename=name, kind="image")
            db.add(asset)
            db.flush()
            db.add(GenerationJob(workspace_id=ws, provider="plugin:test.workflows", provider_profile_id=profile_id,
                                 model="portrait.json", kind="image", request={}, result_asset_id=asset.id,
                                 created_at=datetime(2026, 10, 5, tzinfo=UTC).replace(tzinfo=None)))
        db.commit()
        here = db.query(Asset).filter_by(name="这里的.png").one().id
    scoped = client.get(f"/api/plugins/instances/{instance_id}/workflow-library", params={"workspace_id": workspace}).json()
    assert scoped["workflows"][0]["last_output"]["asset_id"] == here
    assert body["workflows"][0]["last_output"] is None, "没说是哪个工作区就不去翻生成记录"


def test_取一张的原文(library) -> None:
    client, instance_id = library
    response = client.get(f"/api/plugins/instances/{instance_id}/workflow-library/content", params={"path": "sub/sketch.json"})
    assert response.status_code == 200, response.text
    assert response.json() == {"path": "sub/sketch.json", "content": {"nodes": [], "links": [], "path_seen": "sub/sketch.json"}}


@pytest.mark.parametrize("bad", ["../x.json", "/abs.json", "a\\b.json", "noext", "sub/.hidden.json", "a:b.json", "sub/ x.json"])
def test_路径不对的宿主当场拒绝_不交给插件(library, bad: str) -> None:
    client, instance_id = library
    response = client.post(f"/api/plugins/instances/{instance_id}/workflow-library/rename", json={"path": "portrait.json",
                                                                                                    "new_path": bad})
    assert response.status_code == 422, response.text
    assert not [one for one in _ops() if one.get("op") == "rename_workflow"]


def test_复制_改名_撞名回409带建议名_不覆盖(library) -> None:
    client, instance_id = library
    base = f"/api/plugins/instances/{instance_id}/workflow-library"
    clash = client.post(f"{base}/copy", json={"path": "portrait.json", "new_path": "taken.json"})
    assert clash.status_code == 409, clash.text
    assert clash.json()["detail"]["suggestion"] == "taken (1).json"
    assert "taken.json" in clash.json()["detail"]["message"]
    done = client.post(f"{base}/copy", json={"path": "portrait.json", "new_path": "portrait (1).json"})
    assert done.status_code == 200 and done.json() == {"path": "portrait (1).json"}
    moved = client.post(f"{base}/rename", json={"path": "portrait.json", "new_path": "sub/portrait.json"})
    assert moved.json() == {"path": "sub/portrait.json"}
    same = client.post(f"{base}/rename", json={"path": "portrait.json", "new_path": "portrait.json"})
    assert same.json() == {"path": "portrait.json"}
    assert [one["op"] for one in _ops() if one["op"].endswith("_workflow")] == ["copy_workflow", "copy_workflow",
                                                                                 "rename_workflow"], "改成原名不去插件"


def test_删除是挪进回收目录_能恢复_改完马上重拉目录(library) -> None:
    client, instance_id = library
    base = f"/api/plugins/instances/{instance_id}/workflow-library"
    before = len([one for one in _ops() if one["op"] == "models"])
    trashed = client.post(f"{base}/trash", json={"path": "sub/sketch.json"})
    assert trashed.status_code == 200, trashed.text
    assert trashed.json() == {"path": ".mosael-trash/workflows/20261005-101500/sub/sketch.json"}
    assert len([one for one in _ops() if one["op"] == "models"]) > before, "删了之后生成目录马上重拉,不等指纹"
    back = client.post(f"{base}/restore", json={"path": trashed.json()["path"]})
    assert back.json() == {"path": "sub/sketch.json"}, "不给新名字就回原处"
    clash = client.post(f"{base}/restore", json={"path": trashed.json()["path"], "new_path": "taken.json"})
    assert clash.status_code == 409
    bad = client.post(f"{base}/restore", json={"path": ".mosael-trash/elsewhere/x.json"})
    assert bad.status_code == 422, "不是回收目录里的东西不让「恢复」"
