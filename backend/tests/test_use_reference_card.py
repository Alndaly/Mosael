"""智能体从参考库取一条进来要开卡(use_reference,ADR 0091 §6):取用是「由人发起」的,卡就是那一下。

钉三件事:卡上说清取的是哪一张、出自谁、要不要存成资产;别人的 / 不存在的连接开卡前就拒;批准之后走的是
`reference_library.use`(出处随素材写进去),交回素材和资产 id。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.db import SessionLocal
from app.core.i18n import render_message
from app.domain.agent.confirmable import references
from app.domain.agent.confirmable.registry import tool_spec
from app.domain.agent.errors import ConfirmationError

ITEM = {"id": "full_single_P001", "collection": "poses", "kind": "pose",
        "name": {"zh": "后仰坐・单膝立起", "en": "Reclining sit"}, "tags": [], "views": [], "thumbnail": "",
        "nsfw": False, "provenance": {"author": "ギア (@giaaibusi)", "url": "https://example.test/", "license": "仅供参考"}}


@pytest.fixture
def library(monkeypatch: pytest.MonkeyPatch):
    owned = SimpleNamespace(id="conn-1", name="PoseAtlas")
    calls: list[dict] = []
    monkeypatch.setattr(references.inst, "owned",
                        lambda db, instance_id, user_id: owned if (instance_id, user_id) == ("conn-1", "me") else None)
    monkeypatch.setattr(references.reference_library, "item", lambda db, instance, **kwargs: ITEM)

    def use(db, user, instance, **kwargs):
        calls.append(kwargs)
        return {"asset_id": "a1", "asset_ids": ["a1"], "entity_id": "e1" if kwargs["save_entity"] else "", "item": ITEM,
                "provenance": {"instance_id": instance.id, **ITEM["provenance"]}}

    monkeypatch.setattr(references.reference_library, "use", use)
    return calls


def test_卡上说清取哪一张_出自谁_存不存成资产(library) -> None:
    spec = tool_spec("use_reference")
    assert spec is not None and spec.permission == "edit" and set(spec.writes) == {"assets", "entities"}
    payload = {"connection_id": "conn-1", "item_id": ITEM["id"], "collection": "poses", "save_as_asset": True}
    with SessionLocal() as db:
        spec.validate(db, "ws", payload, "me")
        key, params = spec.summarize(db, payload)
    assert key == "confirm_useReferenceAsAsset"
    text = render_message(key, "zh", params)
    assert "后仰坐・单膝立起" in text and "PoseAtlas" in text and "giaaibusi" in text and "姿势" in text

    payload["save_as_asset"] = False
    with SessionLocal() as db:
        assert spec.summarize(db, payload)[0] == "confirm_useReference"


def test_别人的或不存在的连接开卡前就拒(library) -> None:
    spec = tool_spec("use_reference")
    with SessionLocal() as db, pytest.raises(ConfirmationError):
        spec.validate(db, "ws", {"connection_id": "conn-1", "item_id": ITEM["id"]}, "someone-else")


def test_批准之后走参考库的取用_交回素材和资产(library, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = tool_spec("use_reference")
    monkeypatch.setattr(references, "User", SimpleNamespace)
    confirmation = SimpleNamespace(workspace_id="ws", payload={
        "connection_id": "conn-1", "item_id": ITEM["id"], "collection": "poses", "save_as_asset": True})

    class _Db:
        def get(self, model, key):
            return SimpleNamespace(id=key)

    result = spec.execute(_Db(), confirmation, "me")

    assert result["asset_id"] == "a1" and result["entity_id"] == "e1"
    assert library == [{"workspace_id": "ws", "item_id": ITEM["id"], "collection": "poses", "role": "", "save_entity": True}]
