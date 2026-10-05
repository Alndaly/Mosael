"""素材分出中间产物的两条迁移,各喂一份老形状的数据。

- `migrate-assets-know-if-they-are-intermediate`:老的 assets 表补 intermediate 列(和素材库列表按它筛的索引);
- `backfill-intermediate-assets`:逐句配音的一句、对口型的一块,推得出的标上,推不出的留在素材库;再跑一次什么都不变。

真实的库里 1228 份素材,1009 份叫「… · 配音」:822 份记着 `dub_line`,136 份是字幕配音任务派出的合成交回的,
另有 27 份没留下任务关系、但放在配音轨上 —— 都是逐句配音的一句;剩下 24 份是在 AI 工作台单独念的,留在素材库。
"""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.core.db import SessionLocal, engine
from app.db.migrations import _backfill_intermediate_assets, _migrate_assets_know_if_they_are_intermediate
from app.db.models import Asset, Clip, Job, Project, Sequence, Track
from tests.util import fresh_client


def _workspace() -> str:
    return fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]


def _marks() -> dict[str, str]:
    with engine.connect() as conn:
        return dict(conn.execute(text("SELECT id, intermediate FROM assets")).all())


def test_老表补上一列_老素材都还在素材库_再跑一次什么都不做() -> None:
    ws = _workspace()
    with SessionLocal() as db:
        db.add(Asset(id="old", workspace_id=ws, kind="audio", name="老素材"))
        db.commit()
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS idx_assets_workspace_intermediate_created"))
        conn.execute(text("ALTER TABLE assets DROP COLUMN intermediate"))
    engine.dispose()
    assert "intermediate" not in {column["name"] for column in inspect(engine).get_columns("assets")}

    _migrate_assets_know_if_they_are_intermediate()
    _migrate_assets_know_if_they_are_intermediate()
    engine.dispose()

    assert "intermediate" in {column["name"] for column in inspect(engine).get_columns("assets")}
    assert "idx_assets_workspace_intermediate_created" in {index["name"] for index in inspect(engine).get_indexes("assets")}
    assert _marks() == {"old": ""}


def test_回填_逐句配音和对口型的零件标上_别的都不动_重跑不变() -> None:
    ws = _workspace()
    with SessionLocal() as db:
        project = Project(workspace_id=ws, name="P")
        db.add(project)
        db.flush()

        def asset(asset_id: str, source: str, kind: str = "audio", *, media_info: dict | None = None,
                  derived_from: list | None = None) -> None:
            db.add(Asset(id=asset_id, workspace_id=ws, kind=kind, name=asset_id, source=source,
                         media_info=media_info or {}, derived_from=derived_from or []))

        asset("dub-new", "tts", media_info={"duration": 2.0, "dub_line": {"text": "第一句", "voice": "v"}})
        asset("dub-by-job", "tts")
        asset("dub-on-track", "tts")
        asset("talk-line", "tts")
        asset("talk-joined", "tts", derived_from=[{"asset_id": "talk-line", "op": "concat"}])
        asset("talk-short", "tts")
        asset("talk-padded", "tts", derived_from=[{"asset_id": "talk-short", "op": "pad"}])
        asset("standalone", "tts")
        asset("my-voiceover", "imported")
        asset("footage", "imported", "video")
        asset("chunk-done", "digital_human", "video", media_info={"dub_lipsync_chunk": {"key": "k"}})
        asset("chunk-cut", "derived", "video", derived_from=[{"asset_id": "footage", "op": "trim"}])
        asset("chunk-voice", "derived", derived_from=[{"asset_id": "dub-new", "op": "mix"}])
        asset("joined", "digital_human", "video", derived_from=[{"asset_id": "footage", "op": "concat"},
                                                                 {"asset_id": "chunk-done", "op": "concat"}])
        asset("doc", "imported", "document")
        asset("illustration", "derived", "image", derived_from=[{"asset_id": "doc", "op": "extract"}])
        asset("film", "exported", "video", derived_from=[{"asset_id": "dub-new", "op": "export"}])

        dub = Job(workspace_id=ws, kind="subtitle_dub", status="succeeded", payload={}, result={})
        db.add(dub)
        db.flush()
        db.add(Job(workspace_id=ws, kind="tts", status="succeeded", payload={}, result={"asset_id": "dub-by-job"},
                   parent_job_id=dub.id))
        db.add(Job(workspace_id=ws, kind="tts", status="succeeded", payload={}, result={"asset_id": "standalone"}))

        sequence = Sequence(workspace_id=ws, project_id=project.id, name="S")
        db.add(sequence)
        db.flush()
        track = Track(sequence_id=sequence.id, kind="audio", name="配音", position=1, role="dub")
        db.add(track)
        db.flush()
        for start, used in enumerate(("dub-on-track", "my-voiceover")):
            db.add(Clip(workspace_id=ws, sequence_id=sequence.id, track_id=track.id, asset_id=used,
                        timeline_start=float(start * 3), src_in=0.0, src_out=2.0))
        db.commit()

    _backfill_intermediate_assets()
    first = _marks()
    assert {asset_id for asset_id, kind in first.items() if kind == "dub_line"} == {
        "dub-new", "dub-by-job", "dub-on-track", "talk-line", "talk-short"}
    assert {asset_id for asset_id, kind in first.items() if kind == "lipsync_chunk"} == {
        "chunk-done", "chunk-cut", "chunk-voice"}
    for kept in ("talk-joined", "talk-padded", "standalone", "my-voiceover", "footage", "joined", "doc",
                 "illustration", "film"):
        assert first[kept] == "", f"{kept} 不是工序零件,留在素材库"

    _backfill_intermediate_assets()
    assert _marks() == first
