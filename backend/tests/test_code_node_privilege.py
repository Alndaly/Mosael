"""`code` 节点是主机权限,不是内容权限。

code 节点在后端主机上跑任意 Python:子进程隔离 + 超时 + 输出上限,但不是沙箱——里面的代码
能读写文件系统、发网络请求。而工作流的所有写路由只要 `edit`,editor 默认就有 `edit`。团队/
远程后端下,这等于任何 editor 都能拿服务器。这些用例把「落库入口一律要 instance-admin」钉死。

覆盖四条落库路径(create / import / patch / 确认卡审批),以及递归:把 code 节点框选
「折叠为子图」后它藏在 config["body"] 里,只查顶层的门禁会被这一步整个绕过。
"""

from __future__ import annotations

from app.domain.workflows import privileged_nodes_in_graph
from tests.util import fresh_client, second_client

CODE_NODE = {"id": "code_1", "type": "code", "config": {"code": "output = 1"}}
START_NODE = {"id": "start_1", "type": "start", "config": {}}

PLAIN_GRAPH = {"nodes": [START_NODE], "edges": []}
CODE_GRAPH = {"nodes": [START_NODE, CODE_NODE], "edges": []}
# code 节点藏进子图体内——「折叠为子图」产生的正是这个形状。
FOLDED_GRAPH = {
    "nodes": [
        START_NODE,
        {"id": "sub_1", "type": "subgraph", "config": {"body": {"nodes": [CODE_NODE], "edges": []}}},
    ],
    "edges": [],
}
# 再折一层:子图套子图。
DOUBLE_FOLDED_GRAPH = {
    "nodes": [
        START_NODE,
        {
            "id": "sub_1",
            "type": "subgraph",
            "config": {"body": {"nodes": [FOLDED_GRAPH["nodes"][1]], "edges": []}},
        },
    ],
    "edges": [],
}


def _setup(role: str):
    """Owner 工作区 + 一个 `role` 身份的第二成员;返回 (owner, ws, member_client)。"""
    owner = fresh_client()
    ws = owner.post("/api/workspaces", json={"name": "W"}).json()
    mate = second_client("mate")
    owner.post(f"/api/workspaces/{ws['id']}/invitations", json={"username": "mate", "role": role})
    inv = mate.get("/api/invitations").json()["invitations"][0]
    mate.post(f"/api/invitations/{inv['id']}/accept")
    return owner, ws, mate


# ---------------- 纯函数:递归扫描 ----------------


def test_scanner_finds_code_at_top_level() -> None:
    assert privileged_nodes_in_graph(CODE_GRAPH) == {"code"}


def test_scanner_descends_into_subgraph_body() -> None:
    """折叠为子图不能把 code 节点藏起来——这是最容易漏的那条路径。"""
    assert privileged_nodes_in_graph(FOLDED_GRAPH) == {"code"}
    assert privileged_nodes_in_graph(DOUBLE_FOLDED_GRAPH) == {"code"}


def test_scanner_descends_into_loop_body() -> None:
    graph = {
        "nodes": [{"id": "loop_1", "type": "loop_foreach", "config": {"body": {"nodes": [CODE_NODE]}}}],
        "edges": [],
    }
    assert privileged_nodes_in_graph(graph) == {"code"}


def test_scanner_clean_on_ordinary_graph() -> None:
    assert privileged_nodes_in_graph(PLAIN_GRAPH) == set()


def test_scanner_survives_malformed_input() -> None:
    """畸形图不能把校验炸掉——炸掉就等于门禁失效。"""
    for junk in (None, "nope", 42, {}, {"nodes": None}, {"nodes": ["x", None, {}]}):
        assert privileged_nodes_in_graph(junk) == set()


def test_scanner_survives_self_referential_body() -> None:
    """自引用的 body 不能让递归无限下去——扫描器炸掉或挂死都等于门禁失效。"""
    graph: dict = {"nodes": [{"id": "s", "type": "subgraph", "config": {}}, CODE_NODE], "edges": []}
    graph["nodes"][0]["config"]["body"] = graph  # 自己把自己当子图体
    assert privileged_nodes_in_graph(graph) == {"code"}  # 正常返回,且仍然看见了 code


# ---------------- 四条落库路径 ----------------


