"""数字人的描述符规则(ADR 0028 §2):按素材自身时长的上下限,以及三个新键在自定义描述符白名单里。"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.db.models import Asset
from app.domain.generation.operations import GenerationDomainError, _validate_source_assets
from tests.util import fresh_client

RULES = {"source_duration_seconds": {"driving_audio": [2, 20], "source_video": [2, 120]}}


def _audio(ws: str, asset_id: str, duration: float | None) -> None:
    with SessionLocal() as db:
        db.add(Asset(id=asset_id, workspace_id=ws, kind="audio", name=f"{asset_id}.mp3", file_key="",
                     media_info={"duration": duration} if duration is not None else {}))
        db.commit()


def test_驱动音频超出这个模型的时长_提交那一刻说人话_不建注定失败的任务() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    _audio(ws, "long", 72)
    _audio(ws, "short", 1.2)
    _audio(ws, "fine", 12.5)
    _audio(ws, "unknown", None)
    with SessionLocal() as db:
        for asset_id, said in (("long", "72 秒"), ("short", "1.2 秒")):
            with pytest.raises(GenerationDomainError) as caught:
                _validate_source_assets(db, ws, [{"asset_id": asset_id, "role": "driving_audio"}], RULES, owner_user_id=None)
            assert caught.value.key == "genErr_sourceDurationRange"
            assert said in str(caught.value) and "2–20 秒" in str(caught.value), "说得出多长、这个模型收多长"
        #: 在范围里的、读不出时长的(不猜)、没声明上限的角色都放行。
        _validate_source_assets(db, ws, [{"asset_id": "fine", "role": "driving_audio"}], RULES, owner_user_id=None)
        _validate_source_assets(db, ws, [{"asset_id": "unknown", "role": "driving_audio"}], RULES, owner_user_id=None)
        _validate_source_assets(db, ws, [{"asset_id": "long", "role": "reference_audio"}], RULES, owner_user_id=None)


def test_三个新键进了自定义描述符的白名单() -> None:
    from app.domain.generation.custom_profiles import _FIELD_GROUPS, _KNOWN_KEYS

    for key in ("duration_follows", "source_duration_seconds", "truncates_role"):
        assert key in _KNOWN_KEYS and key in _FIELD_GROUPS, key
