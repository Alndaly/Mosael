"""时间线上哪些片段含 AI 生成内容 —— 片段的「AI」角标、导出对话框的标识开关、智能体看时间线,和导出加标识
看的是**同一个**判定:素材登记时定下、顺着出处继承的 `Asset.ai_generated`(见 assets/lineage)。

不能只看来源:`generated` 也被导出成片、截帧、转 GIF 用着(那些不一定是 AI 生成的);而 AI 生成的东西降噪、
拆过之后来源变了,内容还是 AI 生成的 —— 这一层由登记时的继承管,这里走真的登记入口验一遍。
"""

from __future__ import annotations

from pathlib import Path

from app.core.db import SessionLocal
from app.db.models import Asset, Sequence
from app.domain.assets import register_file_asset
from app.domain.assets.lineage import DENOISE, FRAME, ai_generated_assets, derived
from app.domain.sequences.overview import describe_sequence
from tests.util import fresh_client


def _asset(db, ws: str, name: str, *, ai: bool = False, source: str = "imported") -> str:
    asset = Asset(workspace_id=ws, kind="video", name=name, file_key=f"media/{name}.mp4", source=source,
                  media_info={"duration": 5.0}, ai_generated=ai)
    db.add(asset)
    db.flush()
    return asset.id


def _timeline(client) -> tuple[str, str]:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sid = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()["id"]
    return ws, sid


def test_登记时继承_AI素材降噪出来的算_实拍取帧不算(tmp_path: Path) -> None:
    client = fresh_client()
    ws, _sid = _timeline(client)
    media = tmp_path / "x.txt"
    media.write_text("x", encoding="utf-8")
    with SessionLocal() as db:
        generated = register_file_asset(db, workspace_id=ws, project_id=None, source_path=media, name="gen",
                                        source="generated", ai_generated=True).id
        denoised = register_file_asset(db, workspace_id=ws, project_id=None, source_path=media, name="gen 降噪",
                                       source="denoised", derived_from=derived(DENOISE, generated)).id
        shot = _asset(db, ws, "shot")
        frame = register_file_asset(db, workspace_id=ws, project_id=None, source_path=media, name="帧",
                                    source="generated", derived_from=derived(FRAME, shot)).id
        db.commit()
        assert ai_generated_assets(db, [generated, denoised, shot, frame]) == {generated, denoised}


def test_序列接口带出时间线上用到的AI素材() -> None:
    client = fresh_client()
    ws, sid = _timeline(client)
    with SessionLocal() as db:
        voice = _asset(db, ws, "tts", source="tts", ai=True)
        shot = _asset(db, ws, "shot")
        db.commit()
    client.post(f"/api/sequences/{sid}/append", json={"asset_id": shot})
    seq = client.post(f"/api/sequences/{sid}/append", json={"asset_id": voice}).json()
    assert seq["ai_asset_ids"] == [voice]


def test_智能体看时间线_含AI的片段带着标记() -> None:
    """智能体和工作流「看一眼时间线」读同一份(sequences/overview):导出会加「AI 生成」标识,它得说得出是哪几段。"""
    client = fresh_client()
    ws, sid = _timeline(client)
    with SessionLocal() as db:
        generated = _asset(db, ws, "gen", source="generated", ai=True)
        shot = _asset(db, ws, "shot")
        db.commit()
    client.post(f"/api/sequences/{sid}/append", json={"asset_id": shot})
    client.post(f"/api/sequences/{sid}/append", json={"asset_id": generated})
    with SessionLocal() as db:
        view = describe_sequence(db.get(Sequence, sid))
    clips = {clip["asset_id"]: clip for track in view["tracks"] for clip in track["clips"]}
    assert clips[generated].get("ai_generated") is True
    assert "ai_generated" not in clips[shot]
