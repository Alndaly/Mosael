"""生成会话记出处(ADR 0052,D41–D47)。

- 每个入口说自己是哪一处:画板、工作流(画板上跑的能力归画板、资产详情页上的归资产)、定时任务、智能体那段对话(出图、念字、
  播客)、ComfyUI 工作台那张工作流;创作页是 `studio`;
- 别处一处一条:同一个人在同一处的生成都进同一条,标题空着(界面写那一处现在叫什么);创作页没点名就每次新开;
- 列表按看的人现查那一处的名字,删了是 `deleted`、看不见是 `hidden`(名字和 id 都不给);创作页这边开的、别处开的各取一份上限;
- 一条会话的记录可以只取最近的那几条(一块画板一条会话,跑了几百次就是几百轮)。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch as mock_patch

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import AgentSession, GenerationJob, GenerationSession, User, Workflow
from app.domain.generation import create_generation_job
from app.domain.generation.origins import (
    AGENT,
    BOARD,
    COMFYUI,
    ENTITY,
    SCHEDULE,
    STUDIO,
    STUDIO_ORIGIN,
    WORKFLOW,
    Origin,
    of_run_scope,
)
from tests.test_entity_generation_paths import _seedance, _workspace
from tests.util import board_revision, fresh_client, run_on_board

SEEDANCE = "doubao-seedance-2-0-260128"


@pytest.fixture(autouse=True)
def _external(monkeypatch) -> None:
    """只看漏斗把这一次放进了哪条会话,不真的跑。"""
    from app.domain import jobs as jobs_bus

    monkeypatch.setattr(jobs_bus, "_EXECUTION_MODES", {**jobs_bus._EXECUTION_MODES, "ai_generation": "external"})


def _me(db) -> str:
    return db.scalars(select(User).order_by(User.created_at)).first().id


def _generate(db, ws: str, me: str, profile: str, origin: Origin, *, prompt: str = "兔子跑过草地", session_id=None):
    generation, _job = create_generation_job(
        db, workspace_id=ws, session_id=session_id, project_id=None, created_by=me, provider="bytedance",
        provider_profile_id=profile, model=SEEDANCE, kind="video", prompt=prompt, negative_prompt="", parameters={},
        source_assets=[], origin=origin,
    )
    db.commit()
    return db.get(GenerationSession, generation.session_id)


def test_别处一处一条_标题空着_创作页没点名就每次新开() -> None:
    client = fresh_client()
    ws = _workspace(client)
    profile = _seedance(client)
    with SessionLocal() as db:
        me = _me(db)
        first = _generate(db, ws, me, profile, Origin(BOARD, "b1"))
        second = _generate(db, ws, me, profile, Origin(BOARD, "b1"), prompt="第二镜")
        other = _generate(db, ws, me, profile, Origin(BOARD, "b2"))
        assert first.id == second.id, "同一块画板上的第二次生成进了新的一条 —— 列表又被一次一条刷满"
        assert other.id != first.id
        assert (first.origin_kind, first.origin_id, first.title) == (BOARD, "b1", ""), "别处开的不起标题:界面写那一处的名字"
        assert db.scalar(select(GenerationJob.id).where(GenerationJob.session_id == first.id).offset(1)), "两次都在这一条里"

        studio_one = _generate(db, ws, me, profile, STUDIO_ORIGIN, prompt="海边的灯塔")
        studio_two = _generate(db, ws, me, profile, STUDIO_ORIGIN, prompt="海边的灯塔")
        assert studio_one.id != studio_two.id, "创作页没点名会话时每次新开(草稿第一次提交)"
        assert (studio_one.origin_kind, studio_one.title) == (STUDIO, "海边的灯塔")

        #: 点了名的会话照旧:出处只在没点名时用来找会话
        named = _generate(db, ws, me, profile, Origin(BOARD, "b1"), session_id=studio_one.id)
        assert named.id == studio_one.id and named.origin_kind == STUDIO


def test_同一处_各人各一条_老会话没合并时接着用最近用过的那条() -> None:
    from app.domain.generation.sessions import session_at

    client = fresh_client()
    ws = _workspace(client)
    with SessionLocal() as db:
        me = _me(db)
        colleague = User(username="colleague", display_name="同事", password_hash="x")
        db.add(colleague)
        db.flush()
        t0 = datetime(2026, 10, 1, 9, 0, 0)
        older = GenerationSession(workspace_id=ws, owner_user_id=me, title="一", kind="image", origin_kind=BOARD,
                                  origin_id="b1", updated_at=t0)
        newer = GenerationSession(workspace_id=ws, owner_user_id=me, title="二", kind="image", origin_kind=BOARD,
                                  origin_id="b1", updated_at=t0 + timedelta(hours=1))
        theirs = GenerationSession(workspace_id=ws, owner_user_id=colleague.id, title="", kind="image",
                                   origin_kind=BOARD, origin_id="b1", updated_at=t0 + timedelta(hours=2))
        db.add_all([older, newer, theirs])
        db.flush()
        assert session_at(db, workspace_id=ws, owner_user_id=me, origin=Origin(BOARD, "b1")).id == newer.id
        assert session_at(db, workspace_id=ws, owner_user_id=colleague.id, origin=Origin(BOARD, "b1")).id == theirs.id
        assert session_at(db, workspace_id=ws, owner_user_id=me, origin=Origin(WORKFLOW, "b1")) is None
        db.rollback()


def test_工作流执行器的作用域_画板上的能力归画板_资产详情页上的归资产() -> None:
    assert of_run_scope("w1") == Origin(WORKFLOW, "w1")
    assert of_run_scope("board:b1") == Origin(BOARD, "b1")
    assert of_run_scope("entity:e1") == Origin(ENTITY, "e1")


class _Seen(RuntimeError):
    pass


def _spy(seen: dict):
    def spy(*_args, **kwargs):
        seen.update(kwargs)
        raise _Seen("到这儿就够了")

    return spy


def test_每个入口说自己是哪一处() -> None:
    client = fresh_client()
    ws = _workspace(client)

    # 画板格子的「生成」
    board_id = client.post("/api/boards", json={"workspace_id": ws}).json()["id"]
    client.patch(f"/api/boards/{board_id}", json={
        "workspace_id": ws, "canvas": {"items": [{"id": "shot", "kind": "image", "x": 0, "y": 0}], "edges": []},
        "base_revision": board_revision(client, board_id, ws),
    })
    seen: dict = {}
    with mock_patch("app.domain.generation.create_generation_job", side_effect=_spy(seen)):
        with pytest.raises(_Seen):
            run_on_board(client, board_id, ws, producer="generate", item_id="shot", kind="image",
                         form={"prompt": "一只猫", "provider": "openai", "model": "gpt-image-1"})
    assert seen["origin"] == Origin(BOARD, board_id)

    # 工作流的 AI 生成节点:按作用域(工作流 / 画板上的能力 / 资产详情页)
    from app.domain.workflows.executors.subjobs import ai_generate

    for scope_id, expected in (("w1", Origin(WORKFLOW, "w1")), (f"board:{board_id}", Origin(BOARD, board_id)),
                               ("entity:e1", Origin(ENTITY, "e1"))):
        seen.clear()
        with SessionLocal() as db, mock_patch("app.domain.generation.create_generation_job", side_effect=_spy(seen)):
            with pytest.raises(_Seen):
                ai_generate(db, SimpleNamespace(workspace_id=ws, id=scope_id, name="x"), {"kind": "image", "prompt": "猫"})
        assert seen["origin"] == expected, scope_id

    # 定时任务
    from app.domain.scheduler.executors import _run_generation

    seen.clear()
    task = SimpleNamespace(id="t1", workspace_id=ws, project_id=None, owner_user_id=None, payload={"prompt": "早安海报"})
    with SessionLocal() as db, mock_patch("app.domain.generation.create_generation_job", side_effect=_spy(seen)):
        with pytest.raises(_Seen):
            _run_generation(db, task, SimpleNamespace(), SimpleNamespace())
    assert seen["origin"] == Origin(SCHEDULE, "t1")

    # 智能体:出图按对话归;念字、播客同一段对话也进同一处
    from app.domain.agent.confirmable import generation as agent_generation

    card = SimpleNamespace(tool="generate_image", workspace_id=ws, session_id="a1", payload={"prompt": "猫"})
    for target, run in (
        ("app.domain.generation.create_generation_job", lambda db: agent_generation._execute_generation(db, card, None)),
        ("app.domain.generation.voiced.create_speech",
         lambda db: agent_generation._execute_generate_audio(db, SimpleNamespace(**{**vars(card), "payload": {"text": "你好"}}), None)),
        ("app.domain.generation.voiced.create_podcast",
         lambda db: agent_generation._execute_generate_podcast(db, SimpleNamespace(**{**vars(card), "payload": {"text": "聊聊"}}), None)),
    ):
        seen.clear()
        with SessionLocal() as db, mock_patch(target, side_effect=_spy(seen)):
            with pytest.raises(_Seen):
                run(db)
        assert seen["origin"] == Origin(AGENT, "a1"), target
    #: 没挂在哪段对话上的老卡:出处说不出,和迁移同一个判据 —— studio
    seen.clear()
    with SessionLocal() as db, mock_patch("app.domain.generation.create_generation_job", side_effect=_spy(seen)):
        with pytest.raises(_Seen):
            agent_generation._execute_generation(db, SimpleNamespace(**{**vars(card), "session_id": None}), None)
    assert seen["origin"] == STUDIO_ORIGIN

    # ComfyUI 工作台的「运行」:那台连接上的那张工作流(和对话的 comfyui 地方同一种 id)
    from app.domain import workflow_library

    seen.clear()
    profile = SimpleNamespace(id="p1", vendor="plugin:dev.mosael.comfyui")
    row = SimpleNamespace(model_id="海报/封面.json", enabled=True, capability_ids=["image"])
    with SessionLocal() as db, \
            mock_patch.object(workflow_library, "_require", lambda *_a: None), \
            mock_patch.object(workflow_library, "_profile", lambda *_a: profile), \
            mock_patch.object(workflow_library.provider_models, "get_model", lambda *_a: row), \
            mock_patch("app.domain.generation.use_cases.generate", side_effect=_spy(seen)):
        with pytest.raises(_Seen):
            workflow_library.run_canvas(db, SimpleNamespace(id="u1"), SimpleNamespace(id="c1"), workspace_id=ws,
                                        path="海报/封面.json", prompt={"3": {"class_type": "KSampler", "inputs": {}}},
                                        workflow=None, client_id="")
    assert seen["origin"] == Origin(COMFYUI, "c1/海报/封面.json")


def test_列表按看的人现查那一处_删了的照留_两边各取一份上限() -> None:
    client = fresh_client()
    ws = _workspace(client)
    board_id = client.post("/api/boards", json={"workspace_id": ws, "name": "镜头与灵感"}).json()["id"]
    gone_board = client.post("/api/boards", json={"workspace_id": ws, "name": "要删的"}).json()["id"]
    t0 = datetime(2026, 10, 1, 9, 0, 0)
    with SessionLocal() as db:
        me = _me(db)
        workflow = Workflow(workspace_id=ws, name="产品短片", graph={"nodes": [], "edges": []})
        conversation = AgentSession(workspace_id=ws, owner_user_id=me, title="整理素材库")
        db.add_all([workflow, conversation])
        db.flush()
        studio = GenerationSession(workspace_id=ws, owner_user_id=me, title="海边的灯塔", kind="image", updated_at=t0)
        earlier = GenerationSession(workspace_id=ws, owner_user_id=me, title="", kind="speech", origin_kind="audio_page",
                                    origin_id="speech", updated_at=t0)
        rows = [
            GenerationSession(workspace_id=ws, owner_user_id=me, title="", kind="image", origin_kind=BOARD,
                              origin_id=board_id, updated_at=t0 + timedelta(hours=1)),
            GenerationSession(workspace_id=ws, owner_user_id=me, title="", kind="image", origin_kind=BOARD,
                              origin_id=gone_board, updated_at=t0 + timedelta(hours=1)),
            GenerationSession(workspace_id=ws, owner_user_id=me, title="", kind="video", origin_kind=WORKFLOW,
                              origin_id=workflow.id, updated_at=t0 + timedelta(hours=1)),
            GenerationSession(workspace_id=ws, owner_user_id=me, title="", kind="image", origin_kind=AGENT,
                              origin_id=conversation.id, updated_at=t0 + timedelta(hours=1)),
        ]
        #: 迁移之前一次一条的老会话:一个库里几十条,比用户自己开的都新
        rows += [GenerationSession(workspace_id=ws, owner_user_id=me, title=f"老的 {index}", kind="image",
                                   origin_kind=WORKFLOW, origin_id=workflow.id, updated_at=t0 + timedelta(minutes=index))
                 for index in range(60)]
        db.add_all([studio, earlier, *rows])
        db.commit()
        studio_id, earlier_id, board_session, gone_session = studio.id, earlier.id, rows[0].id, rows[1].id
    assert client.delete(f"/api/boards/{gone_board}", params={"workspace_id": ws}).status_code in (200, 204)

    listed = client.get("/api/generation/sessions", params={"workspace_id": ws}).json()
    by_id = {one["id"]: one for one in listed}
    assert studio_id in by_id and earlier_id in by_id, "别处开的老会话把用户自己开的挤出了列表"
    assert sum(1 for one in listed if one["origin_kind"] not in ("studio", "audio_page")) == 50
    assert [one["updated_at"] for one in listed] == sorted((one["updated_at"] for one in listed), reverse=True)
    assert {key: by_id[board_session][key] for key in ("origin_kind", "origin_id", "origin_name", "origin_state", "title")} == {
        "origin_kind": "board", "origin_id": board_id, "origin_name": "镜头与灵感", "origin_state": "ok", "title": "",
    }
    assert {key: by_id[gone_session][key] for key in ("origin_state", "origin_name", "origin_id")} == {
        "origin_state": "deleted", "origin_name": "", "origin_id": "",
    }, "画板删了会话照留(D47),名字和 id 都不给"
    assert (by_id[earlier_id]["origin_kind"], by_id[earlier_id]["origin_id"], by_id[earlier_id]["title"]) == (
        "audio_page", "speech", ""), "「以前的语音」标题空着,界面按读的人的语言写"
    agent_rows = [one for one in listed if one["origin_kind"] == "agent"]
    assert agent_rows and agent_rows[0]["origin_name"] == "整理素材库"

    #: 别人看不见那段对话:只说「一段对话」,名字不漏出来
    with SessionLocal() as db:
        conversation = db.scalars(select(AgentSession).where(AgentSession.title == "整理素材库")).one()
        conversation.owner_user_id = "someone-else"
        db.commit()
    hidden = [one for one in client.get("/api/generation/sessions", params={"workspace_id": ws}).json()
              if one["origin_kind"] == "agent"][0]
    assert (hidden["origin_state"], hidden["origin_name"], hidden["origin_id"]) == ("hidden", "", "")

    created = client.post("/api/generation/sessions", json={"workspace_id": ws, "kind": "image"}).json()
    assert (created["origin_kind"], created["origin_state"], created["title"]) == ("studio", "ok", "新生成")


def test_一条会话的记录可以只取最近的那几条_仍按时间正序() -> None:
    client = fresh_client()
    ws = _workspace(client)
    t0 = datetime(2026, 10, 1, 9, 0, 0)
    with SessionLocal() as db:
        session = GenerationSession(workspace_id=ws, owner_user_id=_me(db), title="", kind="image",
                                    origin_kind=BOARD, origin_id="b1")
        db.add(session)
        db.flush()
        for index in range(5):
            db.add(GenerationJob(workspace_id=ws, session_id=session.id, provider="p", model="m", kind="image",
                                 request={"prompt": f"第 {index} 次"}, created_at=t0 + timedelta(minutes=index)))
        db.commit()
        session_id = session.id
    every = client.get("/api/generation/jobs", params={"workspace_id": ws, "session_id": session_id}).json()
    latest = client.get("/api/generation/jobs", params={"workspace_id": ws, "session_id": session_id, "limit": 2}).json()
    assert [one["request"]["prompt"] for one in every] == [f"第 {index} 次" for index in range(5)]
    assert [one["request"]["prompt"] for one in latest] == ["第 3 次", "第 4 次"]


def test_出参的出处种类就是领域里的那几种() -> None:
    from typing import get_args

    from app.api.schemas.generation import GenerationOriginKind
    from app.domain.generation.origins import KINDS

    assert set(get_args(GenerationOriginKind)) == set(KINDS)
