"""时间线上哪些片段是 AI 生成的 —— 片段的「AI」角标、导出对话框的标识开关看同一份答案(assets/provenance)。

不能只看来源:`generated` 也被导出成片、截帧、转 GIF 用着(那些不是 AI 生成的);而 AI 生成的东西降噪、
拆过之后来源变了,内容还是 AI 生成的。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Asset, GeneratedAsset
from app.domain.assets.provenance import ai_generated_asset_ids
from tests.util import fresh_client


def _asset(db, ws: str, name: str, *, source: str = "imported", parent: str | None = None) -> str:
    asset = Asset(workspace_id=ws, kind="video", name=name, file_key=f"media/{name}.mp4", source=source,
                  media_info={"duration": 5.0, **({"derived_from_asset_id": parent} if parent else {})})
    db.add(asset)
    db.flush()
    return asset.id


def test_按生成记录_合成来源_派生链认AI生成_导出和截帧不算() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        generated = _asset(db, ws, "gen", source="generated")
        db.add(GeneratedAsset(asset_id=generated, provider="p", model="m"))
        denoised = _asset(db, ws, "gen-denoised", source="denoised", parent=generated)
        voice = _asset(db, ws, "tts", source="tts")
        exported = _asset(db, ws, "export", source="generated")
        frame = _asset(db, ws, "frame", source="generated", parent=exported)
        shot = _asset(db, ws, "shot")
        db.commit()
        found = ai_generated_asset_ids(db, [generated, denoised, voice, exported, frame, shot])
    assert found == {generated, denoised, voice}


def test_序列接口带出时间线上用到的AI素材() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sid = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()["id"]
    with SessionLocal() as db:
        voice = _asset(db, ws, "tts", source="tts")
        shot = _asset(db, ws, "shot")
        db.commit()
    client.post(f"/api/sequences/{sid}/append", json={"asset_id": shot})
    seq = client.post(f"/api/sequences/{sid}/append", json={"asset_id": voice}).json()
    assert seq["ai_asset_ids"] == [voice]
