"""片段级「替换媒体」与剪辑台上的片段声音处理(降噪 / 只留人声 / 拆成人声和背景音,做完直接换到时间线上)。

降噪、分离这类付费 / 耗时的外部能力换成立刻交回一份素材;任务、剪辑操作、撤销都是真的。
"""

from __future__ import annotations

from types import SimpleNamespace

from app.core.db import SessionLocal
from app.db.models import Asset, Clip, Job, Sequence
from app.domain.jobs import wait_for_idle_jobs
from app.domain.sequences.history import undo
from tests.util import fresh_client


def _timeline(client, *, kind: str = "video") -> tuple[str, str, str, str]:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sid = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()["id"]
    with SessionLocal() as db:
        footage = Asset(workspace_id=ws, kind=kind, name="原片", file_key=f"media/o.{'mp4' if kind == 'video' else 'wav'}",
                        media_info={"duration": 10.0})
        db.add(footage)
        db.commit()
        footage_id = footage.id
    client.post(f"/api/sequences/{sid}/append", json={"asset_id": footage_id})
    seq = client.post(f"/api/sequences/{sid}/append", json={"asset_id": footage_id}).json()
    clip = sorted((c for t in seq["tracks"] for c in t["clips"]), key=lambda c: c["timeline_start"])[0]
    # 第一段剪短、调速、调音量:换素材之后这些都该在。
    client.patch(f"/api/sequences/{sid}/clips/{clip['id']}/speed", json={"speed": 1.5})
    return ws, sid, footage_id, clip["id"]


def _asset(ws: str, *, kind: str = "video", duration: float = 10.0, **extra) -> str:
    with SessionLocal() as db:
        asset = Asset(workspace_id=ws, kind=kind, name="新", file_key="media/n.mp4", media_info={"duration": duration}, **extra)
        db.add(asset)
        db.commit()
        return asset.id


def _clips(sid: str) -> list[dict]:
    with SessionLocal() as db:
        return sorted(
            ({"id": c.id, "asset_id": c.asset_id, "start": c.timeline_start, "speed": c.speed, "muted": c.muted,
              "track": c.track.kind} for t in db.get(Sequence, sid).tracks for c in t.clips),
            key=lambda c: (c["track"], c["start"]),
        )


def test_替换媒体_位置和属性都不动_一步撤销换回来() -> None:
    client = fresh_client()
    ws, sid, footage, clip_id = _timeline(client)
    new = _asset(ws)
    before = next(c for c in _clips(sid) if c["id"] == clip_id)
    response = client.post(f"/api/sequences/{sid}/clips/replace-media", json={"asset_id": new, "clip_ids": [clip_id]})
    assert response.status_code == 200, response.text
    after = next(c for c in _clips(sid) if c["id"] == clip_id)
    assert after == {**before, "asset_id": new}
    with SessionLocal() as db:
        undo(db, sid)
        db.commit()
    assert next(c for c in _clips(sid) if c["id"] == clip_id)["asset_id"] == footage


def test_批量替换同一素材的所有片段() -> None:
    client = fresh_client()
    ws, sid, footage, _ = _timeline(client)
    new = _asset(ws)
    response = client.post(f"/api/sequences/{sid}/clips/replace-media", json={"asset_id": new, "from_asset_id": footage})
    assert response.status_code == 200, response.text
    assert {c["asset_id"] for c in _clips(sid)} == {new}


def test_换成放不下的素材被拒() -> None:
    client = fresh_client()
    ws, sid, _, clip_id = _timeline(client)
    short = _asset(ws, duration=3.0)
    sound = _asset(ws, kind="audio")
    for asset in (short, sound):
        response = client.post(f"/api/sequences/{sid}/clips/replace-media", json={"asset_id": asset, "clip_ids": [clip_id]})
        assert response.status_code == 422, response.text


def test_换素材不依赖坐标_别处挪过也照做_这一段被人改过就409() -> None:
    """并发协议(sequences/concurrency):换素材不改位置和长短,和别处的编辑能交换;碰过同一段的就拒。"""
    client = fresh_client()
    ws, sid, _, clip_id = _timeline(client)
    new = _asset(ws)
    seen = client.get(f"/api/sequences/{sid}").json()["revision"]
    other = next(c["id"] for c in _clips(sid) if c["id"] != clip_id and c["track"] == "video")
    assert client.patch(f"/api/sequences/{sid}/clips/{other}/move", json={"timeline_start": 30.0}).status_code == 200
    replay = client.post(f"/api/sequences/{sid}/clips/replace-media?base_revision={seen}",
                         json={"asset_id": new, "clip_ids": [clip_id]})
    assert replay.status_code == 200, replay.text

    seen = replay.json()["revision"]
    assert client.patch(f"/api/sequences/{sid}/clips/{clip_id}/gain", json={"gain": 0.5, "muted": False}).status_code == 200
    stale = client.post(f"/api/sequences/{sid}/clips/replace-media?base_revision={seen}",
                        json={"asset_id": _asset(ws), "clip_ids": [clip_id]})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "sequence_revision_conflict"


