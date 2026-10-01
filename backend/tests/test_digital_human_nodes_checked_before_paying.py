"""数字人系列节点做不了的事,在**任何节点花钱之前**说(executors.register_preflight)。

此前只有配音节点登记了运行前检查。「视频译配 · 改口型」排在转写、付费翻译、逐句配音之后:授权没勾、没有会改口型的
模型、配音用的是没声明的克隆音色 —— 都要等前面几步的钱花完,跑到改口型那一步才被拒。说话照片、对口型、人物说话、
长稿分段、挂了驱动音频的生成同理。

走真的入口(start_workflow_job → run_preflights),模型目录换成桩(哪些模型「这个人能用」是外部状态)。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import Asset, Entity, EntityReference, Job, Voice, Workflow
from app.domain.workflows import WorkflowDomainError, create_workflow
from app.domain.workflows.engine import start_workflow_job
from app.domain.workflows.executors import talking
from app.domain.workflows.templates import translated_dub_graph
from tests.util import fresh_client, make_voice, user_id

LIPSYNC = {"id": "p:video:videoretalk", "is_default": True, "capabilities": {"modes": ["video-lipsync"]}}
SPEAKING = {"id": "p:video:s2v", "is_default": True, "capabilities": {"modes": ["speech-to-video"]}}


@pytest.fixture
def workspace(monkeypatch) -> str:
    from app.domain.assets import separation

    monkeypatch.setattr(separation, "available", lambda *_a, **_k: True)
    monkeypatch.setattr(talking, "talking_models",
                        lambda db, mode, actor: [one for one in (LIPSYNC, SPEAKING) if mode in one["capabilities"]["modes"]])
    return fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]


def _start(workspace: str, graph: dict) -> None:
    with SessionLocal() as db:
        workflow = create_workflow(db, workspace_id=workspace, name="数字人", graph=graph, created_by=user_id())
        db.commit()
        start_workflow_job(db, db.get(Workflow, workflow.id), created_by=user_id())
        db.commit()


def _refused(workspace: str, graph: dict) -> str:
    with pytest.raises(WorkflowDomainError) as refused:
        _start(workspace, graph)
    with SessionLocal() as db:
        assert list(db.scalars(select(Job).where(Job.workspace_id == workspace))) == [], "一个节点都没排:转写、翻译、配音都没花钱"
    return refused.value.key


def _lipsync_dub(voice: str = "voice-a", engine: str = "builtin:volcano", consent: str = "yes") -> dict:
    graph = translated_dub_graph(voice_id="", lipsync=True)
    for node in graph["nodes"]:
        if node["id"] == "source_video":
            node["config"]["asset_id"] = "some-video"
        if node["id"] == "dubbing":
            node["config"].update(engine=engine, voice=voice)
        if node["id"] == "lip_sync":
            node["config"]["consent"] = consent
    return graph


def test_改口型译配_没有会改口型的模型_在转写之前就拒(workspace, monkeypatch) -> None:
    monkeypatch.setattr(talking, "talking_models", lambda db, mode, actor: [])
    assert _refused(workspace, _lipsync_dub()) == "wfErr_lipsyncNoModel"


def test_改口型译配_上游配音用的是没声明的克隆音色_在转写之前就拒(workspace) -> None:
    """改口型节点只接上游配好的那条轨 —— 嗓子在上游配音节点上,顺着图往上找。"""
    voice = make_voice(workspace, "老王的嗓子")
    assert _refused(workspace, _lipsync_dub(voice=voice, engine="builtin:clone")) == "wfErr_voiceConsentMissing"
    with SessionLocal() as db:
        db.get(Voice, voice).consent_kind = "self"
        db.commit()
    _start(workspace, _lipsync_dub(voice=voice, engine="builtin:clone"))


def _single(node: dict) -> dict:
    return {"nodes": [{"id": "start", "type": "start", "config": {}}, node],
            "edges": [{"id": "e1", "source": "start", "target": node["id"]}]}


def test_说话照片_脸是没声明的真人人物资产_配音之前就拒(workspace) -> None:
    with SessionLocal() as db:
        face = Asset(workspace_id=workspace, kind="image", name="小李.png")
        person = Entity(workspace_id=workspace, kind="character", name="小李", attributes={"real_person": True})
        db.add_all([face, person])
        db.flush()
        db.add(EntityReference(entity_id=person.id, asset_id=face.id, role="front"))
        db.commit()
        face_id = face.id
    node = {"id": "say", "type": "image_speak",
            "config": {"asset_id": face_id, "text": "你好", "engine": "builtin:volcano", "voice": "v", "consent": "yes"}}
    assert _refused(workspace, _single(node)) == "genErr_entityConsentMissing"


def test_对口型和长稿分段_字面量的克隆音色没声明就拒(workspace) -> None:
    voice = make_voice(workspace, "老王的嗓子")
    lipsync = {"id": "sync", "type": "video_lipsync",
               "config": {"asset_id": "v", "text": "你好", "engine": "builtin:clone", "voice": voice, "consent": "yes"}}
    assert _refused(workspace, _single(lipsync)) == "wfErr_voiceConsentMissing"
    segments = {"id": "seg", "type": "talking_segments", "config": {"text": "很长的稿子。", "engine": "builtin:clone", "voice": voice}}
    assert _refused(workspace, _single(segments)) == "wfErr_voiceConsentMissing"


def test_人物说话_没有本人或同意声明的真人_在花钱之前就拒(workspace) -> None:
    with SessionLocal() as db:
        person = Entity(workspace_id=workspace, kind="character", name="小李", attributes={"real_person": True})
        db.add(person)
        db.commit()
        person_id = person.id
    node = {"id": "say", "type": "entity_speak", "config": {"entity_id": person_id, "text": "你好"}}
    assert _refused(workspace, _single(node)) == "wfErr_entitySpeakNoConsent"


def test_生成节点挂了驱动音频_没勾授权就拒_授权是引用时留给运行时(workspace) -> None:
    """驱动音频常是上游的引用(`{{配音.asset_id}}:driving_audio`),角色写在模板里 —— 按原始配置认出这是数字人生成。"""
    from app.domain.workflows.executors import run_preflights

    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "tts", "type": "synthesize_speech", "config": {"text": "你好", "engine": "builtin:volcano", "voice": "v"}},
            {"id": "gen", "type": "ai_generate",
             "config": {"kind": "video", "provider": "p", "model": "s2v", "prompt": "",
                        "source_assets": "some-face:first_frame\n{{tts.asset_id}}:driving_audio", "consent": ""}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "tts"}, {"id": "e2", "source": "tts", "target": "gen"}],
    }
    with SessionLocal() as db, pytest.raises(WorkflowDomainError) as refused:
        run_preflights(db, graph, user_id(), workspace_id=workspace)
    assert refused.value.key == "wfErr_talkingNeedsConsent"

    graph["nodes"][2]["config"]["consent"] = "{{start.consent}}"
    with SessionLocal() as db:
        run_preflights(db, graph, user_id(), workspace_id=workspace)
