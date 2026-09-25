"""插件工具的三样新本事(框架层,不认识任何一个具体插件):

- **流式工具**(清单里 `stream: true`):边跑边说进度,进度经任务总线的上报口(`jobs.report_progress`)
  交给听的一方 —— 在工作流节点里就是那个节点的 `workflow.node.progress` 事件;任务取消时**先建取消文件**
  让插件去停远端的活,而不是直接杀掉进程(杀掉的话 ComfyUI 会把那张图跑完,结果没人要);
- **一次交出几份文件**(`artifacts: [...]`):全部收进素材库,输出里换成 `assets` / `asset_ids`,
  第一份同时记成 `asset_id`(下游 `{{n1.asset_id}}` 不必知道交的是一份还是几份);
- **一次收几份素材**(`{"type": "array", "items": {"format": "asset"}}`):插件收到的是一串本地路径。

以及两处配套:`type: "json"` 的配置项保存前必须能解析(说出第几行第几列);随应用发的插件升级后多了
工具,已经接好的连接自动补上开关。
"""

from __future__ import annotations

import re
import textwrap
import time
from pathlib import Path

import pytest

from app.core.db import SessionLocal
from app.db.models import Asset, Job, PluginInstance, PluginPackage, TaskEvent
from app.domain.jobs import listening_for_progress, reset_parent_job, set_parent_job, stop_listening_for_progress
from app.domain.plugins.tools import MAX_ARTIFACTS, all_tools, invoke
from tests.util import fresh_client

ENTRY = """
import json, os, pathlib, shutil, sys, time

request = json.loads(sys.stdin.read())
payload = request["input"]
out = pathlib.Path(os.environ["MOSAEL_PLUGIN_OUTPUT_DIR"])

def say(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\\n")
    sys.stdout.flush()

if request["tool"] == "gather":
    say({"event": "progress", "progress": 0.5, "message": "收拾 1/2"})
    files = [payload["one"], *payload.get("many", [])]
    artifacts = []
    for index, path in enumerate(files, start=1):
        shutil.copy(path, out / f"copy-{index}.txt")
        artifacts.append({"path": f"copy-{index}.txt", "filename": f"第{index}份.txt", "node": str(index),
                          "nested": {"dropped": True}})
    say({"event": "progress", "progress": 1.0, "message": "收拾 2/2"})
    say({"ok": True, "output": {"artifacts": artifacts, "received": files, "summary": "两份"}})
elif request["tool"] == "flood":
    for index in range(int(payload["n"])):
        (out / f"{index}.txt").write_text("x")
    say({"ok": True, "output": {"artifacts": [{"path": f"{i}.txt"} for i in range(int(payload["n"]))]}})
elif request["tool"] == "slow":
    cancel = os.environ.get("MOSAEL_PLUGIN_CANCEL_FILE", "")
    for _ in range(200):
        if cancel and os.path.exists(cancel):
            pathlib.Path(os.environ["MOSAEL_PLUGIN_DATA_DIR"], "stopped-remote").write_text("yes")
            say({"ok": False, "error": "cancelled"})
            sys.exit(0)
        time.sleep(0.05)
    say({"ok": True, "output": {"finished": True}})
"""

MANIFEST = {
    "id": "dev.test.gatherer",
    "name": "收集器",
    "version": "1.0.0",
    "manifest_version": 1,
    "runtime": {"kind": "process", "entry": "main.py"},
    "tools": {
        "expose": "all",
        "declare": [
            {"name": "gather", "stream": True, "input_schema": {"type": "object", "properties": {
                "one": {"type": "string", "format": "asset"},
                "many": {"type": "array", "items": {"type": "string", "format": "asset"}},
            }, "required": ["one"]}},
            {"name": "flood", "input_schema": {"type": "object", "properties": {"n": {"type": "integer"}}}},
            {"name": "slow", "stream": True, "input_schema": {"type": "object"}},
        ],
    },
}


def _install(tmp_path: Path) -> tuple[str, str, list[str]]:
    """装一个插件、造三份素材。返回 (workspace, instance, 素材 id)。"""
    plugin_dir = tmp_path / "p"
    plugin_dir.mkdir()
    (plugin_dir / "main.py").write_text(textwrap.dedent(ENTRY), encoding="utf-8")
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    assets = []
    with SessionLocal() as db:
        package = PluginPackage(id=MANIFEST["id"], name="收集器", version="1.0.0",
                                manifest={**MANIFEST, "_path": str(plugin_dir)})
        db.add(package)
        db.flush()
        instance = PluginInstance(package_id=package.id, name="收集器", enabled=True, owner_user_id="")
        db.add(instance)
        db.commit()
        from app.domain.assets import register_file_asset

        for index in range(3):
            media = tmp_path / f"素材{index}.txt"
            media.write_text(f"内容 {index}", encoding="utf-8")
            assets.append(register_file_asset(db, workspace_id=ws, project_id=None, source_path=media,
                                              name=media.name, source="imported").id)
        db.commit()
        return ws, instance.id, assets


