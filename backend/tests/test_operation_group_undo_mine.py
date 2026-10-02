"""操作组和 T3 的撤销协议(expected_revision + mine)一起用:一组操作撤一次,而且只撤自己的。

配音这类「一件事、很多步」的动作记成一条组操作(sequences/grouping),撤销栈上它就是一步、署的是发起人。
同事在这之后做了别的(不相干的)编辑,发起人按 ⌘Z(mine)撤掉的是整次配音,同事那一步留着;同事撤的是他自己那一步。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Sequence
from app.domain.sequences.grouping import OperationGroup
from app.domain.sequences.operations import AddTrack, InsertTextClip, add_track, insert_text_clip
from tests.test_timeline_concurrency import _setup


def _subtitles(state: dict) -> list[str]:
    return sorted(clip["text_override"] for track in state["tracks"] if track["kind"] == "subtitle" for clip in track["clips"])


def test_一组操作撤一次_只撤自己的_同事那一步留着() -> None:
    owner, mate, sid, _revision, first, _second = _setup()
    owner_id = owner.get("/api/auth/me").json()["id"]
    group = OperationGroup(sid, label="subtitle_dub", actor_id=owner_id)
    with SessionLocal() as db, group.collect(db):
        add_track(db, sid, AddTrack(kind="subtitle", actor_id=owner_id))
        track_id = [t for t in db.get(Sequence, sid).tracks if t.kind == "subtitle"][-1].id
        for index, text in enumerate(("一", "二")):
            insert_text_clip(db, sid, InsertTextClip(track_id=track_id, text=text, timeline_start=index * 2.0, duration=1.0,
                                                     actor_id=owner_id))
        db.commit()
    seen = owner.get(f"/api/sequences/{sid}").json()["revision"]
    # 同事改了画面那一段的音量:不依赖坐标、和字幕不相干。
    assert mate.patch(f"/api/sequences/{sid}/clips/{first}/gain", json={"gain": 0.5, "muted": False}).status_code == 200

    undone = owner.post(f"/api/sequences/{sid}/undo?mine=true&expected_revision={seen}")
    assert undone.status_code == 200, undone.text
    state = undone.json()
    assert _subtitles(state) == [] and not [t for t in state["tracks"] if t["kind"] == "subtitle"], "整组一次撤掉"
    film = next(c for t in state["tracks"] if t["kind"] == "video" for c in t["clips"] if c["id"] == first)
    assert film["gain"] == 0.5, "同事那一步留着"

    again = mate.post(f"/api/sequences/{sid}/undo?mine=true")
    assert again.status_code == 200, again.text
    film = next(c for t in again.json()["tracks"] if t["kind"] == "video" for c in t["clips"] if c["id"] == first)
    assert film["gain"] == 1.0
