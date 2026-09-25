"""模板库里的「运行前需要」:每一条说得出**这台机器上齐没齐**。

此前前置条件只是一串句子,界面给每一句配同一个勾 —— 「AI 对话模型」旁边的勾和「待整理的
视频素材」旁边的勾长得一样,而用户什么都还没配。勾在说"齐了",其实只是"这是一条"。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.domain.workflows import template_requirements as req
from app.domain.workflows.templates import TEMPLATE_CATALOG
from tests.util import add_provider, fresh_client, second_client


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def test_每条前置条件的检查键都查得了() -> None:
    """目录里写了一个查不了的键,界面就会永远显示「还不知道」—— 而那不是真话。"""
    used = {one["check"] for card in TEMPLATE_CATALOG for one in card["requires"] if one["check"]}
    assert used <= set(req.CHECKS)
    assert used, "目录里一条能自动查的前置条件都没有 —— 这道测试真空通过了"


def test_未知的检查键在写目录时就挡住() -> None:
    with pytest.raises(ValueError):
        req.requirement("gpu", zh="显卡", en="GPU")


def test_目录接口把检查键和可选标记一起发下去() -> None:
    client = fresh_client()
    templates = client.get("/api/workflows/templates").json()
    full = next(one for one in templates if one["id"] == "full_video_generation")
    assert full["requirements"][0] == {"text": "AI 对话模型", "check": "chat_model", "optional": False}
    narration = full["requirements"][-1]
    assert narration["check"] == "cloned_voice" and narration["optional"] is True
    cleanup = next(one for one in templates if one["id"] == "transcript_video_cleanup")
    #: 素材是跑的时候才给的,查不了 —— 检查键留空,而不是假装它齐了。
    assert cleanup["requirements"][-1]["check"] == ""


def test_什么都没配时说缺_配了之后说齐(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ai.runtime import asr_models, separation_models

    #: 引擎探测:转写测过了、跑得起来;分离还没测出来 —— 「不知道」不能被说成「缺」。
    monkeypatch.setattr(asr_models, "runtime_status", lambda engine: (engine == "funasr", True))
    monkeypatch.setattr(separation_models, "runtime_status", lambda engine: (False, False))

    client = fresh_client()
    workspace_id = _workspace(client)
    before = {row["check"]: row["status"] for row in client.get(
        "/api/workflows/templates/checks", params={"workspace_id": workspace_id},
    ).json()}
    assert set(before) == set(req.CHECKS)
    assert before["chat_model"] == "missing"
    assert before["cloned_voice"] == "missing"
    assert before["transcription_engine"] == "met"
    assert before["separation_engine"] == "unknown"

    with SessionLocal() as db:
        add_provider(
            db, name="对话", vendor="deepseek", base_url="http://b/v1",
            api_key="k", model="deepseek-chat", capability_ids=["chat"],
        )
        db.commit()
    after = {row["check"]: row["status"] for row in client.get(
        "/api/workflows/templates/checks", params={"workspace_id": workspace_id},
    ).json()}
    assert after["chat_model"] == "met"


def test_别人的工作区查不了() -> None:
    owner = fresh_client("owner")
    workspace_id = _workspace(owner)
    stranger = second_client("stranger")
    response = stranger.get("/api/workflows/templates/checks", params={"workspace_id": workspace_id})
    assert response.status_code in (403, 404)
