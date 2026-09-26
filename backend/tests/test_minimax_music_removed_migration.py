"""`remove-minimax-music-models`:MiniMax 音乐撤掉(ADR 0022 的补充),存着的指向清干净。

喂它一份撤掉之前的样子 —— MiniMax 连接下的三个音乐模型行(其中一个是音频默认模型、带参数声明和价格规则)、
同一条连接上的海螺视频模型、别的连接上指向 `minimax-music` 档案的模型行、AI 工作台的会话、画板上的生成格、
工作流节点(连同循环体)、定时任务、生成历史 —— 看它删掉 / 清掉该清的、别的一样不碰,再跑一次什么都不动。
"""

from __future__ import annotations

import json

from sqlalchemy import select, text

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_workflow_revisions
from app.db.migrations import _remove_minimax_music_models as migrate
from app.db.models import (
    Board,
    GenerationCapabilityDeclaration,
    GenerationJob,
    GenerationSession,
    Job,
    ProviderDefault,
    ProviderModel,
    ProviderPricingRule,
    ProviderProfile,
    ScheduledTask,
    Workflow,
    WorkflowRevision,
    WorkflowRevisionAttestation,
)
from app.domain.workflows.revisions import current_workflow_revision
from tests.util import fresh_client, second_client, user_id


def _node(node_id: str, **config) -> dict:
    return {"id": node_id, "type": "ai_generate", "position": {"x": 0, "y": 0},
            "config": {"kind": "audio", "prompt": "夏夜城市流行", **config}}


