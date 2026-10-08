"""数字人的授权在生成漏斗里拦(ADR 0028 §5)。

此前只有工作流的「让它说话 / 对口型」节点、画板和资产详情页查授权;AI 工作台和智能体直接调说话照片、对口型模型时
一道都没有。现在凡是带驱动音频(`driving_audio` 素材或 `driving_audio_url` 链接)的生成,调用方不声明
`digital_human_consent` 就在漏斗入口拒 —— 在解析模型、传素材、渲参考这些花时间花钱的事之前。
"""

from __future__ import annotations

from app.domain.generation.origins import STUDIO_ORIGIN
import pytest

from app.core.db import SessionLocal
from app.domain.agent.confirmable.generation import _validate_generate_video
from app.domain.agent.errors import ConfirmationError
from app.domain.generation import create_generation_job
from app.domain.generation.operations import GenerationDomainError, is_digital_human_request
from tests.util import fresh_client

TALKING = [{"asset_id": "face", "role": "first_frame"}, {"asset_id": "line", "role": "driving_audio"}]


def _submit(ws: str, *, sources: list[dict], parameters: dict | None = None, consent: bool = False):
    with SessionLocal() as db:
        return create_generation_job(
            db, origin=STUDIO_ORIGIN, workspace_id=ws, session_id=None, project_id=None, created_by=None,
            provider="nobody", model="no-such-model", kind="video", prompt="", negative_prompt="",
            parameters=parameters or {}, source_assets=sources, digital_human_consent=consent,
        )


def test_认数字人_按驱动音频的素材或链接() -> None:
    assert is_digital_human_request(TALKING, {})
    assert is_digital_human_request([], {"driving_audio_url": "https://x/line.wav"})
    assert not is_digital_human_request([{"asset_id": "face", "role": "first_frame"}], {"driving_audio_url": " "})


def test_没声明授权_漏斗入口就拒() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    for sources, parameters in ((TALKING, {}), ([], {"driving_audio_url": "https://x/line.wav"})):
        with pytest.raises(GenerationDomainError) as refused:
            _submit(ws, sources=sources, parameters=parameters)
        assert refused.value.key == "genErr_digitalHumanNeedsConsent"


def test_声明了授权_过了这一道_往下照常校验() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with pytest.raises(GenerationDomainError) as later:
        _submit(ws, sources=TALKING, consent=True)
    assert later.value.key != "genErr_digitalHumanNeedsConsent", "拒它的是后面那几道(这里是模型不存在),不是授权"


def test_不是数字人_不问授权() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with pytest.raises(GenerationDomainError) as later:
        _submit(ws, sources=[{"asset_id": "face", "role": "first_frame"}])
    assert later.value.key != "genErr_digitalHumanNeedsConsent"


def test_AI工作台的接口_不勾授权回_422() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    res = client.post("/api/generation/jobs", json={
        "workspace_id": ws, "provider": "nobody", "model": "no-such-model", "kind": "video",
        "source_assets": TALKING,
    })
    assert res.status_code == 422, res.text
    assert "授权" in res.json()["detail"] or "consent" in res.json()["detail"]


def test_智能体开卡时就说_不等批准之后() -> None:
    fresh_client()
    with SessionLocal() as db:
        with pytest.raises(ConfirmationError) as refused:
            _validate_generate_video(db, "ws", {"source_assets": TALKING}, None)
        assert refused.value.key == "genErr_digitalHumanNeedsConsent"
