"""生成任务的 `payload.subject` 只放**用户自己写的那句**;没写就是空串。

只挂素材(或文档)、自己一个字没写的生成,此前 `subject` 会落成**喂给模型的那整段**
(`prompt_for_provider` 把文档、素材说明都接在后面),没有补充时再退化成模型名 ——
界面上的 `Truncate` 收得住布局,但落地数据里存的不是「用户要什么」。

展示层(回执卡 / 「本对话的后台任务」 / 任务中心)和给模型读的那句,在 subject 为空时
按**当前语言** + **任务种类** + **素材份数**自己说清「这是哪来的」;后端只存结构
(种类、份数),不在落库的字符串里带语言。
"""

from __future__ import annotations

import mcp_server

from app.core.db import SessionLocal
from app.core.i18n import speaking
from app.db.models import Job
from app.domain import jobs as jobs_bus
from app.domain.agent import receipts
from tests.util import add_provider, fresh_client, insert_asset

#: 只挂素材、没写提示词的生成:请求里就这几份素材(回执只带「几份」这个数,不带正文)。
TWO_ASSETS = [
    {"asset_id": "a", "role": "reference_image"},
    {"asset_id": "b", "role": "reference_image"},
]


def _external(monkeypatch) -> None:
    """只关心「建成什么样」,不真跑:标成 external,任务照常建好、线程不起。"""
    monkeypatch.setattr(
        jobs_bus, "_EXECUTION_MODES", {**jobs_bus._EXECUTION_MODES, "ai_generation": "external"}
    )


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _digital_human(client, workspace_id: str) -> tuple[str, str, str]:
    """一条数字人连接 + 它要的两份素材(一张人像、一段驱动音频)。

    挑它是因为它是**真的允许不写提示词**的内置模型(`prompt: optional`,ADR 0028):
    「只挂素材」这条路在真实目录里存在,不是测试编出来的形状。
    """
    face = insert_asset(
        workspace_id, kind="image", name="人像.png",
        media_info={"source_url": "https://cdn.example.com/face.jpg"},
    )
    voice = insert_asset(
        workspace_id, kind="audio", name="配音.mp3",
        media_info={"source_url": "https://cdn.example.com/voice.mp3", "duration": 6.0},
    )
    with SessionLocal() as db:
        profile = add_provider(
            db, name="火山数字人", vendor="volcano-visual", base_url="", api_key="k",
            model="omnihuman-1.5", capability_ids=["video"], make_default=False,
        )
        db.commit()
        profile_id = profile.id
    return face, voice, profile_id


def _submit(client, workspace_id: str, face: str, voice: str, profile_id: str, *, prompt: str) -> dict:
    response = client.post("/api/generation/jobs", json={
        "workspace_id": workspace_id,
        "provider_profile_id": profile_id,
        "provider": "volcano-visual",
        "model": "omnihuman-1.5",
        "kind": "video",
        "prompt": prompt,
        "source_assets": [
            {"asset_id": face, "role": "first_frame"},
            {"asset_id": voice, "role": "driving_audio"},
        ],
        "digital_human_consent": True,
    })
    assert response.status_code == 200, response.text
    return response.json()["job"]


def _job(payload: dict) -> Job:
    """一条已落终态的生成任务(不真写库:这里只看读它的那几句怎么拼)。"""
    return Job(
        id="job-1", workspace_id="w1", kind="ai_generation", status="failed",
        payload=payload, result={}, message="", error="", error_key="", error_params={},
    )


# ── ① 只挂素材、没写提示词:subject 是空串(先红:此前是一整篇) ─────────────────────


def test_只挂了两个素材没写提示词_subject留空_不塞喂给模型的拼装正文(monkeypatch) -> None:
    _external(monkeypatch)
    client = fresh_client()
    workspace_id = _workspace(client)
    face, voice, profile_id = _digital_human(client, workspace_id)

    payload = _submit(client, workspace_id, face, voice, profile_id, prompt="")["payload"]

    assert payload["subject"] == "", "没写提示词,subject 却落了东西 —— 那不是「用户要什么」"
    assert payload["request"]["prompt"] == ""
    #: 素材本身照旧记在请求里:展示层要从这里数「几份」,执行器也要用。
    assert payload["request"]["source_assets"] == [
        {"asset_id": face, "role": "first_frame"},
        {"asset_id": voice, "role": "driving_audio"},
    ]


# ── ② 写了提示词:subject 仍是完整原文,不回归 ───────────────────────────────────


def test_写了提示词的生成_subject仍是完整提示词(monkeypatch) -> None:
    _external(monkeypatch)
    client = fresh_client()
    workspace_id = _workspace(client)
    face, voice, profile_id = _digital_human(client, workspace_id)
    prompt = "一只在雨里等车的柴犬," * 30

    payload = _submit(client, workspace_id, face, voice, profile_id, prompt=prompt)["payload"]

    assert payload["subject"] == prompt, "有提示词时也不该收窄 —— 存的是他写的那一句的完整原文"


# ── ③ 回执的结构化事实 + 给模型读的那句 ─────────────────────────────────────────


def test_回执载荷带素材份数_subject不塞拼出来的正文() -> None:
    fresh_client()  # 干净库:receipt_payload 会去查这条生成记录
    job = _job({"subject": "", "request": {"prompt": "", "source_assets": TWO_ASSETS}})

    with SessionLocal() as db:
        facts = receipts.receipt_payload(db, job, subject=receipts._subject(job), asset_ids=[])

    assert facts["subject"] == ""
    #: 份数是**结构**,不是一句写死的话:出口(界面 / 给模型的那句)按当前语言自己拼。
    assert facts["source_asset_count"] == 2


def test_给模型读的那句_没提示词也按当前语言说清是哪来的() -> None:
    job = _job({"subject": "", "request": {"prompt": "", "source_assets": TWO_ASSETS}})

    with speaking("zh-CN"):
        assert "从 2 个素材 AI 生成" in receipts._summarize(job)
    with speaking("en-US"):
        assert "AI generation from 2 assets" in receipts._summarize(job)


def test_给模型读的那句_没有素材数时只说种类() -> None:
    job = _job({"subject": ""})

    with speaking("zh-CN"):
        summary = receipts._summarize(job)
    with speaking("en-US"):
        english = receipts._summarize(job)

    assert "「AI 生成」" in summary, summary
    assert "2 个素材" not in summary
    assert "「AI generation」" in english, english


def test_列任务给模型的简报_没提示词也说清是哪来的() -> None:
    job = {
        "id": "j", "kind": "ai_generation", "status": "succeeded", "progress": 1,
        "payload": {"subject": "", "request": {"prompt": "", "source_assets": TWO_ASSETS}},
        "result": {},
    }

    with speaking("zh-CN"):
        assert mcp_server._job_brief(job)["subject"] == "从 2 个素材 AI 生成"
    with speaking("en-US"):
        assert mcp_server._job_brief(job)["subject"] == "AI generation from 2 assets"


def test_列任务简报_没有素材数时只说种类而不是空() -> None:
    brief = mcp_server._job_brief(
        {"id": "j", "kind": "render", "status": "succeeded", "progress": 1, "payload": {}, "result": {}}
    )

    assert brief["subject"] == "导出", "给模型看的简报里,一条任务不能没有名字"