def _legacy(client) -> dict:
    me, mate = user_id("tester"), user_id("mate")
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    board_id = client.post("/api/boards", json={"workspace_id": workspace, "name": "B"}).json()["id"]
    workflow_id = client.post("/api/workflows", json={"workspace_id": workspace, "name": "WF"}).json()["id"]
    with SessionLocal() as db:
        minimax = ProviderProfile(owner_user_id=me, name="MiniMax", vendor="minimax", base_url="",
                                  auth_type="api_key", extra={}, enabled=True)
        relay = ProviderProfile(owner_user_id=me, name="中转", vendor="openai-compatible", base_url="https://relay",
                                auth_type="api_key", extra={}, enabled=True)
        db.add_all([minimax, relay])
        db.flush()
        song = ProviderModel(provider_profile_id=minimax.id, model_id="music-3.0", capability_ids=["audio"])
        older = ProviderModel(provider_profile_id=minimax.id, model_id="music-2.6", capability_ids=["audio"])
        cover = ProviderModel(provider_profile_id=minimax.id, model_id="music-cover", capability_ids=["audio"],
                              generation_capability_ref="profile:minimax-music-cover")
        hailuo = ProviderModel(provider_profile_id=minimax.id, model_id="MiniMax-Hailuo-2.3", capability_ids=["video"])
        # 中转上一个同名的模型:它不是 MiniMax 连接,不归这次撤掉;只是它指着的那份档案没了
        alias = ProviderModel(provider_profile_id=relay.id, model_id="music-3.0", capability_ids=["audio"],
                              generation_capability_ref="profile:minimax-music")
        pointer = ProviderModel(provider_profile_id=relay.id, model_id="my-song", capability_ids=["audio"])
        db.add_all([song, older, cover, hailuo, alias, pointer])
        db.flush()
        db.add(GenerationCapabilityDeclaration(provider_model_id=song.id, kind="audio", catalog_ref="profile:minimax-music"))
        db.add(GenerationCapabilityDeclaration(provider_model_id=pointer.id, kind="audio",
                                               catalog_ref="model:minimax/music-3.0"))
        db.add(ProviderDefault(capability="audio", owner_user_id=me, provider_model_id=song.id))
        db.add(ProviderDefault(capability="video", owner_user_id=me, provider_model_id=hailuo.id))
        db.add(ProviderPricingRule(provider="minimax", provider_profile_id=minimax.id, capability="audio",
                                   model="music-3.0", billing_unit="audio", unit_amount_micros=1))
        db.add(ProviderPricingRule(provider="minimax", provider_profile_id=minimax.id, capability="video",
                                   model="MiniMax-Hailuo-2.3", billing_unit="video", unit_amount_micros=2))
        db.add(GenerationSession(workspace_id=workspace, title="写歌", provider_profile_id=minimax.id,
                                 model="music-3.0", kind="audio", owner_user_id=me))
        db.add(GenerationSession(workspace_id=workspace, title="出片", provider_profile_id=minimax.id,
                                 model="MiniMax-Hailuo-2.3", kind="video", owner_user_id=me))
        request = {"prompt": "夏夜", "parameters": {"lyrics": "[Verse] 啦"}}
        job = Job(workspace_id=workspace, kind="ai_generation", status="succeeded", created_by=me,
                  payload={"provider": "minimax", "provider_profile_id": minimax.id, "model": "music-3.0",
                           "kind": "audio", "request": request})
        db.add(job)
        db.flush()
        db.add(GenerationJob(workspace_id=workspace, job_id=job.id, provider_profile_id=minimax.id, provider="minimax",
                             model="music-3.0", kind="audio", request=request))
        db.add(ScheduledTask(workspace_id=workspace, owner_user_id=me, name="每天一首", kind="generation",
                             trigger_type="interval", enabled=True,
                             payload={"provider": "minimax", "provider_profile_id": minimax.id, "model": "music-2.6",
                                      "kind": "audio", "prompt": "lofi"}))
        db.add(ScheduledTask(workspace_id=workspace, owner_user_id=me, name="每天一段", kind="generation",
                             trigger_type="interval", enabled=True,
                             payload={"provider": "minimax", "provider_profile_id": minimax.id,
                                      "model": "MiniMax-Hailuo-2.3", "kind": "video", "prompt": "海"}))
        board = db.get(Board, board_id)
        board.canvas = {"items": [
            {"id": "a1", "kind": "audio", "x": 0, "y": 0,
             "form": {"prompt": "夏夜", "provider_profile_id": minimax.id, "model": "music-cover",
                      "parameters": {"lyrics": "[Verse] 啦"}}},
            {"id": "v1", "kind": "video", "x": 0, "y": 0,
             "form": {"prompt": "海", "provider": "minimax", "provider_profile_id": minimax.id,
                      "model": "MiniMax-Hailuo-2.3"}},
        ]}
        db.commit()
        ids = {"minimax": minimax.id, "song": song.id, "hailuo": hailuo.id, "alias": alias.id, "pointer": pointer.id,
               "board": board_id, "workflow": workflow_id, "board_revision": board.revision, "job": job.id}
    graph = {"nodes": [
        _node("top", provider="minimax", provider_profile_id=ids["minimax"], model="music-3.0",
              parameters={"instrumental": True}),
        {"id": "loop", "type": "loop", "position": {"x": 0, "y": 0}, "config": {"body": {"nodes": [
            _node("inner", provider="minimax", model="music-cover"),
        ], "edges": []}}},
        _node("other", provider="google", model="lyria-3.5"),
    ], "edges": []}
    with engine.begin() as conn:
        conn.execute(text("UPDATE workflows SET graph = :g WHERE id = :id"),
                     {"g": json.dumps(graph, ensure_ascii=False), "id": workflow_id})
    _migrate_workflow_revisions()
    with SessionLocal() as db:
        latest = current_workflow_revision(db, db.get(Workflow, workflow_id))
        latest.created_by = me
        db.add(WorkflowRevisionAttestation(revision_id=latest.id, user_id=mate))
        db.commit()
        ids["revisions"] = db.query(WorkflowRevision).filter_by(workflow_id=workflow_id).count()
    return ids


