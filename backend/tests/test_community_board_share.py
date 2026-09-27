"""画板分享(ADR 0026 §5):快照里带什么、不带什么,限额,三步上传的去重与续传,同一个链接发新版本。"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any

from PIL import Image

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset, Board, BoardShare, Job
from app.domain.community import shares, snapshot as snapshots
from app.domain.jobs import cancel_job
from app.domain.note_types import NoteContent
from app.domain.notes import create_note, save_note
from tests.community_fake import FakeCommunity, connect, install
from tests.util import wait_status

#: 快照里**绝不能**出现的键:运行态、表单、本机 id。
FORBIDDEN_KEYS = {"run", "form", "asset_id", "note_id", "note_revision", "scene_id", "job_id", "provider_profile_id",
                  "parameters", "bindings", "abilities", "config", "source_assets", "markers"}


def _png(color: str, size: tuple[int, int] = (64, 48)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def _asset(ws: str, asset_id: str, kind: str, data: bytes, filename: str, info: dict | None = None) -> Path:
    directory = settings.media_dir / "assets" / ws / asset_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_bytes(data)
    with SessionLocal() as db:
        db.add(Asset(id=asset_id, workspace_id=ws, kind=kind, name=f"素材{asset_id}", file_key=str(path.relative_to(settings.data_dir)),
                     media_info=info or {}))
        db.commit()
    return path


def _board(ws: str, items: list[dict], edges: list[dict] | None = None) -> str:
    with SessionLocal() as db:
        board = Board(workspace_id=ws, name="灵感", canvas={"items": items, "edges": edges or [], "markers": []})
        db.add(board)
        db.commit()
        return board.id


def _setup(monkeypatch, fake: FakeCommunity | None = None) -> tuple[FakeCommunity, Any, str]:
    fake, client, clock = install(monkeypatch, fake)
    connect(client, fake, clock)
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    return fake, client, ws


def _share(client, board_id: str, ws: str, **body) -> dict:
    started = client.post(f"/api/boards/{board_id}/share", json={"workspace_id": ws, **body})
    assert started.status_code == 200, started.text
    return started.json()


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for one in value.values() for key in _keys(one)}
    if isinstance(value, list):
        return {key for one in value for key in _keys(one)}
    return set()


def test_快照只带看得见的内容(monkeypatch) -> None:
    fake, client, ws = _setup(monkeypatch)
    cat = _asset(ws, "a-cat", "image", _png("orange"), "cat.png", {"width": 1024, "height": 768})
    clip = _asset(ws, "a-clip", "video", b"not-really-a-video", "clip.mp4", {"width": 1920, "height": 1080})
    song = _asset(ws, "a-song", "audio", b"not-really-audio", "song.mp3")
    render = _asset(ws, "a-render", "image", _png("gray"), "render.png")
    with SessionLocal() as db:
        note = create_note(db, ws, NoteContent(title="剧本", markdown="第一版正文"))
        save_note(db, ws, note.id, 1, NoteContent(title="剧本", markdown="第二版正文,没钉住"))
        note_id = note.id
    items = [
        {"id": "n1", "kind": "note", "x": 0, "y": 0, "text": "开头", "color": "yellow"},
        {"id": "i1", "kind": "image", "x": 300, "y": 0, "width": 260, "height": 180, "asset_id": "a-cat", "title": "猫",
         "form": {"producer": "generate", "prompt": "一只橘猫", "provider_profile_id": "pp-secret",
                  "parameters": {"api_key": "sk-leak"}},
         "run": {"status": "succeeded", "job_id": "job-1"}},
        {"id": "i2", "kind": "image", "x": 600, "y": 0, "asset_id": "a-cat"},
        {"id": "v1", "kind": "video", "x": 0, "y": 300, "asset_id": "a-clip"},
        {"id": "s1", "kind": "audio", "x": 400, "y": 300, "asset_id": "a-song"},
        {"id": "d1", "kind": "document", "x": 0, "y": 600, "note_id": note_id, "note_revision": 1, "text": "剧本"},
        {"id": "c1", "kind": "scene", "x": 400, "y": 600, "scene_id": "scene-local", "asset_id": "a-render"},
        {"id": "f1", "kind": "frame", "x": -20, "y": -20, "width": 900, "height": 900, "title": "第一组"},
        {"id": "gone", "kind": "image", "x": 900, "y": 0, "asset_id": "a-deleted"},
    ]
    board_id = _board(ws, items, [{"id": "e1", "source": "n1", "target": "i1", "label": "配图"}])

    job = _share(client, board_id, ws, title="我的画板")
    assert wait_status(client, job["id"]) == "succeeded", client.get(f"/api/jobs/{job['id']}").json()

    share = next(iter(fake.shares.values()))
    body = share.versions[-1]
    dumped = json.dumps(body, ensure_ascii=False)
    assert not (_keys(body) & FORBIDDEN_KEYS), _keys(body) & FORBIDDEN_KEYS
    for leak in ("sk-leak", "pp-secret", "job-1", "scene-local", str(settings.data_dir), "a-cat"):
        assert leak not in dumped, leak

    by_id = {item["id"]: item for item in body["items"]}
    assert by_id["n1"] == {"id": "n1", "kind": "note", "x": 0.0, "y": 0.0, "width": 220.0, "height": 140.0,
                           "text": "开头", "color": "yellow"}
    cat_hash = hashlib.sha256(cat.read_bytes()).hexdigest()
    media = by_id["i1"]["media"]
    assert media["sha256"] == cat_hash and media["content_type"] == "image/png"
    assert (media["width"], media["height"]) == (1024, 768)
    thumb = cat.parent / "thumbnail.webp"
    assert media["thumb_sha256"] == hashlib.sha256(thumb.read_bytes()).hexdigest()
    assert by_id["i1"]["prompt"] == "一只橘猫" and by_id["i1"]["title"] == "猫"
    assert by_id["i2"]["media"]["sha256"] == cat_hash
    assert by_id["v1"]["media"]["sha256"] == hashlib.sha256(clip.read_bytes()).hexdigest()
    assert by_id["s1"]["media"] == {"sha256": hashlib.sha256(song.read_bytes()).hexdigest(), "content_type": "audio/mpeg"}
    # 文档:钉住的那一版正文,不是最新版。
    assert by_id["d1"]["markdown"] == "第一版正文" and by_id["d1"]["revision"] == 1 and by_id["d1"]["title"] == "剧本"
    assert by_id["c1"]["preview"]["sha256"] == hashlib.sha256(render.read_bytes()).hexdigest()
    assert by_id["f1"]["title"] == "第一组"
    assert "media" not in by_id["gone"]
    assert body["edges"] == [{"id": "e1", "source": "n1", "target": "i1", "label": "配图"}]

    # 同一只猫摆了两次,只传一次。
    assert fake.puts.count(cat_hash) == 1
    with SessionLocal() as db:
        board = db.get(Board, board_id)
        row = db.get(BoardShare, board_id)
        assert share.board_key == board.board_key
        assert (row.slug, row.version, row.title, row.visibility) == (share.slug, 1, "我的画板", "unlisted")
        assert row.url == f"https://community.test/zh/b/{share.slug}"


def test_不合快照字符集的_id_换成按位置编的名字_连线跟着改(monkeypatch) -> None:
    fake, client, ws = _setup(monkeypatch)
    board_id = _board(ws, [
        {"id": "便签 一", "kind": "note", "x": 0, "y": 0, "text": "a"},
        {"id": "n2", "kind": "note", "x": 300, "y": 0, "text": "b"},
    ], [{"id": "便签 一->n2", "source": "便签 一", "target": "n2"}])
    assert wait_status(client, _share(client, board_id, ws)["id"]) == "succeeded"
    body = next(iter(fake.shares.values())).versions[-1]
    assert [item["id"] for item in body["items"]] == ["i0", "n2"]
    assert body["edges"] == [{"id": "e0", "source": "i0", "target": "n2"}]


def test_超出限额_在上传之前就说清楚(monkeypatch) -> None:
    fake, client, ws = _setup(monkeypatch)
    many = [{"id": f"n{i}", "kind": "note", "x": i, "y": 0} for i in range(snapshots.MAX_ITEMS + 1)]
    refused = client.post(f"/api/boards/{_board(ws, many)}/share", json={"workspace_id": ws})
    assert refused.status_code == 422
    assert "最多 300 格" in refused.json()["detail"]

    _asset(ws, "a-big", "image", _png("red"), "big.png")
    monkeypatch.setattr(snapshots, "MAX_FILE_BYTES", 10)
    big = _board(ws, [{"id": "i", "kind": "image", "x": 0, "y": 0, "asset_id": "a-big"}])
    refused = client.post(f"/api/boards/{big}/share", json={"workspace_id": ws})
    assert refused.status_code == 422
    assert "素材a-big" in refused.json()["detail"]
    assert fake.count("/shares/uploads") == 0
    with SessionLocal() as db:
        assert db.query(Job).filter(Job.kind == "board_share").count() == 0


def test_传到一半断了_再分享只传没传完的(monkeypatch) -> None:
    fake, client, ws = _setup(monkeypatch)
    first = _asset(ws, "a-1", "audio", b"first-file", "one.mp3")
    second = _asset(ws, "a-2", "audio", b"second-file", "two.mp3")
    one, two = (hashlib.sha256(path.read_bytes()).hexdigest() for path in (first, second))
    board_id = _board(ws, [
        {"id": "x", "kind": "audio", "x": 0, "y": 0, "asset_id": "a-1"},
        {"id": "y", "kind": "audio", "x": 0, "y": 100, "asset_id": "a-2"},
    ])
    fake.put_failures[two] = shares.UPLOAD_ATTEMPTS  # 每次都 503,重试也救不回来

    failed = _share(client, board_id, ws)
    assert wait_status(client, failed["id"]) == "failed"
    assert set(fake.blobs) == {one}
    assert fake.count("/shares") == 0

    again = _share(client, board_id, ws)
    assert wait_status(client, again["id"]) == "succeeded"
    # 第二次问「缺哪几个」,服务端只要第二个:第一个不再传。
    assert fake.puts == [one, two]
    assert client.get(f"/api/jobs/{again['id']}").json()["result"]["uploaded"] == 1


def test_单个文件失败会重试(monkeypatch) -> None:
    fake, client, ws = _setup(monkeypatch)
    path = _asset(ws, "a-1", "audio", b"flaky", "one.mp3")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    fake.put_failures[digest] = shares.UPLOAD_ATTEMPTS - 1
    job = _share(client, _board(ws, [{"id": "x", "kind": "audio", "x": 0, "y": 0, "asset_id": "a-1"}]), ws)
    assert wait_status(client, job["id"]) == "succeeded"
    assert fake.puts == [digest]


def test_再分享沿用同一个链接_发新版本(monkeypatch) -> None:
    fake, client, ws = _setup(monkeypatch)
    board_id = _board(ws, [{"id": "n", "kind": "note", "x": 0, "y": 0, "text": "v1"}])
    assert wait_status(client, _share(client, board_id, ws)["id"]) == "succeeded"
    state = client.get(f"/api/boards/{board_id}/share", params={"workspace_id": ws}).json()
    slug = state["share"]["slug"]
    assert state["share"]["version"] == 1 and state["status"]["connected"] is True

    with SessionLocal() as db:
        board = db.get(Board, board_id)
        board.canvas = {"items": [{"id": "n", "kind": "note", "x": 0, "y": 0, "text": "v2"}], "edges": [], "markers": []}
        db.commit()
    assert wait_status(client, _share(client, board_id, ws, visibility="public")["id"]) == "succeeded"
    state = client.get(f"/api/boards/{board_id}/share", params={"workspace_id": ws}).json()
    assert state["share"]["slug"] == slug and state["share"]["version"] == 2
    assert state["share"]["visibility"] == "public"
    assert len(fake.shares) == 1 and fake.shares[slug].versions[-1]["items"][0]["text"] == "v2"


def test_改可见性与撤回(monkeypatch) -> None:
    fake, client, ws = _setup(monkeypatch)
    board_id = _board(ws, [{"id": "n", "kind": "note", "x": 0, "y": 0}])
    assert wait_status(client, _share(client, board_id, ws)["id"]) == "succeeded"
    slug = next(iter(fake.shares))

    changed = client.patch(f"/api/boards/{board_id}/share", json={"workspace_id": ws, "visibility": "public", "title": "新标题"})
    assert changed.status_code == 200, changed.text
    assert (changed.json()["visibility"], changed.json()["title"]) == ("public", "新标题")
    assert (fake.shares[slug].visibility, fake.shares[slug].title) == ("public", "新标题")

    assert client.delete(f"/api/boards/{board_id}/share", params={"workspace_id": ws}).status_code == 204
    assert fake.shares[slug].withdrawn is True
    assert client.get(f"/api/boards/{board_id}/share", params={"workspace_id": ws}).json()["share"] is None


def test_预签名地址上传时不带令牌(monkeypatch) -> None:
    fake, client, ws = _setup(monkeypatch, FakeCommunity(presigned=True))
    path = _asset(ws, "a-1", "audio", b"to-object-storage", "one.mp3")
    job = _share(client, _board(ws, [{"id": "x", "kind": "audio", "x": 0, "y": 0, "asset_id": "a-1"}]), ws)
    assert wait_status(client, job["id"]) == "succeeded"
    assert hashlib.sha256(path.read_bytes()).hexdigest() in fake.blobs


def test_取消_传完手上这个就停(monkeypatch) -> None:
    fake, client, ws = _setup(monkeypatch)
    _asset(ws, "a-1", "audio", b"first", "one.mp3")
    _asset(ws, "a-2", "audio", b"second", "two.mp3")
    board_id = _board(ws, [
        {"id": "x", "kind": "audio", "x": 0, "y": 0, "asset_id": "a-1"},
        {"id": "y", "kind": "audio", "x": 0, "y": 100, "asset_id": "a-2"},
    ])
    job_id: list[str] = []

    def cancel_after_first(_digest: str) -> None:
        with SessionLocal() as db:
            cancel_job(db, db.get(Job, job_id[0]))

    fake.on_put = cancel_after_first
    job_id.append(_share(client, board_id, ws)["id"])
    assert wait_status(client, job_id[0]) == "failed"
    assert len(fake.puts) == 1
    assert fake.count("/shares") == 0


def test_没连社区账号时说清楚(monkeypatch) -> None:
    fake, client, _clock = install(monkeypatch)
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    refused = client.post(f"/api/boards/{_board(ws, [])}/share", json={"workspace_id": ws})
    assert refused.status_code == 409
    assert "社区账号" in refused.json()["detail"]


def test_复制出来的画板拿到自己的_board_key(monkeypatch) -> None:
    _fake, client, ws = _setup(monkeypatch)
    board_id = _board(ws, [])
    copied = client.post(f"/api/boards/{board_id}/duplicate", json={"workspace_id": ws})
    assert copied.status_code == 200, copied.text
    with SessionLocal() as db:
        keys = {db.get(Board, board_id).board_key, db.get(Board, copied.json()["id"]).board_key}
    assert len(keys) == 2 and all(keys)
