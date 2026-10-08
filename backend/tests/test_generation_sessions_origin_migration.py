"""`generation-sessions-origin-from-facts` 与 `earlier-speech-and-podcast-find-their-origin`(ADR 0052 §4,D46)。

喂的是照真实库的形状造的老会话:一次一条、每条只有一次生成;任务行有的还在、有的被「清空已结束」删了。归出处**只看查得到的
事实**(祖先任务、任务上的回执、工作台记号、确认卡的结果、画板格子上摆着的产出),查不到就是 `studio`;老会话不合并。
「以前的语音 / 播客」标成 `audio_page`、标题清空;里面带画板 / 对话回执的记录挪到那个人在那一处的会话,挪空了的删掉。
跑两遍和一遍一样。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select, text

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_earlier_speech_and_podcast_find_their_origin as resort
from app.db.migrations import _migrate_generation_sessions_get_an_origin as add_columns
from app.db.migrations import _migrate_generation_sessions_origin_from_facts as backfill
from app.db.models import Asset, GenerationJob, GenerationSession, Job, RecordReference, ToolConfirmation, User
from tests.util import fresh_client

T0 = datetime(2026, 9, 1, 10, 0, 0)


def _job(db, ws: str, job_id: str, kind: str, payload: dict, *, minutes: int, parent: str | None = None,
         by: str | None = None) -> None:
    at = T0 + timedelta(minutes=minutes)
    db.add(Job(id=job_id, workspace_id=ws, kind=kind, status="succeeded", payload=payload, result={},
               parent_job_id=parent, created_by=by, created_at=at, updated_at=at))


def _session(db, ws: str, owner: str, session_id: str, *, title: str = "一张图", kind: str = "image",
             minutes: int = 0) -> None:
    at = T0 + timedelta(minutes=minutes)
    db.add(GenerationSession(id=session_id, workspace_id=ws, owner_user_id=owner, title=title, kind=kind,
                             created_at=at, updated_at=at))


def _record(db, ws: str, session_id: str, record_id: str, *, job: str | None, minutes: int, kind: str = "image",
            request: dict | None = None, asset: str | None = None, profile: str | None = None, model: str = "m") -> None:
    at = T0 + timedelta(minutes=minutes)
    db.flush()  # 会话、任务、素材先落:记录对它们有外键
    db.add(GenerationJob(id=record_id, workspace_id=ws, session_id=session_id, job_id=job, provider="p", model=model,
                         kind=kind, request=request or {"prompt": "x"}, result_asset_id=asset, provider_profile_id=profile,
                         created_at=at, updated_at=at))


def _origins() -> dict[str, tuple[str, str, str, str]]:
    with SessionLocal() as db:
        return {row.id: (row.origin_kind, row.origin_id, row.title, row.kind or "")
                for row in db.scalars(select(GenerationSession))}


def test_老会话按事实归出处_以前的语音播客里查得到出处的挪过去_跑两遍和一遍一样() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        me = db.scalars(select(User).order_by(User.created_at)).first().id
        colleague = User(username="colleague", display_name="同事", password_hash="x")
        db.add(colleague)
        db.flush()
        other = colleague.id
        db.add(Asset(id="on-board", workspace_id=ws, kind="image", name="图", source="ai", media_info={}))
        # —— 任务还在 ——
        _session(db, ws, me, "s-board")
        _job(db, ws, "j-board", "ai_generation", {"receipt": {"kind": "board_item", "board_id": "B", "item_id": "i1"}}, minutes=1)
        _record(db, ws, "s-board", "r-board", job="j-board", minutes=1)
        _session(db, ws, me, "s-workflow")
        _job(db, ws, "j-run", "workflow", {"workflow_id": "W"}, minutes=2)
        _job(db, ws, "j-wf-gen", "ai_generation", {}, minutes=2, parent="j-run")
        _record(db, ws, "s-workflow", "r-workflow", job="j-wf-gen", minutes=2)
        #: 定时任务跑的工作流:包装任务复用成工作流任务,两个记号都在 —— 生成在那张工作流里
        _session(db, ws, me, "s-scheduled-workflow")
        _job(db, ws, "j-sched-run", "workflow", {"scheduled_task_id": "T", "workflow_id": "W2"}, minutes=3)
        _job(db, ws, "j-sched-node", "ai_generation", {}, minutes=3, parent="j-sched-run")
        _record(db, ws, "s-scheduled-workflow", "r-scheduled-workflow", job="j-sched-node", minutes=3)
        _session(db, ws, me, "s-schedule")
        _job(db, ws, "j-wrapper", "ai_generation", {"scheduled_task_id": "T"}, minutes=4)
        _job(db, ws, "j-sched-gen", "ai_generation", {}, minutes=4, parent="j-wrapper")
        _record(db, ws, "s-schedule", "r-schedule", job="j-sched-gen", minutes=4)
        _session(db, ws, me, "s-board-run")
        _job(db, ws, "j-board-run", "board_run", {"board_id": "B2", "item_id": "i9"}, minutes=5)
        _job(db, ws, "j-board-node", "ai_generation", {"receipt": {"kind": "board_item", "board_id": "B2"}}, minutes=5,
             parent="j-board-run")
        _record(db, ws, "s-board-run", "r-board-run", job="j-board-node", minutes=5)
        _session(db, ws, me, "s-entity")
        _job(db, ws, "j-draw", "entity_draw", {"entity_id": "E"}, minutes=6)
        _job(db, ws, "j-draw-gen", "ai_generation", {}, minutes=6, parent="j-draw")
        _record(db, ws, "s-entity", "r-entity", job="j-draw-gen", minutes=6)
        _session(db, ws, me, "s-agent")
        _job(db, ws, "j-agent", "ai_generation", {"receipt": {"kind": "agent_session", "session_id": "A"}}, minutes=7)
        _record(db, ws, "s-agent", "r-agent", job="j-agent", minutes=7)
        #: 任务在、什么都没说:创作页开的
        _session(db, ws, me, "s-studio", minutes=8)
        _job(db, ws, "j-studio", "ai_generation", {}, minutes=8)
        _record(db, ws, "s-studio", "r-studio", job="j-studio", minutes=8, asset="on-board")
        #: 第一条(开出它的那一次)说了算:后来在创作页里接着生成的还是画板那条
        _session(db, ws, me, "s-continued", minutes=10)
        _job(db, ws, "j-cont-1", "ai_generation", {"receipt": {"kind": "board_item", "board_id": "B"}}, minutes=9)
        _record(db, ws, "s-continued", "r-cont-1", job="j-cont-1", minutes=9)
        _job(db, ws, "j-cont-2", "ai_generation", {}, minutes=10)
        _record(db, ws, "s-continued", "r-cont-2", job="j-cont-2", minutes=10)
        # —— 任务被清掉了 ——
        _session(db, ws, me, "s-gone-agent")
        _record(db, ws, "s-gone-agent", "r-gone-agent", job=None, minutes=11)
        db.add(ToolConfirmation(workspace_id=ws, session_id="A2", tool="generate_image", permission="ai-cost",
                                payload={}, status="approved", result={"generation_id": "r-gone-agent"}, requested_by="agent"))
        _session(db, ws, me, "s-gone-board")
        _record(db, ws, "s-gone-board", "r-gone-board", job=None, minutes=12, asset="on-board")
        _session(db, ws, me, "s-gone-two")
        _record(db, ws, "s-gone-two", "r-gone-two-1", job=None, minutes=13, asset="on-board")
        _record(db, ws, "s-gone-two", "r-gone-two-2", job=None, minutes=14)
        db.add(RecordReference(source_kind="board", source_id="B3", target_kind="asset", target_id="on-board", how="cell",
                               workspace_id=ws))
        _session(db, ws, me, "s-gone-unknown")
        _record(db, ws, "s-gone-unknown", "r-gone-unknown", job=None, minutes=15)
        _session(db, ws, me, "s-workbench")
        _record(db, ws, "s-workbench", "r-workbench", job=None, minutes=16, request={"prompt": "", "workbench": True},
                model="海报/封面.json")
        _session(db, ws, me, "s-empty")
        # —— 以前的语音 / 播客 ——
        _session(db, ws, me, "s-earlier-speech", title="以前的语音", kind="speech", minutes=20)
        for job_id, payload, minutes in (
            ("j-speak-board", {"receipt": {"kind": "board_item", "board_id": "B", "item_id": "i2"}, "session_id": "x"}, 20),
            ("j-speak-agent", {"receipt": {"kind": "agent_session", "session_id": "A"}}, 21),
            ("j-speak-note", {"text": "笔记朗读,没记是哪篇"}, 22),
        ):
            _job(db, ws, job_id, "tts", payload, minutes=minutes, by=me)
            _record(db, ws, "s-earlier-speech", f"r-{job_id}", job=job_id, minutes=minutes, kind="speech")
        _session(db, ws, me, "s-earlier-podcast", title="以前的播客", kind="podcast", minutes=23)
        _job(db, ws, "j-pod-agent", "podcast", {"receipt": {"kind": "agent_session", "session_id": "A9"}}, minutes=23, by=me)
        _record(db, ws, "s-earlier-podcast", "r-pod-agent", job="j-pod-agent", minutes=23, kind="podcast")
        _session(db, ws, other, "s-their-earlier", title="以前的语音", kind="speech", minutes=24)
        _job(db, ws, "j-their-board", "tts", {"receipt": {"kind": "board_item", "board_id": "B"}}, minutes=24, by=other)
        _record(db, ws, "s-their-earlier", "r-their-board", job="j-their-board", minutes=24, kind="speech")
        #: 标题碰巧一样、种类对不上的不是那两条(那两条是「以前的语音」= 语音、「以前的播客」= 播客)
        db.add(GenerationSession(id="s-named-like-it", workspace_id=ws, owner_user_id=me, title="以前的语音", kind="image",
                                 origin_kind="studio"))
        db.commit()
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(text(
            "INSERT INTO provider_profiles (id, owner_user_id, name, vendor, base_url, auth_type, extra, enabled, "
            "plugin_instance_id, created_at, updated_at) VALUES ('pc', '', 'ComfyUI', 'plugin:x', '', 'api_key', '{}', 1, "
            "'C', '2026-09-01', '2026-09-01')"
        ))
        conn.execute(text("UPDATE generation_jobs SET provider_profile_id = 'pc' WHERE id = 'r-workbench'"))

    backfill()
    resort()
    once = _origins()
    backfill()
    resort()
    assert _origins() == once, "跑两遍和一遍不一样"

    expected = {
        "s-board": ("board", "B"),
        "s-workflow": ("workflow", "W"),
        "s-scheduled-workflow": ("workflow", "W2"),
        "s-schedule": ("schedule", "T"),
        "s-board-run": ("board", "B2"),
        "s-entity": ("entity", "E"),
        "s-agent": ("agent", "A"),
        "s-studio": ("studio", ""),
        "s-continued": ("board", "B"),
        "s-gone-agent": ("agent", "A2"),
        "s-gone-board": ("board", "B3"),
        "s-gone-two": ("studio", ""),
        "s-gone-unknown": ("studio", ""),
        "s-workbench": ("comfyui", "C/海报/封面.json"),
        "s-empty": ("studio", ""),
        "s-earlier-speech": ("audio_page", "speech"),
        "s-named-like-it": ("studio", ""),
    }
    assert {key: once[key][:2] for key in expected} == expected
    assert once["s-earlier-speech"][2] == "", "「以前的语音」标题空着:界面按读的人的语言写"
    assert once["s-board"][2] == "一张图", "老会话的标题不动(副标题写出处)"
    assert "s-earlier-podcast" not in once, "挪空了的「以前的播客」删掉"

    with SessionLocal() as db:
        where = {row.id: row.session_id for row in db.scalars(select(GenerationJob))}
        assert where["r-j-speak-board"] == "s-continued", "挪进那个人在那块画板上**最近用过的**那条"
        assert where["r-j-speak-agent"] == "s-agent"
        assert where["r-j-speak-note"] == "s-earlier-speech", "查不到出处的留在原地"
        made = db.get(GenerationSession, where["r-pod-agent"])
        assert (made.origin_kind, made.origin_id, made.title, made.owner_user_id, made.kind) == ("agent", "A9", "", me, "podcast")
        theirs = db.get(GenerationSession, where["r-their-board"])
        assert (theirs.origin_kind, theirs.origin_id, theirs.owner_user_id) == ("board", "B", other), "同事的进同事自己的那条"
        assert db.get(Job, "j-speak-board").payload["session_id"] == "s-continued", "任务中心「前往」跟着去新的那条"
        continued = db.get(GenerationSession, "s-continued")
        assert continued.kind == "speech", "会话记着最后一条的种类"
        assert continued.updated_at >= T0 + timedelta(minutes=20)


def test_老库加上出处两列和索引_老会话默认是创作页开的_跑两遍和一遍一样() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        _session(db, ws, db.scalars(select(User).order_by(User.created_at)).first().id, "s-old")
        db.commit()
    #: 退回加列之前的形状:没有这两列、没有索引
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS idx_generation_sessions_origin"))
        conn.execute(text("ALTER TABLE generation_sessions DROP COLUMN origin_kind"))
        conn.execute(text("ALTER TABLE generation_sessions DROP COLUMN origin_id"))

    add_columns()
    add_columns()
    with engine.connect() as conn:
        columns = {row[1]: row for row in conn.execute(text("PRAGMA table_info(generation_sessions)"))}
        indexes = {row[1] for row in conn.execute(text("PRAGMA index_list(generation_sessions)"))}
        old = conn.execute(text("SELECT origin_kind, origin_id FROM generation_sessions WHERE id = 's-old'")).one()
    assert {"origin_kind", "origin_id"} <= set(columns)
    assert "idx_generation_sessions_origin" in indexes
    assert tuple(old) == ("studio", ""), "老会话加列之后默认是创作页开的,由下一步按事实改"
