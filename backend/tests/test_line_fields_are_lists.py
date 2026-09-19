"""声明为「行列表」的字段,库里只存列表。

生成节点的输入素材此前存成一整段多行文本。某一行正好是一整串引用(`{{角色三视图.results}}`)时,
插值后是一组素材 —— 而它和别的行拼在同一个字符串里,列表被 `str()` 成 `['…']`,当场就坏。

所以规范形状改成**行的列表**:保存/导入经过的图规范化只写列表,库里已有的由迁移一次转好,
编辑器只认列表。这里钉住三处:规范化、迁移、以及列表里的整组引用在运行时真的被摊平。
"""

from __future__ import annotations

import json

from app.core.db import SessionLocal
from app.db.models import Workflow
from app.domain.workflows import NODE_TYPES
from app.domain.workflows.normalization import canonicalize_line_fields, normalize_graph

TEXT = "{{a.asset_id}}:first_frame\n\n  {{b.asset_id}}:last_frame  \n"


def _graph(source_assets) -> dict:
    generate = {"id": "gen", "type": "ai_generate", "config": {"prompt": "p", "source_assets": source_assets}}
    loop = {"id": "loop", "type": "loop_foreach", "config": {
        "items": "[]", "body": {"nodes": [{**generate, "id": "inner"}], "edges": []},
    }}
    return {"nodes": [{"id": "start", "type": "start", "config": {}}, generate, loop], "edges": []}


def test_多行文本按行拆成列表_循环体里的也一样() -> None:
    graph = canonicalize_line_fields(_graph(TEXT), node_types=NODE_TYPES)
    expected = ["{{a.asset_id}}:first_frame", "{{b.asset_id}}:last_frame"]
    assert graph["nodes"][1]["config"]["source_assets"] == expected
    assert graph["nodes"][2]["config"]["body"]["nodes"][0]["config"]["source_assets"] == expected


def test_已经是列表的原样不动_规范化幂等() -> None:
    once = normalize_graph(_graph(TEXT), node_types=NODE_TYPES)
    assert normalize_graph(once, node_types=NODE_TYPES) == once


def test_迁移把库里已存的多行文本转成列表() -> None:
    from app.db.migrations import _migrate_line_fields_are_lists
    from tests.util import fresh_client

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        #: 直接写行,绕过保存入口 —— 模拟规范形状改变之前落库的图。
        workflow = Workflow(workspace_id=ws, name="旧图", graph=_graph(TEXT))
        db.add(workflow)
        db.commit()
        workflow_id = workflow.id

    _migrate_line_fields_are_lists()
    _migrate_line_fields_are_lists()

    with SessionLocal() as db:
        graph = db.get(Workflow, workflow_id).graph
        graph = json.loads(graph) if isinstance(graph, str) else graph
        assert graph["nodes"][1]["config"]["source_assets"] == ["{{a.asset_id}}:first_frame", "{{b.asset_id}}:last_frame"]


def test_列表里的整组引用在运行时被摊平() -> None:
    """插值保留整串引用的原类型(一组),解析时摊平 —— 和一条一条写出来是一回事。"""
    from app.domain.generation.operations import parse_source_assets
    from app.domain.workflows import interpolate

    config = ["{{first.asset_id}}:first_frame", "{{sheets.results}}"]
    context = {"first": {"asset_id": "f1"}, "sheets": {"results": ["h1:reference_image", "h2:reference_image"]}}
    parsed = parse_source_assets(interpolate(config, context), kind="video")
    assert [(one["asset_id"], one["role"]) for one in parsed] == [
        ("f1", "first_frame"), ("h1", "reference_image"), ("h2", "reference_image"),
    ]
