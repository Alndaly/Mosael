"""模型目录里声明了默认值的参数，请求里照发 —— 不省掉、让服务商按它自己的默认来。

隔离环境里用「模特上身图」模板按 Evolink 默认模型建图：出图节点没带画质，视频节点没带 generate_audio。
AI 工作台的表单会把声明的默认值预填上，可工作流、画板、智能体从同一个漏斗(create_generation_job)进来时
什么都不补:gpt-image-2 于是落在服务商的 medium(目录声明的、也是我们定的默认是最便宜的 low),Seedance
落在服务商默认的有声 —— 而记账按请求里的参数估价，请求里没有 generate_audio 就按无声估。
"""

from __future__ import annotations

from app.domain.generation.origins import STUDIO_ORIGIN
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import ProviderProfile, User
from app.domain.generation.operations import create_generation_job
from app.domain.providers import models as provider_models
from tests.util import fresh_client


def _evolink(models: dict[str, list[str]]) -> tuple[str, str, str]:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    profile_id = client.post(
        "/api/settings/providers",
        json={"vendor": "evolink", "name": "Evolink", "api_key": "sk-test", "base_url": "http://127.0.0.1:1"},
    ).json()["id"]
    client.put(f"/api/settings/providers/{profile_id}/credential", json={"api_key": "sk-test"})
    with SessionLocal() as db:
        profile = db.get(ProviderProfile, profile_id)
        for model, capability_ids in models.items():
            provider_models.upsert(db, profile, model, source="manual", capability_ids=capability_ids)
        db.commit()
        user_id = db.scalars(select(User).order_by(User.created_at)).first().id
    return ws, profile_id, user_id


def _sent(ws: str, profile_id: str, user_id: str, *, model: str, kind: str, parameters: dict) -> dict:
    with SessionLocal() as db:
        generation, _job = create_generation_job(
            db, origin=STUDIO_ORIGIN, workspace_id=ws, session_id=None, project_id=None, created_by=user_id,
            provider="evolink", provider_profile_id=profile_id, model=model, kind=kind,
            prompt="一只橘猫坐在窗台上", negative_prompt="", parameters=parameters, source_assets=[],
        )
        db.commit()
        return dict(generation.request["parameters"])


def test_出图没给画质_照目录声明的默认发_low() -> None:
    ws, profile_id, user_id = _evolink({"gpt-image-2": ["image"]})
    sent = _sent(ws, profile_id, user_id, model="gpt-image-2", kind="image", parameters={"size": "9:16"})
    assert sent["quality"] == "low", sent
    assert sent["resolution"] == "1K", sent
    assert sent["size"] == "9:16", "给了的照旧"


def test_视频没给_generate_audio_照目录声明的默认发() -> None:
    ws, profile_id, user_id = _evolink({"seedance-2.5-text-to-video": ["video"]})
    sent = _sent(ws, profile_id, user_id, model="seedance-2.5-text-to-video", kind="video",
                 parameters={"duration_seconds": 4, "resolution": "480p"})
    assert sent["generate_audio"] is True, sent
    assert sent["duration_seconds"] == 4 and sent["resolution"] == "480p", "给了的照旧"


def test_给了的值不被默认值盖掉_空着的格子算没给() -> None:
    """模板里 `{{input.resolution}}` 没接上时插值成空串:那是没填，照默认补;明说了关声音就是关。"""
    ws, profile_id, user_id = _evolink({"seedance-2.5-text-to-video": ["video"]})
    sent = _sent(ws, profile_id, user_id, model="seedance-2.5-text-to-video", kind="video",
                 parameters={"generate_audio": False, "resolution": ""})
    assert sent["generate_audio"] is False, sent
    assert sent["resolution"] == "720p", sent