def test_流式工具_进度交给听的一方_几份文件全进素材库(tmp_path) -> None:
    ws, instance_id, assets = _install(tmp_path)
    heard: list[tuple[float, str]] = []
    token = listening_for_progress(lambda fraction, message: heard.append((fraction, message)))
    try:
        with SessionLocal() as db:
            assert next(tool for tool in all_tools(db, db.get(PluginInstance, instance_id)) if tool["name"] == "gather")["stream"]
            invocation = invoke(db, instance_id, "gather", {"one": assets[0], "many": assets[1:]}, workspace_id=ws)
            assert invocation.status == "succeeded", invocation.error
            output = invocation.output
            names = {asset_id: db.get(Asset, asset_id).name for asset_id in output["asset_ids"]}
    finally:
        stop_listening_for_progress(token)
    assert ("收拾 1/2" in [message for _, message in heard]) and heard[-1] == (1.0, "收拾 2/2")
    assert len(output["received"]) == 3, "数组里的每一份素材都换成了本地路径"
    assert all(Path(path).is_absolute() for path in output["received"])
    assert "artifacts" not in output
    assert list(names.values()) == ["第1份.txt", "第2份.txt", "第3份.txt"]
    assert output["asset_id"] == output["asset_ids"][0], "第一份同时是 asset_id:下游不必知道交的是一份还是几份"
    assert output["assets"][1] == {"node": "2", "asset_id": output["asset_ids"][1], "asset_name": "第2份.txt"}, (
        "附带的标量说明原样跟着;嵌套结构不带"
    )


def test_交出的文件太多就整次失败(tmp_path) -> None:
    ws, instance_id, _ = _install(tmp_path)
    with SessionLocal() as db:
        invocation = invoke(db, instance_id, "flood", {"n": MAX_ARTIFACTS + 1}, workspace_id=ws)
    assert invocation.status == "failed" and str(MAX_ARTIFACTS) in (invocation.error or "")


def test_取消时先让插件去停远端的活(tmp_path) -> None:
    """在任务里跑的流式工具,取消任务 = 建取消文件,插件看到它去停远端(ComfyUI 的 interrupt),再退出。"""
    ws, instance_id, _ = _install(tmp_path)
    token = set_parent_job("a-job-that-is-already-gone")  # 登记时发现任务不在了 —— 当场拉下开关
    try:
        with SessionLocal() as db:
            started = time.monotonic()
            invocation = invoke(db, instance_id, "slow", {}, workspace_id=ws)
    finally:
        reset_parent_job(token)
    assert invocation.status == "failed"
    assert time.monotonic() - started < 8, "插件看到取消文件就退了,不是等到超时"
    from app.domain.plugins.runtime import data_dir_for

    assert (data_dir_for(MANIFEST["id"]) / "stopped-remote").read_text() == "yes", "插件有机会去停远端的活"


def test_工作流节点里的进度成了节点事件(monkeypatch) -> None:
    from app.domain.jobs import report_progress
    from app.domain.plugins.nodes import node_meta
    from app.domain.workflows import create_workflow
    from app.domain.workflows.engine import start_workflow_job
    from app.domain.workflows.executors import get_executor
    from tests.util import user_id

    kind = "plugin.demo.slowpoke"
    meta = node_meta({"name": "slowpoke", "label": "慢", "input_schema": {"properties": {}}})
    monkeypatch.setattr("app.domain.plugins.nodes.plugin_node_types", lambda db, user_id=None: {kind: meta})

    def slowpoke(db, workflow, config):
        report_progress(0.25, "采样 5/20")
        return {"output": "ok"}

    monkeypatch.setattr("app.domain.workflows.engine.get_executor",
                        lambda name: slowpoke if name == kind else get_executor(name))
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    graph = {"nodes": [{"id": "start", "type": "start", "config": {}}, {"id": "n1", "type": kind, "config": {}}],
             "edges": [{"id": "e1", "source": "start", "target": "n1"}]}
    with SessionLocal() as db:
        workflow = create_workflow(db, workspace_id=ws, name="进度", graph=graph, created_by=user_id())
        job_id = start_workflow_job(db, workflow, created_by=None).id
    for _ in range(100):
        with SessionLocal() as db:
            if db.get(Job, job_id).status in ("succeeded", "failed"):
                break
        time.sleep(0.05)
    with SessionLocal() as db:
        events = [event.payload for event in db.query(TaskEvent).filter(
            TaskEvent.job_id == job_id, TaskEvent.type == "workflow.node.progress")]
    assert events == [{"node_id": "n1", "name": "慢", "name_key": "慢", "progress": 0.25, "message": "采样 5/20"}]


