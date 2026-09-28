"""文档进素材库(ADR 0031 第一步):pdf / docx / pptx 这类文件认成「文档」,不再兜底成视频。

此前 `guess_kind` 认不出的一律是视频:一份 pptx 进了「视频」筛选,还去起了一个代理转码。现在:
文档按扩展名 / 类型认;认不出、也探不出画面和声音的文件拒收并说清楚;文档放不上时间线;
已经被当成视频的文档由迁移改回来。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.db import SessionLocal
from app.db.models import Asset, Job
from tests.util import fresh_client


def _ws(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _upload(client, ws: str, name: str, data: bytes, content_type: str = "application/octet-stream"):
    return client.post("/api/assets/import", data={"workspace_id": ws}, files={"file": (name, data, content_type)})


@pytest.mark.parametrize(("name", "content_type"), [
    ("方案.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    ("合同.docx", "application/octet-stream"),
    ("报表.xlsx", ""),
    ("说明.pdf", "application/pdf"),
    ("readme.md", "text/markdown"),
    ("数据.csv", "text/csv"),
])
def test_文档认成文档_不当视频_不起转码(name: str, content_type: str) -> None:
    client = fresh_client()
    ws = _ws(client)
    made = _upload(client, ws, name, b"PK\x03\x04 not really a zip", content_type)
    assert made.status_code == 200, made.text
    asset = made.json()
    assert asset["kind"] == "document"
    assert asset["media_info"]["format"] == Path(name).suffix.lstrip(".")
    assert asset["media_info"]["size_bytes"] > 0
    assert "duration" not in asset["media_info"] and "has_thumbnail" not in asset["media_info"]
    with SessionLocal() as db:
        assert db.query(Job).filter(Job.kind == "proxy").count() == 0, "文档不起视频代理转码"


def test_没有扩展名但类型说了是_PDF_也认得() -> None:
    from app.media.probe import guess_kind

    assert guess_kind(Path("download"), "application/pdf") == "document"
    assert guess_kind(Path("a.pptx"), "video/mp4") == "document", "扩展名是文档就是文档"
    assert guess_kind(Path("a.png"), None) == "image"
    assert guess_kind(Path("a.mp3"), None) == "audio"


def test_认不出也探不出画面声音的文件_拒收_不留文件() -> None:
    from app.media.paths import asset_dir

    client = fresh_client()
    ws = _ws(client)
    refused = _upload(client, ws, "工具.zip", b"PK\x03\x04 junk")
    assert refused.status_code == 415, refused.text
    assert "工具.zip" in refused.json()["detail"]
    with SessionLocal() as db:
        assert db.query(Asset).filter(Asset.workspace_id == ws).count() == 0
    root = asset_dir(ws, "x").parent
    assert not root.exists() or not any(root.iterdir()), "拒了的导入不在磁盘上留文件"


def test_说了是视频的照收_探不出来由修复任务补() -> None:
    client = fresh_client()
    ws = _ws(client)
    made = _upload(client, ws, "clip.bin", b"\x00" * 64, "video/mp4")
    assert made.status_code == 200, made.text
    assert made.json()["kind"] == "video"


def test_文档放不上时间线() -> None:
    client = fresh_client()
    ws = _ws(client)
    doc = _upload(client, ws, "方案.pptx", b"PK\x03\x04").json()
    board = client.post("/api/boards", json={"workspace_id": ws, "name": "B"}).json()["id"]
    sequence = client.post(f"/api/boards/{board}/sequences", json={"workspace_id": ws}).json()["sequence_id"]
    refused = client.post(f"/api/sequences/{sequence}/append", json={"asset_id": doc["id"]})
    assert refused.status_code in (400, 422), refused.text
    body = client.get(f"/api/sequences/{sequence}").json()
    track = next(one for one in body["tracks"] if one["kind"] == "video")
    from app.domain.sequences.operations import InsertClip, insert_clip
    from app.domain.sequences.errors import SequenceDomainError

    with SessionLocal() as db, pytest.raises(SequenceDomainError) as refused_insert:
        insert_clip(db, sequence, InsertClip(track_id=track["id"], asset_id=doc["id"], timeline_start=0, src_in=0, src_out=5))
    assert refused_insert.value.key == "seqErr_assetNotMedia"


def test_迁移_被当成视频的文档改回来_真视频不动() -> None:
    from app.db.migrations import _migrate_documents_are_not_videos, migration_plan
    from app.media.paths import asset_dir, asset_key

    assert "migrate-documents-are-not-videos" in {step.name for step in migration_plan().steps}
    client = fresh_client()
    ws = _ws(client)
    with SessionLocal() as db:
        for asset_id, name in (("deck", "方案.pptx"), ("real", "clip.mp4")):
            folder = asset_dir(ws, asset_id)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / name).write_bytes(b"12345")
            db.add(Asset(id=asset_id, workspace_id=ws, kind="video", name=name, original_filename=name,
                         file_key=asset_key(ws, asset_id, name), media_info={"fps": 1.0}))
        db.commit()

    _migrate_documents_are_not_videos()
    _migrate_documents_are_not_videos()
    with SessionLocal() as db:
        deck, real = db.get(Asset, "deck"), db.get(Asset, "real")
        info = deck.media_info if isinstance(deck.media_info, dict) else json.loads(deck.media_info)
        assert deck.kind == "document" and info == {"format": "pptx", "size_bytes": 5}
        assert real.kind == "video" and real.media_info == {"fps": 1.0}


def test_前端认的文档扩展名和后端是同一张表() -> None:
    import re

    from app.media.probe import DOCUMENT_EXTENSIONS

    source = (Path(__file__).resolve().parents[2] / "frontend/src/lib/assetKinds.ts").read_text(encoding="utf-8")
    block = re.search(r"DOCUMENT_EXTENSIONS = \[(.*?)\] as const", source, re.S).group(1)
    assert set(re.findall(r'"(\.[a-z0-9]+)"', block)) == DOCUMENT_EXTENSIONS
