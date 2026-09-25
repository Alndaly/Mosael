"""工作流整图保存的乐观并发:拿着旧底子存,就该撞 409,而不是把别人刚写的那份静默盖掉。

画板早就这么做了(base_revision → 409,见 domain/boards)。工作流的保存此前不带任何底子:
画布上有没存的改动时,智能体(或另一个窗口)刚改过的图,会被下一次自动保存整份覆盖掉。

底子用的是 `graph_hash` 而不是 `revision` —— revision 只在**执行语义**变了才增(纯布局不成版),
拿它当底子的话,别人挪过的节点照样会被旧快照盖回去。
"""

from __future__ import annotations

from copy import deepcopy

from app.core.db import SessionLocal
from app.db.models import Workflow
from tests.util import fresh_client


def _graph(template: str = "关于 {{start.topic}}") -> dict:
    return {
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}, "config": {"params": {"topic": "海边"}}},
            {"id": "t", "type": "template", "name": "写", "position": {"x": 240, "y": 0}, "config": {"template": template}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "t"}],
    }


def _setup(client):
    ws = client.post("/api/workspaces", json={"name": "并发"}).json()
    return ws, client.post("/api/workflows", json={"workspace_id": ws["id"], "name": "WF", "graph": _graph()}).json()


def test_拿着旧底子保存整图_撞409而不是盖掉别人刚写的() -> None:
    client = fresh_client()
    _ws, workflow = _setup(client)
    base = workflow["graph_hash"]

    # 别处(另一个窗口)先存了一版。
    theirs = client.patch(
        f"/api/workflows/{workflow['id']}",
        json={"graph": _graph("别处改的"), "base_graph_hash": base},
    )
    assert theirs.status_code == 200, theirs.text

    # 这边还拿着旧底子:存不上,并且说清是版本冲突。
    mine = client.patch(
        f"/api/workflows/{workflow['id']}",
        json={"graph": _graph("我这边改的"), "base_graph_hash": base},
    )
    assert mine.status_code == 409, mine.text
    detail = mine.json()["detail"]
    assert detail["code"] == "workflow_graph_conflict"
    assert detail["current_graph_hash"] == theirs.json()["graph_hash"]

    current = client.get(f"/api/workflows/{workflow['id']}").json()
    assert current["graph"]["nodes"][1]["config"]["template"] == "别处改的"


def test_只挪了位置也算别人的改动() -> None:
    """纯布局不增 revision,但它仍是别人的写入 —— 底子按整图摘要比,不按执行版本号比。"""
    client = fresh_client()
    _ws, workflow = _setup(client)
    moved = deepcopy(workflow["graph"])
    moved["nodes"][1]["position"] = {"x": 900, "y": 400}
    theirs = client.patch(f"/api/workflows/{workflow['id']}", json={"graph": moved, "base_graph_hash": workflow["graph_hash"]})
    assert theirs.status_code == 200 and theirs.json()["revision"] == workflow["revision"]

    mine = client.patch(
        f"/api/workflows/{workflow['id']}",
        json={"graph": _graph("我这边改的"), "base_graph_hash": workflow["graph_hash"]},
    )
    assert mine.status_code == 409, mine.text


def test_保存整图必须带底子() -> None:
    client = fresh_client()
    _ws, workflow = _setup(client)
    missing = client.patch(f"/api/workflows/{workflow['id']}", json={"graph": _graph("没带底子")})
    assert missing.status_code == 422, missing.text
    # 只改名不碰图,不需要底子。
    renamed = client.patch(f"/api/workflows/{workflow['id']}", json={"name": "新名字"})
    assert renamed.status_code == 200, renamed.text


def test_存的正好就是库里那份_不算冲突() -> None:
    client = fresh_client()
    _ws, workflow = _setup(client)
    theirs = client.patch(
        f"/api/workflows/{workflow['id']}", json={"graph": _graph("同一份"), "base_graph_hash": workflow["graph_hash"]}
    ).json()
    same = client.patch(
        f"/api/workflows/{workflow['id']}", json={"graph": _graph("同一份"), "base_graph_hash": workflow["graph_hash"]}
    )
    assert same.status_code == 200, same.text
    assert same.json()["graph_hash"] == theirs["graph_hash"]