# --- 代码类的配置项 -----------------------------------------------------------------


JSON_MANIFEST = {
    "id": "dev.test.jsonconfig",
    "name": "带模板的插件",
    "version": "1.0.0",
    "manifest_version": 1,
    "runtime": {"kind": "process", "entry": "main.py"},
    "instance": {"multiple": True, "config": [
        {"key": "template", "label": "模板", "type": "json", "required": False},
        {"key": "script", "label": "脚本", "type": "code", "language": "Python", "required": False},
    ]},
    "tools": {"declare": []},
}


def test_json配置项_保存前必须能解析_说出第几行第几列(tmp_path) -> None:
    plugin_dir = tmp_path / "j"
    plugin_dir.mkdir()
    (plugin_dir / "main.py").write_text("", encoding="utf-8")
    client = fresh_client()
    with SessionLocal() as db:
        db.add(PluginPackage(id=JSON_MANIFEST["id"], name="带模板的插件", version="1.0.0",
                             manifest={**JSON_MANIFEST, "_path": str(plugin_dir)}))
        db.commit()
    package = next(one for one in client.get("/api/plugins").json() if one["id"] == JSON_MANIFEST["id"])
    assert [(field["type"], field["language"]) for field in package["config_fields"]] == [("json", "json"), ("code", "python")]
    broken = client.post(f"/api/plugins/{JSON_MANIFEST['id']}/instances", json={"config": {"template": '{\n  "a": 1,\n}'}})
    assert broken.status_code == 422 and re.search(r"第 \d+ 行第 \d+ 列", broken.json()["detail"]), broken.text
    created = client.post(f"/api/plugins/{JSON_MANIFEST['id']}/instances", json={"config": {"template": ""}})
    assert created.status_code == 200, "空的不查:没填不等于填错"
    instance_id = created.json()["id"]
    bad = client.patch(f"/api/plugins/instances/{instance_id}", json={"config": {"template": "[1, 2"}})
    assert bad.status_code == 422
    raw = '{\n  "1": {"class_type": "X"}\n}'
    good = client.patch(f"/api/plugins/instances/{instance_id}", json={"config": {"template": raw}})
    assert good.status_code == 200 and good.json()["config"]["template"] == raw, "存的是原文,不是解析后再写回的那一份"


def test_随应用发的插件多了工具_已接好的连接补上开关(tmp_path, monkeypatch) -> None:
    import json as _json

    from app.domain.plugins import bundled
    from app.domain.plugins.instances import exposed_tools

    source = tmp_path / "bundled" / "demo"
    source.mkdir(parents=True)
    manifest = {"id": "dev.test.bundled-demo", "name": "内置示例", "version": "1.0.0", "manifest_version": 1,
                "runtime": {"kind": "process", "entry": "main.py"},
                "tools": {"expose": "selected", "recommended": ["old", "new"],
                          "declare": [{"name": "old", "input_schema": {"type": "object"}}]}}
    (source / "main.py").write_text("", encoding="utf-8")
    (source / "mosael.plugin.json").write_text(_json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(bundled, "bundled_root", lambda: tmp_path / "bundled")
    plugins_dir = tmp_path / "installed"
    fresh_client()
    with SessionLocal() as db:
        bundled.install(db, plugins_dir)
        instance = PluginInstance(package_id=manifest["id"], name="示例", enabled=True, owner_user_id="u")
        db.add(instance)
        db.commit()
        bundled.install(db, plugins_dir)
        assert exposed_tools(db, instance.id) == {"old"}
        manifest["version"] = "1.1.0"
        manifest["tools"]["declare"].append({"name": "new", "input_schema": {"type": "object"}})
        (source / "mosael.plugin.json").write_text(_json.dumps(manifest), encoding="utf-8")
        bundled.install(db, plugins_dir)
        assert exposed_tools(db, instance.id) == {"old", "new"}, "升级带来的新工具按 recommended 预勾"


@pytest.fixture(autouse=True)
def _clean_markers():
    from app.domain.plugins.runtime import data_dir_for

    marker = data_dir_for(MANIFEST["id"]) / "stopped-remote"
    marker.unlink(missing_ok=True)
    yield
    marker.unlink(missing_ok=True)
