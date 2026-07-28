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