def test_MiniMax音乐的模型行与引用清干净_别的不碰_再跑一次什么都不动() -> None:
    client = fresh_client()
    second_client("mate")
    ids = _legacy(client)

    migrate()

    me = user_id("tester")
    with SessionLocal() as db:
        # 三个音乐模型行没了,海螺视频还在;中转上同名的那行不是 MiniMax 的,留着,只清掉它指着的已删档案
        remaining = {(row.provider_profile_id, row.model_id) for row in db.scalars(select(ProviderModel))}
        assert not {(ids["minimax"], one) for one in ("music-3.0", "music-2.6", "music-cover")} & remaining
        assert db.get(ProviderModel, ids["hailuo"]) is not None
        assert db.get(ProviderModel, ids["alias"]).generation_capability_ref is None
        assert db.scalars(select(GenerationCapabilityDeclaration)).all() == [], "指向已删模型 / 档案的声明都删了"
        # 默认模型:音频那一项置空 = 没设;视频那一项不动
        assert db.get(ProviderDefault, {"capability": "audio", "owner_user_id": me}).provider_model_id is None
        assert db.get(ProviderDefault, {"capability": "video", "owner_user_id": me}).provider_model_id == ids["hailuo"]
        assert [rule.model for rule in db.scalars(select(ProviderPricingRule))] == ["MiniMax-Hailuo-2.3"]

        sessions = {row.title: row for row in db.scalars(select(GenerationSession))}
        assert (sessions["写歌"].model, sessions["写歌"].provider_profile_id) == (None, None)
        assert (sessions["出片"].model, sessions["出片"].provider_profile_id) == ("MiniMax-Hailuo-2.3", ids["minimax"])

        tasks = {row.name: row for row in db.scalars(select(ScheduledTask))}
        assert tasks["每天一首"].enabled is False, "清掉模型的定时任务不能落到默认模型上悄悄换一家花钱"
        assert tasks["每天一首"].payload == {"kind": "audio", "prompt": "lofi"}
        assert tasks["每天一段"].enabled is True and tasks["每天一段"].payload["model"] == "MiniMax-Hailuo-2.3"

        # 画板:音乐格只清模型选择,提示词和歌词留着;视频格不动;revision 往前走
        board = db.get(Board, ids["board"])
        audio, video = board.canvas["items"]
        assert audio["form"] == {"prompt": "夏夜", "parameters": {"lyrics": "[Verse] 啦"}}
        assert video["form"]["model"] == "MiniMax-Hailuo-2.3"
        assert board.revision == ids["board_revision"] + 1

        # 工作流:连循环体一起清;别家的节点不动;追加一版修订,作者与认可人沿用上一版
        workflow = db.get(Workflow, ids["workflow"])
        top, loop, other = workflow.graph["nodes"]
        assert top["config"] == {"kind": "audio", "prompt": "夏夜城市流行", "parameters": {"instrumental": True}}
        assert loop["config"]["body"]["nodes"][0]["config"] == {"kind": "audio", "prompt": "夏夜城市流行"}
        assert (other["config"]["provider"], other["config"]["model"]) == ("google", "lyria-3.5")
        latest = current_workflow_revision(db, workflow)
        assert latest.graph == workflow.graph and latest.source == "migration" and latest.created_by == me
        attesters = {row.user_id for row in db.scalars(select(WorkflowRevisionAttestation).where(
            WorkflowRevisionAttestation.revision_id == latest.id))}
        assert attesters == {user_id("mate")}
        assert db.query(WorkflowRevision).filter_by(workflow_id=ids["workflow"]).count() == ids["revisions"] + 1

        # 历史是发生过的事:生成记录和任务回执原样
        assert db.scalars(select(GenerationJob)).one().model == "music-3.0"
        assert db.get(Job, ids["job"]).payload["model"] == "music-3.0"
        models = db.query(ProviderModel).count()

    migrate()
    with SessionLocal() as db:
        assert db.query(WorkflowRevision).filter_by(workflow_id=ids["workflow"]).count() == ids["revisions"] + 1
        assert db.get(Board, ids["board"]).revision == ids["board_revision"] + 1
        assert db.query(ProviderModel).count() == models


def test_没有MiniMax连接的库什么都不动() -> None:
    fresh_client()
    with engine.begin() as conn:
        before = conn.execute(text("SELECT COUNT(*) FROM provider_models")).scalar()
    migrate()
    with engine.begin() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM provider_models")).scalar() == before
