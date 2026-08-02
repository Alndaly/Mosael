"""确认卡的权限档必须由**这次调用实际会做什么**决定,不能查一张静态表。

档位不只是卡片上的一个徽标:它决定措辞、决定用户会不会真看一眼,而三档权限模式一上,它直接决定
**要不要放行**。所以「这张卡属于哪一档」必须是从 payload 算出来的:

  - `run_workflow` 静态挂在 `ai-cost` 上,但工作流节点里有 code / http_request / publish /
    browser_* / plugin_tool —— 一张"可能产生 AI 消耗"的卡可以执行以上全部。
  - `create/update/edit_workflow` 静态是 `edit`(可撤销),但往图里写一个 publish 节点之后,
    这张图会被**别的触发路径**点着(定时、webhook),那时没有任何卡挡在前面。
  - `browser_pool_open` 静态是 `edit`,而它接的是用户**真实登录的身份**。

判据是"后果落在哪":`edit` 撤得回、`ai-cost` 最坏是花钱、`external` 撤不回。
"""

from __future__ import annotations

from app.domain.agent.confirmations import TOOL_DEFS, effective_permission
from app.domain.workflows import EXTERNAL_NODE_TYPES, INTERNAL_NODE_TYPES, NODE_TYPES, external_nodes_in_graph
from tests.util import fresh_client

START = {"id": "start_1", "type": "start", "config": {}}
CODE = {"id": "code_1", "type": "code", "config": {"code": "output = 1"}}
PUBLISH = {"id": "pub_1", "type": "publish", "config": {}}
LLM = {"id": "llm_1", "type": "llm", "config": {}}


def _graph(*nodes) -> dict:
    return {"nodes": [START, *nodes], "edges": []}


# ---------------- 节点分类 ----------------


def test_every_node_type_is_classified() -> None:
    """新增一个节点类型时,作者必须说清它的后果落在哪 —— 而不是默认落进"安全"那一边。

    这条断言的是**覆盖**:漏掉一个新节点类型,测试就红,而不是让它悄悄按内部处理。
    """
    classified = EXTERNAL_NODE_TYPES | INTERNAL_NODE_TYPES
    assert set(NODE_TYPES) - classified == set(), "有节点类型没有归类"
    assert classified - set(NODE_TYPES) == set(), "归类里有不存在的节点类型"
    assert EXTERNAL_NODE_TYPES & INTERNAL_NODE_TYPES == set(), "同一个节点被归了两边"


def test_scanner_finds_external_nodes_including_nested() -> None:
    assert external_nodes_in_graph(_graph(CODE)) == {"code"}
    assert external_nodes_in_graph(_graph(LLM)) == set()
    folded = _graph({"id": "sub_1", "type": "subgraph", "config": {"body": {"nodes": [PUBLISH]}}})
    assert external_nodes_in_graph(folded) == {"publish"}, "折叠成子图不该把它藏起来"


def test_call_workflow_is_treated_as_external() -> None:
    """它按 id 引用另一张图,扫描器跟不过去 —— 跟不过去就得保守。"""
    assert external_nodes_in_graph(_graph({"id": "c1", "type": "call_workflow", "config": {}})) == {"call_workflow"}


def test_scanner_survives_malformed_input() -> None:
    for junk in (None, "nope", 42, {}, {"nodes": None}, {"nodes": ["x", None, {}]}):
        assert external_nodes_in_graph(junk) == set()


# ---------------- 工具档位 ----------------


def test_browser_pool_open_is_external() -> None:
    """它接的是用户真实登录的身份 —— 不是"可撤销的编辑"。"""
    assert TOOL_DEFS["browser_pool_open"]["permission"] == "external"


def test_isolated_browser_stays_edit() -> None:
    """对照:隔离浏览器与用户身份物理隔开,不该被一起提上去。"""
    assert TOOL_DEFS["browser_open"]["permission"] == "edit"


def _workspace_with_workflow(client, graph: dict) -> tuple[str, str]:
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    workflow = client.post(
        "/api/workflows", json={"workspace_id": workspace["id"], "name": "WF", "graph": graph}
    ).json()
    return workspace["id"], workflow["id"]


def test_run_workflow_is_external_when_the_graph_reaches_outside() -> None:
    client = fresh_client()
    _ws, workflow_id = _workspace_with_workflow(client, _graph(PUBLISH))
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        assert effective_permission(db, "run_workflow", {"workflow_id": workflow_id}) == "external"


def test_run_workflow_stays_ai_cost_for_an_ordinary_graph() -> None:
    client = fresh_client()
    _ws, workflow_id = _workspace_with_workflow(client, _graph(LLM))
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        assert effective_permission(db, "run_workflow", {"workflow_id": workflow_id}) == "ai-cost"


def test_authoring_an_external_node_is_itself_external() -> None:
    """写进图里就够了 —— 定时/webhook 会点着它,那时没有卡挡在前面。"""
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        assert effective_permission(db, "create_workflow", {"name": "X", "graph": _graph(PUBLISH)}) == "external"
        assert effective_permission(db, "create_workflow", {"name": "X", "graph": _graph(LLM)}) == "edit"


def test_edit_workflow_ops_are_judged_on_the_resulting_graph() -> None:
    """ops 里看不见的东西,应用之后能看见:set_node_config 可以把整张含 code 的图塞进子图体。"""
    client = fresh_client()
    _ws, workflow_id = _workspace_with_workflow(client, _graph(LLM))
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        plain = effective_permission(
            db,
            "edit_workflow",
            {"workflow_id": workflow_id, "operations": [{"kind": "add_node", "type": "template", "node_id": "t1"}]},
        )
        assert plain == "edit"
        folded = effective_permission(
            db,
            "edit_workflow",
            {
                "workflow_id": workflow_id,
                "operations": [
                    {"kind": "add_node", "type": "subgraph", "node_id": "sub_1"},
                    {"kind": "set_node_config", "node_id": "sub_1", "config": {"body": {"nodes": [CODE]}}},
                ],
            },
        )
        assert folded == "external"


def test_a_tool_without_a_graph_keeps_its_static_tier() -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        assert effective_permission(db, "edit_timeline", {"sequence_id": "s", "operations": []}) == "edit"
        assert effective_permission(db, "generate_image", {"prompt": "x"}) == "ai-cost"
        assert effective_permission(db, "publish_asset", {"account_id": "a", "asset_id": "b"}) == "external"


# ---------------- 卡片上说了什么 ----------------


def test_the_card_carries_the_derived_tier() -> None:
    """派生的档位要真的落到卡上 —— 徽标、措辞、以后的放行判定都读它。"""
    client = fresh_client()
    workspace_id, workflow_id = _workspace_with_workflow(client, _graph(CODE))
    card = client.post(
        "/api/confirmations",
        json={"workspace_id": workspace_id, "tool": "run_workflow", "payload": {"workflow_id": workflow_id}},
    )
    assert card.status_code == 200, card.text
    body = card.json()
    assert body["permission"] == "external"
    assert "代码" in body["summary"], f"卡上没说图里有什么:{body['summary']}"


def test_an_ordinary_workflow_card_is_not_dressed_up_as_dangerous() -> None:
    client = fresh_client()
    workspace_id, workflow_id = _workspace_with_workflow(client, _graph(LLM))
    card = client.post(
        "/api/confirmations",
        json={"workspace_id": workspace_id, "tool": "run_workflow", "payload": {"workflow_id": workflow_id}},
    ).json()
    assert card["permission"] == "ai-cost"
    assert "⚠️" not in card["summary"], card["summary"]
