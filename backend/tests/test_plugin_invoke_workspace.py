"""插件面板的 HTTP 入口必须把素材工作区传到真实插件运行时。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import Asset, PluginInstance, PluginInvocation, PluginPackage, User, Workspace, WorkspaceMember
from app.domain.assets import register_file_asset
from tests.util import fresh_client


@pytest.fixture
def panel(tmp_path):
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "当前工作区"}).json()["id"]
    # 使用百度网盘实际声明的输入契约，进程只搬本地测试文件，不连接网盘。
    original = json.loads((Path(__file__).resolve().parents[2] / "plugins/examples/baidu-pan/mosael.plugin.json").read_text())
    manifest = {
        "id": "test.pan", "name": "测试网盘", "version": "1.0.0",
        "runtime": {"kind": "process", "entry": "main.py"},
        "tools": {"expose": "all", "declare": original["tools"]["declare"]},
        "_path": str(tmp_path),
    }
    (tmp_path / "main.py").write_text('''
import json, os, sys
from pathlib import Path
request = json.loads(sys.stdin.read())
if request["tool"] == "pan_import":
    Path(os.environ["MOSAEL_PLUGIN_OUTPUT_DIR"], "download.txt").write_text("网盘内容")
    output = {"artifact": {"path": "download.txt"}, "fs_id": request["input"]["fs_id"]}
elif request["tool"] == "pan_upload":
    output = {"content": Path(request["input"]["asset_id"]).read_text(), "path": request["input"]["path"]}
else:
    output = {"entries": []}
print(json.dumps({"ok": True, "output": output}))
''')
    source = tmp_path / "source.txt"
    source.write_text("素材内容")
    with SessionLocal() as db:
        user_id = db.scalar(select(User.id))
        db.add(PluginPackage(id="test.pan", name="测试网盘", version="1.0.0", manifest=manifest))
        db.flush()
        instance = PluginInstance(package_id="test.pan", name="测试网盘", enabled=True, owner_user_id=user_id)
        db.add(instance)
        asset = register_file_asset(db, workspace_id=workspace, project_id=None, source_path=source,
                                    name="source.txt", source="imported")
        db.commit()
        return client, workspace, instance.id, asset.id, user_id


def invoke(panel, tool, payload, workspace):
    client, _, instance_id, _, _ = panel
    return client.post(f"/api/plugins/instances/{instance_id}/tools/{tool}/invoke",
                       json={"input": payload, "workspace_id": workspace})


def test_import_collects_file_in_selected_workspace(panel):
    result = invoke(panel, "pan_import", {"fs_id": "230120330866997"}, panel[1])
    assert result.status_code == 200, result.text
    invocation = result.json()
    assert invocation["status"] == "succeeded", invocation
    with SessionLocal() as db:
        asset = db.get(Asset, invocation["output"]["asset_id"])
        assert asset.workspace_id == panel[1]
        assert asset.source == "plugin"


def test_upload_materializes_asset_from_selected_workspace(panel):
    result = invoke(panel, "pan_upload", {"asset_id": panel[3], "path": "/成片.txt"}, panel[1])
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "succeeded", result.json()
    assert result.json()["output"]["content"] == "素材内容"
    assert result.json()["output"]["path"] == "/成片.txt"


@pytest.mark.parametrize("role,status", [(None, 404), ("viewer", 403)])
def test_workspace_authorization_precedes_plugin_execution(panel, role, status):
    with SessionLocal() as db:
        other = Workspace(name="其它工作区")
        db.add(other)
        db.flush()
        if role:
            db.add(WorkspaceMember(workspace_id=other.id, user_id=panel[4], role=role))
        db.commit()
        other_id = other.id
    result = invoke(panel, "pan_import", {"fs_id": "1"}, other_id)
    assert result.status_code == status, result.text
    with SessionLocal() as db:
        assert db.scalar(select(PluginInvocation.id)) is None


def test_selected_workspace_does_not_allow_uploading_another_workspaces_asset(panel):
    client, _, _, asset_id, _ = panel
    other = client.post("/api/workspaces", json={"name": "另一个自己的工作区"}).json()["id"]
    result = invoke(panel, "pan_upload", {"asset_id": asset_id, "path": "/成片.txt"}, other)
    assert result.status_code == 200
    assert result.json()["status"] == "failed"
    assert "工作区" in result.json()["error"]


def test_context_free_tools_remain_compatible(panel):
    client, _, instance_id, _, _ = panel
    result = client.post(f"/api/plugins/instances/{instance_id}/tools/pan_list/invoke", json={"input": {}})
    assert result.status_code == 200
    assert result.json()["status"] == "succeeded", result.json()
