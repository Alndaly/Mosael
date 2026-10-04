"""引用了一个节点**没有的输出**(`{{t.nokey}}`),运行前就拦,说清是谁引用了谁的哪个输出、它有哪些输出。

此前只核对「节点在不在」:节点在、输出拼错了(或者上游改了输出名),运行时插值成空串,下游拿着空值照样跑 —— 付费生成
照样扣费,工作流照样报成功。判据和画布就绪清单是同一条(contracts/workflow-output-reference-cases.json 两侧各跑一遍);
这里看真实目录、真实接口上的样子:整句说的是哪个节点、哪个输出、可选的有哪些;动态输出(运行时才知道键)不误报;官方模板一条都不报。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.i18n import set_current_locale
from app.db.models import Job, User
from app.domain.workflows import validate_graph
from app.domain.workflows.templates import TEMPLATE_CATALOG, built_in_template_graph
from tests.util import fresh_client


@pytest.fixture(autouse=True)
def _locale():
    set_current_locale("zh")
    yield
    set_current_locale("zh")


def _chain(*nodes: dict) -> dict:
    ids = ["start", *(node["id"] for node in nodes)]
    return {
        "nodes": [{"id": "start", "type": "start", "name": "开始", "config": {"params": {"topic": "猫"}}}, *nodes],
        "edges": [{"id": f"e{index}", "source": ids[index - 1], "target": ids[index]} for index in range(1, len(ids))],
    }


SCRIPT = {"id": "script", "type": "template", "name": "写稿子", "config": {"template": "{{start.topic}}"}}


def _output_errors(graph: dict) -> list[str]:
    return [one for one in validate_graph(graph) if "没有的输出" in one or "声明的结构里" in one]


def test_引用了没有的输出_点运行当场拦下_不建任务_英文界面整句英文() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    graph = _chain(SCRIPT, {"id": "post", "type": "template", "name": "拼文案", "config": {"template": "标题:{{script.titel}}"}})
    saved = client.post("/api/workflows", json={"workspace_id": ws, "name": "W", "graph": graph})
    assert saved.status_code == 200, "保存不拦:上游改了输出名,下游那几格还没改,不该连存都存不下"
    workflow_id = saved.json()["id"]

    zh = client.post(f"/api/workflows/{workflow_id}/run", json={"params": {}})
    assert zh.status_code == 422, zh.text
    assert zh.json()["detail"] == "「拼文案」引用了「写稿子」没有的输出 写稿子 · titel:它的输出有 文本"
    en = client.post(f"/api/workflows/{workflow_id}/run", json={"params": {}}, headers={"Accept-Language": "en"})
    assert en.json()["detail"] == "“拼文案” references an output “写稿子” doesn't have: 写稿子 · titel. Its outputs are Text"
    with SessionLocal() as db:
        assert db.scalars(select(Job).where(Job.kind == "workflow")).all() == [], "拦在建任务之前,上游一个都没跑"


def test_大模型给了_Schema_拼错的子字段拦下_列出那一层有的字段() -> None:
    judge = {"id": "judge", "type": "llm", "name": "评审", "config": {
        "prompt": "p", "response_format": "json_schema", "json_schema": {
            "type": "object", "additionalProperties": False,
            "properties": {"verdict": {"type": "string"}, "score": {"type": "number"}},
        },
    }}
    graph = _chain(judge, {"id": "post", "type": "template", "name": "拼文案",
                           "config": {"template": "{{judge.json.verdict}} / {{judge.json.verdikt}}"}})
    assert _output_errors(graph) == ["「拼文案」引用的 评审 · JSON · verdikt 不在「评审」声明的结构里:那一层只有 verdict、score"]


def test_数据边指着没有的输出_算在目标节点头上() -> None:
    graph = _chain(SCRIPT, {"id": "post", "type": "template", "name": "拼文案", "config": {"template": ""}})
    graph["edges"].append({"id": "d", "source": "script", "target": "post", "kind": "data",
                           "source_output": "txt", "target_input": "template"})
    assert _output_errors(graph) == ["「拼文案」引用了「写稿子」没有的输出 写稿子 · txt:它的输出有 文本"]


def test_循环体里和循环的对外输出_按体里那一层核对() -> None:
    body = {
        "nodes": [
            {"id": "a", "type": "template", "name": "写一句", "config": {"template": "{{loop.item}}"}},
            {"id": "b", "type": "template", "name": "改一句", "config": {"template": "{{a.txt}}"}},
        ],
        "edges": [{"id": "be", "source": "a", "target": "b"}],
    }
    loop = {"id": "each", "type": "loop_foreach", "name": "逐句", "config": {
        "items": "{{script.text}}", "body": body, "output": "{{b.result}}"}}
    assert _output_errors(_chain(SCRIPT, loop)) == [
        "「逐句 › 改一句」引用了「写一句」没有的输出 写一句 · txt:它的输出有 文本",
        "「逐句」引用了「改一句」没有的输出 改一句 · result:它的输出有 文本",
    ]


def test_动态输出底下的路径不误报() -> None:
    """运行时才知道键的:代码的 output、HTTP 的 json、调子工作流 / 子图的 output、插件工具的整份返回、JSON 提取的 value、
    浏览器脚本的 value、循环的 results、没给 Schema 的大模型 json —— 它们底下的路径一律不判,顶层的输出名照样核对。"""
    nodes = [
        SCRIPT,
        {"id": "py", "type": "code", "name": "算", "config": {"code": "output = {}", "input": {}}},
        {"id": "req", "type": "http_request", "name": "请求", "config": {"url": "https://example.com"}},
        {"id": "call", "type": "call_workflow", "name": "调子流程", "config": {"workflow_id": "", "inputs": {}}},
        {"id": "tool", "type": "plugin_tool", "name": "插件工具", "config": {}},
        {"id": "pick", "type": "json_extract", "name": "取字段", "config": {"json": "{}", "path": "a"}},
        {"id": "free", "type": "llm", "name": "随便写", "config": {"prompt": "p"}},
        {"id": "use", "type": "template", "name": "汇总", "config": {"template": (
            "{{py.output.a.b}} {{req.json.data.items.0}} {{call.output.x}} {{tool.output.rows}} "
            "{{pick.value.deep}} {{free.json.anything.at.all}}"
        )}},
    ]
    assert _output_errors(_chain(*nodes)) == []


def test_官方模板一条都不报() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        user = db.query(User).first()
        for card in TEMPLATE_CATALOG:
            graph = built_in_template_graph(db, card["id"], user_id=user.id, workspace_id=ws, locale="zh")
            assert _output_errors(graph) == [], card["id"]
