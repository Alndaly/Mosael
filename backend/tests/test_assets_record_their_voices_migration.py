"""素材记下自己用到的克隆嗓子(`assets.voices`)的那条迁移(ADR 0093)。

旧形状:只有配音产出的 `media_info.voice_id` 记着一把,截取、拼接出来的派生素材什么都没记。
迁移之后:每份素材的 `voices` = 自己记的那把 ∪ 全部出处的(顺着来源链往下传),`media_info.voice_id` 去掉;再跑一次什么都不变。
"""

from __future__ import annotations

import json

from sqlalchemy import text

from app.core.db import engine
from app.db.migrations import _create_current_schema, _migrate_assets_record_their_voices
from tests.util import fresh_client, insert_asset


def _row(asset_id: str) -> tuple[list[str], dict]:
    with engine.begin() as conn:
        voices, info = conn.execute(text("SELECT voices, media_info FROM assets WHERE id = :i"), {"i": asset_id}).one()
    return json.loads(voices), json.loads(info)


def test_old_voice_ids_move_to_voices_and_flow_down_the_lineage() -> None:
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    wang = insert_asset(ws, kind="audio", name="老王配音", media_info={"duration": 3.0, "voice_id": "wang"})
    li = insert_asset(ws, kind="audio", name="小李配音", media_info={"voice_id": "li"})
    plain = insert_asset(ws, kind="audio", name="上传的")
    cut = insert_asset(ws, kind="audio", name="截一段")
    joined = insert_asset(ws, kind="audio", name="拼一段")
    padded = insert_asset(ws, kind="audio", name="补静音")
    lineage = {cut: [wang], joined: [cut, li, plain], padded: [joined]}
    #: 升级前的形状:没有 voices 列,出处写在 derived_from 里。
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE assets DROP COLUMN voices"))
        for child, parents in lineage.items():
            conn.execute(text("UPDATE assets SET derived_from = :d WHERE id = :i"),
                         {"d": json.dumps([{"asset_id": one, "op": "trim"} for one in parents]), "i": child})

    _migrate_assets_record_their_voices()
    _create_current_schema()

    assert _row(wang) == (["wang"], {"duration": 3.0})
    assert _row(li)[0] == ["li"] and _row(plain)[0] == []
    assert _row(cut)[0] == ["wang"], "截出来的一段继承出处的嗓子"
    assert _row(joined)[0] == ["li", "wang"], "拼起来的继承全部出处的,不止同一把的情形"
    assert _row(padded)[0] == ["li", "wang"], "隔两级也传得下去"
    with engine.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM assets WHERE json_extract(media_info, '$.voice_id') IS NOT NULL")).scalar() == 0

    _migrate_assets_record_their_voices()
    assert _row(padded)[0] == ["li", "wang"] and _row(wang) == (["wang"], {"duration": 3.0})