def test_owner_may_save_code_node() -> None:
    """单机安装不受影响:用户是自己工作区的 owner。"""
    owner = fresh_client()
    ws = owner.post("/api/workspaces", json={"name": "W"}).json()
    r = owner.post("/api/workflows", json={"workspace_id": ws["id"], "name": "W", "graph": CODE_GRAPH})
    assert r.status_code == 200, r.text


def test_editor_may_save_ordinary_graph() -> None:
    """门禁只针对 code 节点,不能顺手把普通工作流也挡了。"""
    _owner, ws, editor = _setup("editor")
    r = editor.post("/api/workflows", json={"workspace_id": ws["id"], "name": "W", "graph": PLAIN_GRAPH})
    assert r.status_code == 200, r.text


def test_editor_blocked_from_creating_code_node() -> None:
    _owner, ws, editor = _setup("editor")
    r = editor.post("/api/workflows", json={"workspace_id": ws["id"], "name": "W", "graph": CODE_GRAPH})
    assert r.status_code == 403, r.text
    # 文案要点名是哪个节点:通用的「Instance settings require admin」对着画布看没人懂。
    detail = r.json()["detail"]
    assert "代码" in detail and "管理员" in detail, detail


def test_editor_blocked_from_folded_code_node() -> None:
    """把 code 折进子图不是绕过门禁的办法。"""
    _owner, ws, editor = _setup("editor")
    r = editor.post("/api/workflows", json={"workspace_id": ws["id"], "name": "W", "graph": FOLDED_GRAPH})
    assert r.status_code == 403, r.text


def test_editor_blocked_from_patching_in_code_node() -> None:
    """先存一张干净的图,再 PATCH 塞 code 节点——update 路径同样要挡。"""
    _owner, ws, editor = _setup("editor")
    wf = editor.post(
        "/api/workflows", json={"workspace_id": ws["id"], "name": "W", "graph": PLAIN_GRAPH}
    ).json()
    r = editor.patch(f"/api/workflows/{wf['id']}", json={"graph": CODE_GRAPH})
    assert r.status_code == 403, r.text


def test_editor_may_patch_non_graph_fields() -> None:
    """不带 graph 的 PATCH(改名等)不该被 code 门禁波及。"""
    _owner, ws, editor = _setup("editor")
    wf = editor.post(
        "/api/workflows", json={"workspace_id": ws["id"], "name": "W", "graph": PLAIN_GRAPH}
    ).json()
    assert editor.patch(f"/api/workflows/{wf['id']}", json={"name": "改个名"}).status_code == 200


def test_editor_blocked_from_importing_code_node() -> None:
    """导入是最像「只是拖个文件」的入口,但文件里的 graph 原样落库。"""
    _owner, ws, editor = _setup("editor")
    payload = {
        "workspace_id": ws["id"],
        "data": {"format": "openstudio-workflow", "version": 1, "name": "载荷", "graph": CODE_GRAPH},
    }
    r = editor.post("/api/workflows/import", json=payload)
    assert r.status_code == 403, r.text


def test_admin_may_save_code_node() -> None:
    """门禁是 instance-admin,不是 owner-only——admin 应当放行。"""
    _owner, ws, admin = _setup("admin")
    r = admin.post("/api/workflows", json={"workspace_id": ws["id"], "name": "W", "graph": CODE_GRAPH})
    assert r.status_code == 200, r.text


# ---------------- 第四条:确认卡审批 ----------------
#
# 智能体那条路的形状和另外三条不一样:create/update_workflow 的卡带着**整份 graph**,
# 而 edit_workflow 只带 operations —— 图要把 ops 应用到当前图上才出现。门禁按 payload["graph"]
# 取值,于是 edit_workflow 那条恒为 None、静默跳过,而 add_node(type=code) 恰恰走这条路。
# 画布没有这个形状(它总是 PATCH 整份图),所以这条路只有智能体走,也只有这里能挡。


def _workflow_for(client, workspace_id: str) -> dict:
    return client.post(
        "/api/workflows", json={"workspace_id": workspace_id, "name": "W", "graph": PLAIN_GRAPH}
    ).json()


def _card(client, workspace_id: str, tool: str, payload: dict):
    return client.post(
        "/api/confirmations", json={"workspace_id": workspace_id, "tool": tool, "payload": payload}
    )


