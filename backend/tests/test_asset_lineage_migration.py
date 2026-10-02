"""素材记出处那两条迁移,各喂一份老形状的数据。

- `migrate-assets-remember-where-they-came-from`:老的 assets 表补 derived_from / ai_generated 两列;
- `backfill-asset-lineage`:推得出的补上出处和「含 AI」(生成记录、合成来源、media_info 里各写各的出处、
  截取任务、导出任务),推不出的留空;再跑一次什么都不变。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import inspect, text

from app.core.db import SessionLocal, engine
from app.db.migrations import _backfill_asset_lineage, _migrate_assets_remember_where_they_came_from
from app.db.models import Asset, Clip, GeneratedAsset, GenerationJob, Job, Project, Sequence, Track
from tests.util import fresh_client


def _workspace() -> str:
    return fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]


def _columns() -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns("assets")}


def _table() -> dict[str, tuple]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, derived_from, ai_generated, media_info FROM assets")).all()
    return {row[0]: (json.loads(row[1]), bool(row[2]), json.loads(row[3])) for row in rows}


def test_老表补上两列_老数据不动_再跑一次什么都不做() -> None:
    ws = _workspace()
    with SessionLocal() as db:
        db.add(Asset(id="old", workspace_id=ws, kind="video", name="老素材", media_info={"duration": 3.0}))
        db.commit()
    with engine.begin() as conn:
        for column in ("derived_from", "ai_generated"):
            conn.execute(text(f"ALTER TABLE assets DROP COLUMN {column}"))
    engine.dispose()
    assert not {"derived_from", "ai_generated"} & _columns()

    _migrate_assets_remember_where_they_came_from()
    _migrate_assets_remember_where_they_came_from()
    engine.dispose()

    assert {"derived_from", "ai_generated"} <= _columns()
    assert _table()["old"] == ([], False, {"duration": 3.0})


def test_回填_推得出的补上_推不出的留空_含AI顺着出处往下传_重跑不变() -> None:
    ws = _workspace()
    start = datetime(2026, 9, 1)
    with SessionLocal() as db:
        project = Project(workspace_id=ws, name="P")
        db.add(project)
        db.flush()

        def asset(asset_id: str, minutes: int, *, source: str = "imported", media_info: dict | None = None) -> None:
            db.add(Asset(id=asset_id, workspace_id=ws, kind="video", name=asset_id, source=source,
                         media_info=media_info or {}, created_at=start + timedelta(minutes=minutes)))

        asset("plain", 0)
        asset("gen", 1, source="generated")  # 生成记录的第二张产出:只有 generated_assets 认得
        asset("cover", 2, source="generated")  # 生成记录的封面:result_asset_id
        asset("voice", 3, source="tts")
        asset("podcast", 4, source="podcast")
        asset("lipsync", 5, source="digital_human")
        asset("tile", 6, source="generated",
              media_info={"derived_from_asset_id": "gen", "derivation": "image_grid_split", "grid_cell": [1, 1]})
        asset("tile-gif", 7, source="generated", media_info={"derived_from_asset_id": "tile", "derivation": "video_to_gif"})
        asset("stem", 8, source="separated",
              media_info={"derived_from_asset_id": "plain", "derivation": "separate_audio", "stem": "vocals"})
        asset("strange", 9, media_info={"derived_from_asset_id": "gen", "derivation": "something_else"})
        asset("cut", 10, source="generated")
        asset("cut-failed", 11, source="generated")
        asset("export", 12, source="exported")
        asset("export-stale", 13, source="exported")
        db.flush()

        db.add(GenerationJob(id="g1", workspace_id=ws, provider="p", model="m", kind="image", result_asset_id="cover"))
        db.add(GeneratedAsset(asset_id="gen", provider="p", model="m", job_id="j"))
        db.add(GeneratedAsset(asset_id="cover", provider="p", model="m", job_id="j"))

        same = Sequence(workspace_id=ws, project_id=project.id, name="没改过", revision=3)
        edited = Sequence(workspace_id=ws, project_id=project.id, name="改过了", revision=5)
        db.add_all([same, edited])
        db.flush()
        for sequence, used in ((same, ("plain", "cut")), (edited, ("voice",))):
            track = Track(sequence=sequence, kind="video", name="V1", position=0)
            db.add(track)
            db.flush()
            for at, asset_id in enumerate(used):
                db.add(Clip(workspace_id=ws, sequence_id=sequence.id, track_id=track.id, asset_id=asset_id,
                            timeline_start=at, src_in=0, src_out=1))
        db.add_all([
            Job(workspace_id=ws, kind="trim", status="succeeded", payload={"asset_id": "voice"}, result={"asset_id": "cut"}),
            Job(workspace_id=ws, kind="trim", status="failed", payload={"asset_id": "gen"}, result={"asset_id": "cut-failed"}),
            Job(workspace_id=ws, kind="render", status="succeeded",
                payload={"sequence_id": same.id, "sequence_revision": 3}, result={"asset_id": "export"}),
            Job(workspace_id=ws, kind="render", status="succeeded",
                payload={"sequence_id": edited.id, "sequence_revision": 1}, result={"asset_id": "export-stale"}),
        ])
        db.commit()

    _backfill_asset_lineage()
    first = _table()
    _backfill_asset_lineage()
    assert _table() == first, "第二次跑改了东西"

    lineage = {asset_id: row[0] for asset_id, row in first.items()}
    ai = {asset_id for asset_id, row in first.items() if row[1]}
    assert lineage["tile"] == [{"asset_id": "gen", "op": "grid_split"}]
    assert lineage["tile-gif"] == [{"asset_id": "tile", "op": "gif"}]
    assert lineage["stem"] == [{"asset_id": "plain", "op": "separate"}]
    assert lineage["cut"] == [{"asset_id": "voice", "op": "trim"}]
    assert lineage["export"] == [{"asset_id": "plain", "op": "export"}, {"asset_id": "cut", "op": "export"}]
    # 推不出的留空:失败的截取、时间线改过之后的导出、认不得的 derivation。
    assert lineage["cut-failed"] == lineage["export-stale"] == lineage["strange"] == []

    assert ai == {"gen", "cover", "voice", "podcast", "lipsync", "tile", "tile-gif", "cut", "export"}, (
        "生成记录的每一份产出、合成的配音 / 播客 / 数字人整段,以及顺着出处(截取 ← 配音、导出 ← 截取、GIF ← 宫格 ← 生成)"
    )

    # 搬走的两个键去掉了,别的照留;认不得的那份原样不动。
    assert first["tile"][2] == {"grid_cell": [1, 1]}
    assert first["stem"][2] == {"stem": "vocals"}
    assert first["strange"][2] == {"derived_from_asset_id": "gen", "derivation": "something_else"}