def test_智能体整图替换_开卡之后用户改过就不执行() -> None:
    """update_workflow 的整图是对着开卡那一刻的图审的;批准之前用户又改了,就不能拿它盖掉。"""
    client = fresh_client()
    ws, workflow = _setup(client)
    card = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "update_workflow",
            "requested_by": "pi",
            "payload": {"workflow_id": workflow["id"], "graph": _graph("智能体的整图")},
        },
    ).json()
    user = client.patch(
        f"/api/workflows/{workflow['id']}", json={"graph": _graph("用户刚改的"), "base_graph_hash": workflow["graph_hash"]}
    )
    assert user.status_code == 200, user.text

    approved = client.post(f"/api/confirmations/{card['id']}/approve").json()
    assert approved["status"] == "failed"
    current = client.get(f"/api/workflows/{workflow['id']}").json()
    assert current["graph"]["nodes"][1]["config"]["template"] == "用户刚改的"


def test_智能体整图替换_没人动过就照常执行() -> None:
    client = fresh_client()
    ws, workflow = _setup(client)
    card = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "update_workflow",
            "requested_by": "pi",
            "payload": {"workflow_id": workflow["id"], "graph": _graph("智能体的整图")},
        },
    ).json()
    approved = client.post(f"/api/confirmations/{card['id']}/approve").json()
    assert approved["status"] == "executed", approved.get("error")
    current = client.get(f"/api/workflows/{workflow['id']}").json()
    assert current["graph"]["nodes"][1]["config"]["template"] == "智能体的整图"


def _write_behind_our_back(workflow_id: str, template: str) -> None:
    """另一个连接在「读完、还没写」的空档里写入一版。"""
    from app.domain.workflows import update_workflow

    with SessionLocal() as other:
        row = other.get(Workflow, workflow_id)
        assert row is not None
        update_workflow(other, row, {"graph": _graph(template)}, base_graph_hash=row.graph_hash)


def test_整图保存的读写空档里有人写入_撞冲突而不是重试着盖掉() -> None:
    from app.domain.workflows.revisions import WorkflowGraphConflict, commit_graph_revision, replace_graph

    client = fresh_client()
    _ws, workflow = _setup(client)
    wrote = []

    def sneaky(current: dict) -> dict:
        if not wrote:
            _write_behind_our_back(workflow["id"], "空档里写的")
            wrote.append(True)
        return replace_graph(_graph("拿旧底子存的"), base_graph_hash=workflow["graph_hash"])(current)

    with SessionLocal() as db:
        row = db.get(Workflow, workflow["id"])
        assert row is not None
        try:
            commit_graph_revision(db, row, sneaky, source="edit")
        except WorkflowGraphConflict:
            pass
        else:
            raise AssertionError("旧底子的整图保存必须撞冲突")
    current = client.get(f"/api/workflows/{workflow['id']}").json()
    assert current["graph"]["nodes"][1]["config"]["template"] == "空档里写的"


def test_按算子改图_撞上并发写入就在最新那份上重做() -> None:
    """edit_workflow 这类「只改自己那一处」的写入,撞了就重读再合 —— 和画板 _merge_into_latest 同一条。"""
    from app.domain.workflows import edit_workflow_graph

    client = fresh_client()
    _ws, workflow = _setup(client)
    wrote = []

    def rename_start(current: dict) -> dict:
        if not wrote:
            _write_behind_our_back(workflow["id"], "空档里写的")
            wrote.append(True)
        changed = deepcopy(current)
        changed["nodes"][0]["name"] = "智能体改的名"
        return changed

    with SessionLocal() as db:
        row = db.get(Workflow, workflow["id"])
        assert row is not None
        edit_workflow_graph(db, row, rename_start, source="agent")
    current = client.get(f"/api/workflows/{workflow['id']}").json()
    assert current["graph"]["nodes"][0]["name"] == "智能体改的名"
    assert current["graph"]["nodes"][1]["config"]["template"] == "空档里写的"
