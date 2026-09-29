"""笔记**写入**时引用的对话消息,跟着那次对话的读闸走。

读回来的那一刻(`/notes/sources/message/{id}`)早就过 `readable_session`;写进去的那一刻此前只查「消息在这个
工作区」,于是同事能把别人私有对话里的消息 id 写进笔记 —— 内容读不到,却能借「写不写得进」探出 id 在不在,
写进去的引用还以「来源」挂着。现在写入链(create / save / append,以及画板、智能体、工作流这些替人写的路)
都带着操作人,判据和读闸是同一份 `may_use`;看不见与不存在同一个回答。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import mcp_server
from app.core.db import SessionLocal
from app.core.security import mint_service_session
from app.db.models import User
from app.domain.authority import Authority, Voucher
from app.domain.note_types import NoteContent
from app.domain.notes import NoteNotFound, create_note
from app.main import app
from tests.test_agent_session_access import _message, _session, _team
from tests.test_board_write_entities_and_documents import Seen, _board, _write
from tests.test_boards import _writable_profile
from tests.test_mcp_tool_payloads import _route_through


def _cite(message_id: str) -> dict:
    return {"kind": "message", "id": message_id, "label": "对话", "quote": ""}


def _user_id(username: str) -> str:
    with SessionLocal() as db:
        return db.query(User).filter(User.username == username).one().id


def test_别人私有对话的消息_写不进笔记_和不存在一模一样() -> None:
    owner, workspace, mate = _team()
    private = _message(_session(owner, workspace, shared=False), "私下说的")

    def create(message_id: str):
        return mate.post("/api/notes", json={"workspace_id": workspace, "sources": [_cite(message_id)]})

    hidden, missing = create(private), create("no-such-message")
    assert hidden.status_code == 404, hidden.text
    assert (hidden.status_code, hidden.json()) == (missing.status_code, missing.json())

    # 改一版、追加,同一道闸。
    note = mate.post("/api/notes", json={"workspace_id": workspace, "markdown": "正文"}).json()
    edited = mate.patch(f"/api/notes/{note['id']}", json={**note, "base_revision": 1, "sources": [_cite(private)]})
    appended = mate.post(f"/api/notes/{note['id']}/append",
                         json={"workspace_id": workspace, "markdown": "补一句", "sources": [_cite(private)]})
    assert (edited.status_code, edited.json()) == (missing.status_code, missing.json())
    assert (appended.status_code, appended.json()) == (missing.status_code, missing.json())


def test_共享进来的对话和自己的对话_都能引用() -> None:
    owner, workspace, mate = _team()
    shared = _message(_session(owner, workspace, shared=True), "给大家看的")
    own = _message(_session(owner, workspace, shared=False), "我自己的")

    by_mate = mate.post("/api/notes", json={"workspace_id": workspace, "sources": [_cite(shared)]})
    assert by_mate.status_code == 200, by_mate.text
    by_owner = owner.post("/api/notes", json={"workspace_id": workspace, "sources": [_cite(own)]})
    assert by_owner.status_code == 200, by_owner.text
    assert by_owner.json()["sources"][0]["id"] == own


def test_说不出是谁_或被执行那一版没有担保人看得见_都当作不存在() -> None:
    """工作流传的是整份授权:跑的人看得见还不够,改过这一版图的人也得看得见 —— 否则同事改一下主人的图,
    主人的定时任务就替他把主人私有对话里的消息引进笔记。"""
    owner, workspace, _mate = _team()
    private = _message(_session(owner, workspace, shared=False))
    owner_id, mate_id = _user_id("tester"), _user_id("mate")
    content = NoteContent(sources=[_cite(private)])
    edited_by_mate = Authority(actor=owner_id, vouchers=(Voucher("wf", "流程", 2, frozenset({mate_id})),))

    with SessionLocal() as db:
        for actor in (None, edited_by_mate):
            with pytest.raises(NoteNotFound) as caught:
                create_note(db, workspace, content, actor=actor)
            assert caught.value.key == "noteErr_sourceNotInWorkspace"
        assert create_note(db, workspace, content, actor=owner_id).sources[0]["id"] == private


def test_画板上同事改写文档格_笔记上原有的来源照留() -> None:
    """画板替点「写」的那个人写。主人引的那条私有消息落库时已经过了主人的闸,同事改正文不重判它 ——
    否则一篇引过私有对话的笔记,除了主人谁都改不动。"""
    owner, workspace, mate = _team()
    private = _message(_session(owner, workspace, shared=False), "私下说的")
    note = owner.post("/api/notes", json={"workspace_id": workspace, "title": "企划", "markdown": "第一版",
                                          "sources": [_cite(private)]}).json()
    board_id = _board(owner, workspace, [{"id": "doc", "kind": "document", "x": 0, "y": 0, "note_id": note["id"],
                                          "note_revision": note["revision"], "text": "企划"}])
    _writable_profile(mate)

    done = _write(mate, board_id, workspace, "doc", "document", Seen("改过的正文"), prompt="改短一点")
    assert done.status_code == 200, done.text
    latest = owner.get(f"/api/notes/{note['id']}", params={"workspace_id": workspace}).json()
    assert latest["revision"] == 2 and latest["markdown"] == "改过的正文"
    assert [source["id"] for source in latest["sources"]] == [private]


def test_智能体在自己的对话里把消息存成笔记_操作人是这一轮的发起人(monkeypatch) -> None:
    """智能体的工具走 HTTP,带的是这一轮铸给**发消息的那个人**的令牌(agent/host._mint_service_session),
    没有跳过检查的「系统」身份:主人的智能体能引主人自己的对话,同事的智能体引不了主人的私有对话。"""
    owner, workspace, mate = _team()
    mine = _session(owner, workspace, shared=False)
    said = _message(mine, "把这段存下来")
    mates_own = mate.post("/api/agent/sessions", json={"workspace_id": workspace}).json()["id"]

    def agent_of(username: str, session_id: str) -> list[tuple[str, str, int, str]]:
        client = TestClient(app)
        with SessionLocal() as db:
            client.headers["Authorization"] = f"Bearer {mint_service_session(db, _user_id(username), agent_session_id=session_id)}"
        return _route_through(monkeypatch, client)

    agent_of("tester", mine)
    saved = mcp_server.create_note(title="摘录", markdown="把这段存下来", workspace_id=workspace, sources=[_cite(said)])
    assert saved["sources"][0]["id"] == said

    agent_of("mate", mates_own)
    told: list[str] = []
    for message_id in (said, "no-such-message"):
        with pytest.raises(ValueError) as caught:
            mcp_server.create_note(title="摘录", markdown="偷看", workspace_id=workspace, sources=[_cite(message_id)])
        told.append(str(caught.value))
    hidden, missing = told
    assert hidden.startswith("404") and hidden == missing, "模型读到的两句话一字不差"