def test_editor_blocked_from_adding_code_node_via_agent_ops() -> None:
    """edit_workflow 的 add_node 是第四条落库路径,门禁一样要挡。"""
    _owner, ws, editor = _setup("editor")
    workflow = _workflow_for(editor, ws["id"])
    card = _card(
        editor,
        ws["id"],
        "edit_workflow",
        {
            "workflow_id": workflow["id"],
            "operations": [{"kind": "add_node", "type": "code", "config": {"code": "output = 1"}}],
        },
    )
    assert card.status_code == 200, card.text
    editor.post(f"/api/confirmations/{card.json()['id']}/approve")
    after = editor.get(f"/api/workflows/{workflow['id']}").json()
    types = [node["type"] for node in after["graph"]["nodes"]]
    assert "code" not in types, "editor 通过智能体的 ops 路径落库了一个 code 节点"


def test_editor_blocked_from_folding_code_into_a_subgraph_via_agent_ops() -> None:
    """ops 不只有 add_node —— set_node_config 能把整张含 code 的图塞进子图体里。

    只扫 operations 里的 node_type 会漏掉这一手;门禁要看的是**ops 应用之后**的图。
    """
    _owner, ws, editor = _setup("editor")
    workflow = _workflow_for(editor, ws["id"])
    card = _card(
        editor,
        ws["id"],
        "edit_workflow",
        {
            "workflow_id": workflow["id"],
            "operations": [
                {"kind": "add_node", "type": "subgraph", "node_id": "sub_1"},
                {"kind": "set_node_config", "node_id": "sub_1", "config": {"body": {"nodes": [CODE_NODE], "edges": []}}},
            ],
        },
    )
    assert card.status_code == 200, card.text
    editor.post(f"/api/confirmations/{card.json()['id']}/approve")
    after = editor.get(f"/api/workflows/{workflow['id']}").json()
    assert privileged_nodes_in_graph(after["graph"]) == set(), "code 节点被折进子图后落库了"


def test_editor_blocked_from_replacing_the_graph_via_agent_update() -> None:
    """对照:update_workflow 带整份 graph,这条今天就挡住了——不能在修复里把它弄丢。"""
    _owner, ws, editor = _setup("editor")
    workflow = _workflow_for(editor, ws["id"])
    card = _card(editor, ws["id"], "update_workflow", {"workflow_id": workflow["id"], "graph": CODE_GRAPH})
    assert card.status_code == 200, card.text
    editor.post(f"/api/confirmations/{card.json()['id']}/approve")
    after = editor.get(f"/api/workflows/{workflow['id']}").json()
    assert privileged_nodes_in_graph(after["graph"]) == set()


def test_editor_may_still_make_ordinary_agent_edits() -> None:
    """门禁只针对特权节点:普通 ops 必须照常批准并落库,否则修复就把智能体废了。"""
    _owner, ws, editor = _setup("editor")
    workflow = _workflow_for(editor, ws["id"])
    card = _card(
        editor,
        ws["id"],
        "edit_workflow",
        {"workflow_id": workflow["id"], "operations": [{"kind": "add_node", "type": "template", "node_id": "t_1"}]},
    )
    assert card.status_code == 200, card.text
    settled = editor.post(f"/api/confirmations/{card.json()['id']}/approve")
    assert settled.json()["status"] == "executed", settled.text
    after = editor.get(f"/api/workflows/{workflow['id']}").json()
    assert [node["type"] for node in after["graph"]["nodes"]] == ["start", "template"]


def test_admin_may_add_a_code_node_via_agent_ops() -> None:
    """admin 走这条路应当放行——门禁是 instance-admin,不是"智能体一律不许"。"""
    _owner, ws, admin = _setup("admin")
    workflow = _workflow_for(admin, ws["id"])
    card = _card(
        admin,
        ws["id"],
        "edit_workflow",
        {
            "workflow_id": workflow["id"],
            "operations": [{"kind": "add_node", "type": "code", "config": {"code": "output = 1"}}],
        },
    )
    assert card.status_code == 200, card.text
    settled = admin.post(f"/api/confirmations/{card.json()['id']}/approve")
    assert settled.json()["status"] == "executed", settled.text
    after = admin.get(f"/api/workflows/{workflow['id']}").json()
    assert privileged_nodes_in_graph(after["graph"]) == {"code"}
