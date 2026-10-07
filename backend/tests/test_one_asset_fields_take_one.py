"""只收**一份**素材的格子接到一个交出**一串**的口上。

一次出两张的 ComfyUI 工作流,那个保存节点的口上现在是两张(plugins.tools._collect_artifact:一个口交了几份就是几份),
和宫格切分的 `asset_ids` 一样是一串。下游只收一份的格子(内置节点的 `asset_id`、插件入参里 `format: asset` 的字符串)
接到它上面时:

- 只有一份:就是它(和接一个 id 一样);
- 好几份:不替人挑,报出来,说清两种接法 —— 只要一份就改接只交一份的口(「第一份产出」),每一份都要就放进循环。

此前一串原样往下交:内置节点 `str()` 成 "['…', '…']",报「素材不在这个工作区」;插件收到一串路径,按一个字符串读。
收一串的格子(`asset_ids`、插件的素材数组)照收。
"""

from __future__ import annotations

import io
import json
import textwrap
from pathlib import Path

import pytest
from PIL import Image

from app.core.db import SessionLocal
from app.db.models import PluginInstance, PluginPackage, Workflow
from app.domain.plugins.tools import invoke, refresh_tools
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.binding import one_asset_fields
from app.domain.workflows.engine import execute_graph
from tests.util import fresh_client, user_id

PACKAGE = "dev.test.onefile"
ENTRY = """
    import json, os, sys
    request = json.loads(sys.stdin.read())
    given = request["input"]
    print(json.dumps({"ok": True, "output": {"file": given.get("file"), "is_path": isinstance(given.get("file"), str)
                                             and os.path.isfile(given["file"]),
                                             "files": [os.path.isfile(one) for one in given.get("files") or []]}}))
"""
TOOLS = [{"name": "take", "input_schema": {"type": "object", "properties": {
    "file": {"type": "string", "format": "asset", "title": {"zh": "图", "en": "Image"}},
    "files": {"type": "array", "items": {"type": "string", "format": "asset"}},
}}}]


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 40, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


def _workspace_with_images(count: int) -> tuple[str, list[str]]:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    ids = [client.post("/api/assets/import", data={"workspace_id": ws},
                       files={"file": (f"图{index}.png", _png(), "image/png")}).json()["id"] for index in range(count)]
    return ws, ids


def _install(tmp_path: Path) -> str:
    plugin_dir = tmp_path / "onefile"
    plugin_dir.mkdir(exist_ok=True)
    (plugin_dir / "main.py").write_text(textwrap.dedent(ENTRY), encoding="utf-8")
    manifest = {"id": PACKAGE, "name": "一份", "version": "0.1.0", "runtime": {"kind": "process", "entry": "main.py"},
                "tools": {"expose": "all", "declare": TOOLS}, "_path": str(plugin_dir)}
    with SessionLocal() as db:
        db.add(PluginPackage(id=PACKAGE, name="一份", version="0.1.0", manifest=manifest))
        db.flush()
        instance = PluginInstance(package_id=PACKAGE, name="我的", enabled=True, owner_user_id=user_id())
        db.add(instance)
        db.commit()
        refresh_tools(db, instance, notify=False)
        db.commit()
        return instance.id


def test_插件只收一份的入参_一串里只有一份就是它_好几份报出来(tmp_path) -> None:
    ws, (first, second) = _workspace_with_images(2)
    instance_id = _install(tmp_path)
    with SessionLocal() as db:
        one = invoke(db, instance_id, "take", {"file": [first]}, workspace_id=ws)
        assert one.status == "succeeded", one.error
        assert one.output["is_path"] is True, "插件声明的是一个字符串:收到的是一条路径,不是一串"
        many = invoke(db, instance_id, "take", {"file": [first, second]}, workspace_id=ws)
        assert many.status == "failed"
        assert "「图」只收一份素材,上游交来了 2 份" in many.error and "第一份产出" in many.error and "循环" in many.error
        listed = invoke(db, instance_id, "take", {"files": [first, second]}, workspace_id=ws)
        assert listed.status == "succeeded" and listed.output["files"] == [True, True], "收一串的入参照收"


def test_内置节点只收一份的格子_一份就是它_好几份报出来_收一串的照收() -> None:
    assert one_asset_fields("image_grid_split", {"asset_id": ["a1"], "grid": "2x2"}) == {"asset_id": "a1", "grid": "2x2"}
    assert one_asset_fields("image_grid_split", {"asset_id": "a1"}) == {"asset_id": "a1"}, "一个 id 原样"
    with pytest.raises(WorkflowDomainError) as raised:
        one_asset_fields("image_speak", {"asset_id": "a1", "audio_asset_id": ["v1", "v2"]})
    assert raised.value.key == "wfErr_oneAssetGotMany" and str(raised.value.params["count"]) == "2"
    assert one_asset_fields("asset_tag", {"asset_ids": ["a1", "a2"]}) == {"asset_ids": ["a1", "a2"]}


def test_工作流里一串接到只收一份的格子_运行时说清怎么接(tmp_path) -> None:
    """走引擎那一条:开始节点交来一串(和一次出两张的口一样),数据边接到宫格切分的「图」。"""
    ws, ids = _workspace_with_images(2)
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="一串", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        wf_id = workflow.id
    graph = {
        "nodes": [{"id": "start", "type": "start", "config": {"params": {"pics": ""}}},
                  {"id": "split", "type": "image_grid_split", "config": {"asset_id": "", "grid": "2x2"}}],
        "edges": [{"id": "d1", "source": "start", "target": "split", "kind": "data",
                   "source_output": "pics", "target_input": "asset_id"}],
    }
    with pytest.raises(WorkflowDomainError) as raised:
        execute_graph(graph, wf_id=wf_id, params={"pics": ids})
    assert "只收一份素材,上游交来了 2 份" in json.dumps(raised.value.params, ensure_ascii=False) + str(raised.value)
    context, _ = execute_graph(graph, wf_id=wf_id, params={"pics": ids[:1]})
    assert context["split"]["count"] == 4 and context["split"]["source_asset_id"] == ids[0], "只有一份:就是它"
