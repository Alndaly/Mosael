"""批准是写操作 —— 它的权限校验不能靠「当前请求恰好是 POST」推断出来。

`ensure_workspace_access` 是方法敏感的:`_request_method` 这个 ContextVar 只在 ASGI 中间件里
绑定,默认值是 `"GET"`,好让测试、worker、守护任务这些非 HTTP 路径「一律当读,不会误 403」。
那个宽松默认之所以安全,前提是**那些路径都不是授权路径**。

批准恰恰是授权路径。今天它只从 HTTP 路由和飞书回调进来(两者都是 POST,中间件绑得到),
所以 edit 权限校验是靠环境凑巧成立的 —— 一旦有人把它挪到后台线程(自动放行、定时重试、
队列消费),viewer 的批准就会连同执行一起通过,而且没有任何报错。这些用例把「审批者必须
持有 edit」钉成显式的,不依赖调用方是谁。
"""

from __future__ import annotations

import threading

from app.core.db import SessionLocal
from app.domain.permissions import PermissionDenied
from app.db.models import Sequence, ToolConfirmation, User
from tests.util import fresh_client, second_client


def _setup(role: str):
    """Owner 工作区 + 一个 `role` 身份的第二成员 + 一张待批的时间线编辑卡。"""
    owner = fresh_client()
    ws = owner.post("/api/workspaces", json={"name": "W"}).json()
    mate = second_client("mate")
    owner.post(f"/api/workspaces/{ws['id']}/invitations", json={"username": "mate", "role": role})
    invitation = mate.get("/api/invitations").json()["invitations"][0]
    mate.post(f"/api/invitations/{invitation['id']}/accept")

    project = owner.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    sequence = owner.post(
        "/api/sequences", json={"workspace_id": ws["id"], "project_id": project["id"], "name": "S"}
    ).json()
    card = owner.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "edit_timeline",
            "payload": {
                "sequence_id": sequence["id"],
                "operations": [{"kind": "add_track", "track_kind": "video"}],
            },
        },
    )
    assert card.status_code == 200, card.text
    return owner, ws, mate, sequence["id"], card.json()["id"]


def _approve_off_the_request_thread(card_id: str, username: str) -> BaseException | None:
    """在一条全新的线程里批准 —— 与后台线程/守护任务同构:没有绑定过请求方法的 context。"""
    captured: list[BaseException | None] = [None]

    def run() -> None:
        from app.domain.agent.confirmations import authorize_and_approve

        with SessionLocal() as db:
            user = db.query(User).filter(User.username == username).one()
            confirmation = db.get(ToolConfirmation, card_id)
            try:
                authorize_and_approve(db, user, confirmation)
            except BaseException as exc:  # noqa: BLE001 —— 用例要看的就是它抛没抛
                captured[0] = exc

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(timeout=20)
    assert not thread.is_alive(), "批准线程没跑完"
    return captured[0]


def _track_count(client, sequence_id: str) -> int:
    return len(client.get(f"/api/sequences/{sequence_id}").json()["tracks"])


def test_viewer_cannot_approve_off_the_request_thread() -> None:
    """没有 edit 权限的人,在任何调用路径上都不能批准。"""
    owner, _ws, _viewer, sequence_id, card_id = _setup("viewer")
    before = _track_count(owner, sequence_id)

    error = _approve_off_the_request_thread(card_id, "mate")

    assert isinstance(error, PermissionDenied), f"viewer 的批准没有被挡住:{error!r}"
    assert "Permission denied" in str(error), str(error)
    # 光看异常不够:门禁失效时卡片是**连同执行一起**通过的,时间线真的会多一条轨。
    assert _track_count(owner, sequence_id) == before, "viewer 的批准把编辑执行掉了"
    with SessionLocal() as db:
        assert db.get(ToolConfirmation, card_id).status == "pending"


def test_viewer_cannot_approve_over_http() -> None:
    """对照:同一个人走 HTTP 今天就被挡住了 —— 修复不能把这条弄丢。"""
    _owner, _ws, viewer, _sequence_id, card_id = _setup("viewer")
    response = viewer.post(f"/api/confirmations/{card_id}/approve")
    assert response.status_code == 403, response.text


def test_editor_may_approve_off_the_request_thread() -> None:
    """门禁只挡缺权限的人:editor 默认持有 edit,非 HTTP 路径上也该照常批准并执行。"""
    owner, _ws, _editor, sequence_id, card_id = _setup("editor")
    before = _track_count(owner, sequence_id)

    error = _approve_off_the_request_thread(card_id, "mate")

    assert error is None, f"editor 的批准被误挡:{error!r}"
    assert _track_count(owner, sequence_id) == before + 1
    with SessionLocal() as db:
        assert db.get(ToolConfirmation, card_id).status == "executed"


def _reject_off_the_request_thread(card_id: str, username: str) -> BaseException | None:
    captured: list[BaseException | None] = [None]

    def run() -> None:
        from app.domain.agent.confirmations import authorize_and_reject

        with SessionLocal() as db:
            user = db.query(User).filter(User.username == username).one()
            try:
                authorize_and_reject(db, user, db.get(ToolConfirmation, card_id))
            except BaseException as exc:  # noqa: BLE001
                captured[0] = exc

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(timeout=20)
    assert not thread.is_alive(), "拒绝线程没跑完"
    return captured[0]


def test_viewer_cannot_reject_either() -> None:
    """拒绝和批准是同一类决定 —— 走 HTTP 时 viewer 本来就被挡(POST → 判 edit),
    非 HTTP 路径上必须给出同一个答案,而不是靠 ContextVar 默认成 GET 才放过去。"""
    _owner, _ws, viewer, _sequence_id, card_id = _setup("viewer")
    assert viewer.post(f"/api/confirmations/{card_id}/reject").status_code == 403

    error = _reject_off_the_request_thread(card_id, "mate")

    assert isinstance(error, PermissionDenied), f"{error!r}"
    with SessionLocal() as db:
        assert db.get(ToolConfirmation, card_id).status == "pending"


def test_editor_may_reject_off_the_request_thread() -> None:
    _owner, _ws, _editor, _sequence_id, card_id = _setup("editor")
    assert _reject_off_the_request_thread(card_id, "mate") is None
    with SessionLocal() as db:
        assert db.get(ToolConfirmation, card_id).status == "rejected"


def test_sequence_is_untouched_when_the_approver_lacks_edit() -> None:
    """守住不变量本身:没过闸门的批准,不该在库里留下任何痕迹。"""
    owner, _ws, _viewer, sequence_id, _card_id = _setup("viewer")
    with SessionLocal() as db:
        revision_before = db.get(Sequence, sequence_id).revision
    _approve_off_the_request_thread(_card_id, "mate")
    with SessionLocal() as db:
        assert db.get(Sequence, sequence_id).revision == revision_before