def test_片段声音处理照着看到的那一版_那一段被改过就不排任务(monkeypatch) -> None:
    client = fresh_client()
    ws, sid, _, clip_id = _timeline(client)
    _fake_processing(monkeypatch, ws)
    seen = client.get(f"/api/sequences/{sid}").json()["revision"]
    assert client.patch(f"/api/sequences/{sid}/clips/{clip_id}/gain", json={"gain": 0.5, "muted": False}).status_code == 200
    stale = client.post(f"/api/sequences/{sid}/clips/{clip_id}/audio?base_revision={seen}", json={"action": "denoise"})
    assert stale.status_code == 409, stale.text


def _fake_processing(monkeypatch, ws: str) -> list[str]:
    import app.domain.assets.denoise as denoise
    import app.domain.assets.separation as separation

    calls: list[str] = []

    def fake_denoise(db, asset, **_):
        calls.append("denoise")
        made = Asset(workspace_id=ws, kind=asset.kind, name="降噪", file_key="media/dn.mp4",
                     media_info={"duration": 10.0, "derived_from_asset_id": asset.id, "derivation": "denoise"})
        db.add(made)
        db.flush()
        return made, "fake"

    def fake_separate(db, asset, **_):
        calls.append("separate")
        made = {}
        for stem in ("vocals", "background"):
            row = Asset(workspace_id=ws, kind="audio", name=stem, file_key=f"media/{stem}.wav",
                        media_info={"duration": 10.0, "derived_from_asset_id": asset.id, "derivation": "separate_audio",
                                    "stem": stem})
            db.add(row)
            db.flush()
            made[stem] = row
        return SimpleNamespace(vocals=made["vocals"], background=made["background"], engine="fake")

    monkeypatch.setattr(denoise, "denoise_asset", fake_denoise)
    monkeypatch.setattr(denoise, "ready_adapter", lambda *a, **k: object())
    monkeypatch.setattr(separation, "separate_asset", fake_separate)
    monkeypatch.setattr(separation, "available", lambda *a, **k: True)
    return calls


def _process(client, sid: str, clip_id: str, action: str) -> Job:
    response = client.post(f"/api/sequences/{sid}/clips/{clip_id}/audio", json={"action": action})
    assert response.status_code == 200, response.text
    assert wait_for_idle_jobs(15)
    with SessionLocal() as db:
        job = db.get(Job, response.json()["id"])
        assert job.status == "succeeded", job.error
        return job


def test_片段降噪之后_时间线上用着它的片段都换成降噪的_一步撤销(monkeypatch) -> None:
    client = fresh_client()
    ws, sid, footage, clip_id = _timeline(client)
    _fake_processing(monkeypatch, ws)
    job = _process(client, sid, clip_id, "denoise")
    denoised = job.result["assets"]["denoised"]
    assert {c["asset_id"] for c in _clips(sid)} == {denoised} and job.result["clips"] == 2
    with SessionLocal() as db:
        undo(db, sid)
        db.commit()
    assert {c["asset_id"] for c in _clips(sid)} == {footage}


def test_视频片段只留人声_画面不动_人声放到音频轨上(monkeypatch) -> None:
    client = fresh_client()
    ws, sid, footage, clip_id = _timeline(client)
    calls = _fake_processing(monkeypatch, ws)
    job = _process(client, sid, clip_id, "isolate_voice")
    clips = _clips(sid)
    source = next(c for c in clips if c["id"] == clip_id)
    assert source["asset_id"] == footage and source["muted"], "画面还是原片,原片的声音关了"
    [voice] = [c for c in clips if c["asset_id"] == job.result["assets"]["vocals"]]
    assert voice["track"] == "audio" and voice["start"] == source["start"] and voice["speed"] == 1.5

    # 再拆另一段:同一份素材已经整段拆过,直接用缓存。
    other = next(c for c in clips if c["track"] == "video" and c["id"] != clip_id)["id"]
    _process(client, sid, other, "separate")
    assert calls == ["separate"]


def test_音频片段拆成人声和背景音_两份都上轨(monkeypatch) -> None:
    client = fresh_client()
    ws, sid, footage, clip_id = _timeline(client, kind="audio")
    _fake_processing(monkeypatch, ws)
    job = _process(client, sid, clip_id, "separate")
    stems = set(job.result["assets"].values())
    placed = {c["asset_id"] for c in _clips(sid) if c["asset_id"] in stems}
    assert placed == stems
    with SessionLocal() as db:
        assert db.get(Clip, clip_id).muted
