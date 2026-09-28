"""「本次提供的素材:参考图 1 = 创作者.png; …」由生成漏斗补,不再拼进用户写的那句话。

画板此前在前端把这段对照拼进提示词再提交,于是生成记录里存的是拼过的字,AI 工作台的用户气泡原样画出来
(连「首帧 1 = 上一张生成图的素材名」一起)。现在画板只说「要对照」(`name_sources`),漏斗按素材自己的名字
和这次请求的语言写这一段,记进 `prompt_notes`;交给供应商时由 `prompt_for_provider` 接上,模型收到的不变。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.core.i18n import DEFAULT_LOCALE, set_current_locale
from app.domain.generation import create_generation_job
from app.domain.generation.operations import prompt_for_provider
from tests.test_entity_generation_paths import _board_with_entity_cell, _entity, _spy_generation, _seedance, _workspace
from tests.util import fresh_client, seed_assets


@pytest.fixture(autouse=True)
def _external(monkeypatch) -> None:
    """只看漏斗写下了什么,不真的跑。"""
    from app.domain import jobs as jobs_bus

    monkeypatch.setattr(jobs_bus, "_EXECUTION_MODES", {**jobs_bus._EXECUTION_MODES, "ai_generation": "external"})


def _create(ws: str, profile: str, prompt: str, *, name_sources: bool) -> dict:
    with SessionLocal() as db:
        generation, _job = create_generation_job(
            db, workspace_id=ws, session_id=None, project_id=None, created_by=None, provider="bytedance",
            provider_profile_id=profile, model="doubao-seedance-2-0-260128", kind="video", prompt=prompt,
            negative_prompt="", parameters={},
            source_assets=[
                {"asset_id": "创作者.png", "role": "reference_image"},
                {"asset_id": "街景.jpg", "role": "reference_image"},
            ],
            name_sources=name_sources,
        )
        return dict(generation.request)


def test_对照记在补充里_记录上只有用户写的那句() -> None:
    client = fresh_client()
    ws = _workspace(client)
    seed_assets(ws, {"创作者.png": "image", "街景.jpg": "image"})
    profile = _seedance(client)

    request = _create(ws, profile, "把 创作者.png 里的人放到 街景.jpg", name_sources=True)
    assert request["prompt"] == "把 创作者.png 里的人放到 街景.jpg"
    assert request["prompt_notes"] == ["本次提供的素材:参考图 1 = 创作者.png; 参考图 2 = 街景.jpg"]
    # 模型收到的和此前前端拼出来的一字不差。
    assert prompt_for_provider(request) == (
        "把 创作者.png 里的人放到 街景.jpg\n\n本次提供的素材:参考图 1 = 创作者.png; 参考图 2 = 街景.jpg"
    )


def test_按这次请求的语言写() -> None:
    client = fresh_client()
    ws = _workspace(client)
    seed_assets(ws, {"创作者.png": "image", "街景.jpg": "image"})
    profile = _seedance(client)
    set_current_locale("en")
    try:
        request = _create(ws, profile, "put them together", name_sources=True)
    finally:
        set_current_locale(DEFAULT_LOCALE)
    assert request["prompt_notes"] == [
        "Materials provided with this request:reference image 1 = 创作者.png; reference image 2 = 街景.jpg"
    ]


def test_没要对照就不写() -> None:
    client = fresh_client()
    ws = _workspace(client)
    seed_assets(ws, {"创作者.png": "image", "街景.jpg": "image"})
    profile = _seedance(client)
    assert "prompt_notes" not in _create(ws, profile, "一段街景", name_sources=False)


def test_画板生成要对照() -> None:
    client = fresh_client()
    ws = _workspace(client)
    board_id = _board_with_entity_cell(client, ws, _entity(ws, "张三", "", []))
    assert _spy_generation(client, ws, board_id, {})["name_sources"] is True


def test_没有补充时_交给供应商的就是原样() -> None:
    assert prompt_for_provider({"prompt": "  一只猫 "}) == "  一只猫 "
    assert prompt_for_provider({"prompt": "", "prompt_notes": ["张三: 黑色短发"]}) == "张三: 黑色短发"
