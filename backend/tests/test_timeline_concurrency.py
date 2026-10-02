"""同一条时间线上的几个写入方:编辑带着「我看到的是第几版」,落后了能交换就照做,不能就 409 并说清是谁改的。

## 现场(审查实测)

- 两个人同时剪同一条时间线:A 看到的是第 5 版,B 先提交了第 6 版,A 的那一步照样做下去 ——
  拖到的落点、切的那一刀算的是 A 屏幕上那份过时的时间线。没有任何地方报冲突。
- 版本号的 CAS 撞上时回的是 422(领域错误的基类),客户端分不出这是「冲突了、拉最新的」还是「参数不对」。
- 剪辑页的 ⌘Z 撤的是整条时间线上最新的一步:同事刚做的那一下,被我按一下撤掉了。
"""

from __future__ import annotations

from tests.util import fresh_client, insert_asset, second_client


def _setup():
    owner = fresh_client()
    ws = owner.post("/api/workspaces", json={"name": "W"}).json()["id"]
    mate = second_client("mate")
    invited = owner.post(f"/api/workspaces/{ws}/invitations", json={"username": "mate", "role": "editor"})
    assert invited.status_code == 200, invited.text
    invitation = mate.get("/api/invitations").json()["invitations"][0]
    assert mate.post(f"/api/invitations/{invitation['id']}/accept").status_code == 200
    project = owner.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sequence = owner.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()
    video = next(track for track in sequence["tracks"] if track["kind"] == "video")["id"]
    asset = insert_asset(ws, kind="video", name="v", file_key="x", media_info={"duration": 60})
    sid = sequence["id"]
    for start in (0.0, 10.0):
        state = owner.post(
            f"/api/sequences/{sid}/clips",
            json={"track_id": video, "asset_id": asset, "timeline_start": start, "src_in": 0, "src_out": 5},
        ).json()
    first, second = [clip["id"] for clip in _video(state)["clips"]]
    return owner, mate, sid, state["revision"], first, second


def _video(state: dict) -> dict:
    return next(track for track in state["tracks"] if track["kind"] == "video")


def _clip(state: dict, clip_id: str) -> dict:
    return next(clip for clip in _video(state)["clips"] if clip["id"] == clip_id)


def test_落后的一版上挪片段_而中间有人挪过_回409带最新序列并说是谁() -> None:
    owner, mate, sid, seen, first, second = _setup()
    moved = mate.patch(f"/api/sequences/{sid}/clips/{second}/move?base_revision={seen}", json={"timeline_start": 20})
    assert moved.status_code == 200, moved.text

    stale = owner.patch(f"/api/sequences/{sid}/clips/{first}/move?base_revision={seen}", json={"timeline_start": 3})
    assert stale.status_code == 409, stale.text
    detail = stale.json()["detail"]
    assert detail["code"] == "sequence_revision_conflict"
    assert detail["base_revision"] == seen and detail["current_revision"] == moved.json()["revision"]
    assert "mate" in detail["message"], "说清是谁改的"
    assert "别处" not in detail["message"]
    latest = detail["sequence"]
    assert latest["revision"] == moved.json()["revision"]
    assert _clip(latest, second)["timeline_start"] == 20, "附上的就是最新的那一版"
    assert _clip(latest, first)["timeline_start"] == 0, "过时的那一步没有做"


def test_落后的一版上改另一段的增益_与中间的挪动可交换_自动在最新版上做() -> None:
    owner, mate, sid, seen, first, second = _setup()
    mate.patch(f"/api/sequences/{sid}/clips/{second}/move?base_revision={seen}", json={"timeline_start": 20})

    gained = owner.patch(
        f"/api/sequences/{sid}/clips/{first}/gain?base_revision={seen}", json={"gain": 0.5, "muted": False}
    )
    assert gained.status_code == 200, gained.text
    state = gained.json()
    assert _clip(state, first)["gain"] == 0.5
    assert _clip(state, second)["timeline_start"] == 20, "中间那一步还在"


def test_落后的一版上改同一段的文字属性_中间有人删了它_拒() -> None:
    owner, mate, sid, seen, first, _second = _setup()
    mate.delete(f"/api/sequences/{sid}/clips/{first}?base_revision={seen}")

    stale = owner.patch(
        f"/api/sequences/{sid}/clips/{first}/gain?base_revision={seen}", json={"gain": 0.5, "muted": False}
    )
    assert stale.status_code == 409, stale.text
    assert "mate" in stale.json()["detail"]["message"]


def test_落后的一版上挪片段_中间只是改了别的片段的增益_照做() -> None:
    owner, mate, sid, seen, first, second = _setup()
    mate.patch(f"/api/sequences/{sid}/clips/{second}/gain?base_revision={seen}", json={"gain": 0.3, "muted": True})

    moved = owner.patch(f"/api/sequences/{sid}/clips/{first}/move?base_revision={seen}", json={"timeline_start": 30})
    assert moved.status_code == 200, moved.text
    assert _clip(moved.json(), first)["timeline_start"] == 30


def test_做了又撤掉的那一步不算_不会挡住() -> None:
    owner, mate, sid, seen, first, second = _setup()
    mate.patch(f"/api/sequences/{sid}/clips/{second}/move", json={"timeline_start": 20})
    mate.post(f"/api/sequences/{sid}/undo")

    moved = owner.patch(f"/api/sequences/{sid}/clips/{first}/move?base_revision={seen}", json={"timeline_start": 3})
    assert moved.status_code == 200, moved.text


def test_版本号的CAS撞上_也是409() -> None:
    """两个写入方在同一版上同时记账:后到的那个改 0 行 —— 409(冲突),不是 422(参数不对)。"""
    from app.core.db import SessionLocal
    from app.db.models import Sequence
    from app.domain.sequences.errors import SequenceRevisionConflict
    from app.domain.sequences.operations import SetClipGain, set_clip_gain

    owner, _mate, sid, _seen, first, _second = _setup()
    with SessionLocal() as db:
        mine = db.get(Sequence, sid)  # 这一方先读到了现在的版本号(留着引用:身份映射是弱引用,丢了就会重读)
        read = mine.revision
        owner.patch(f"/api/sequences/{sid}/clips/{first}/gain", json={"gain": 0.5, "muted": False})
        try:
            set_clip_gain(db, sid, SetClipGain(clip_id=first, gain=0.2, muted=False))
            raise AssertionError("后到的写入方应当被挡下")
        except SequenceRevisionConflict as exc:
            assert exc.status == 409 and exc.base_revision == read
        db.rollback()


def test_编辑记下是谁做的_请求体冒充不了() -> None:
    from app.core.db import SessionLocal
    from app.db.models import SequenceOperation

    owner, mate, sid, _seen, first, _second = _setup()
    mate.patch(f"/api/sequences/{sid}/clips/{first}/gain", json={"gain": 0.5, "muted": False, "actor_id": "x"})
    with SessionLocal() as db:
        last = db.query(SequenceOperation).filter_by(sequence_id=sid).order_by(SequenceOperation.revision_after.desc()).first()
        mate_id = mate.get("/api/auth/me").json()["id"]
        assert last.actor_id == mate_id


# ---- 一步编辑碰到的不止点名的那段:链接组员、放下时覆盖掉的邻居、跨轨波纹挪动的别的轨 ----


def _audio(state: dict) -> list[dict]:
    return next(track for track in state["tracks"] if track["kind"] == "audio")["clips"]


def test_挪带链接音频的画面_中间有人改了那段音频_组员也算碰到_拒() -> None:
    owner, mate, sid, _seen, first, _second = _setup()
    seen = owner.post(f"/api/sequences/{sid}/clips/{first}/detach-audio").json()
    audio = _audio(seen)[0]["id"]
    mate.patch(f"/api/sequences/{sid}/clips/{audio}/gain", json={"gain": 0.2, "muted": False})

    stale = owner.patch(
        f"/api/sequences/{sid}/clips/{first}/move?base_revision={seen['revision']}", json={"timeline_start": 30}
    )
    assert stale.status_code == 409, "音频跟着画面挪,而它刚被同事改过"
    assert "mate" in stale.json()["detail"]["message"]

    alone = owner.patch(
        f"/api/sequences/{sid}/clips/{first}/move?base_revision={seen['revision']}",
        json={"timeline_start": 30, "linked": False},
    )
    assert alone.status_code == 200, "临时解链只挪画面,和那段音频不相干"


def test_放下会盖住的片段_中间有人改过它_拒() -> None:
    owner, mate, sid, seen, _first, second = _setup()
    state = owner.get(f"/api/sequences/{sid}").json()
    video = _video(state)["id"]
    asset = _clip(state, second)["asset_id"]
    mate.patch(f"/api/sequences/{sid}/clips/{second}/gain", json={"gain": 0.2, "muted": False})

    covering = owner.post(
        f"/api/sequences/{sid}/clips?base_revision={seen}",
        json={"track_id": video, "asset_id": asset, "timeline_start": 8, "src_in": 0, "src_out": 4},
    )
    assert covering.status_code == 409, "覆盖会裁掉同事刚改过的那段"

    elsewhere = owner.post(
        f"/api/sequences/{sid}/clips?base_revision={seen}",
        json={"track_id": video, "asset_id": asset, "timeline_start": 20, "src_in": 0, "src_out": 4},
    )
    assert elsewhere.status_code == 200, "落在空处,和那段不相干"


def test_跨轨波纹删除挪到别的轨上那段_中间有人改过它_拒() -> None:
    owner, mate, sid, _seen, first, _second = _setup()
    state = owner.get(f"/api/sequences/{sid}").json()
    audio_track = next(track for track in state["tracks"] if track["kind"] == "audio")["id"]
    asset = _clip(state, first)["asset_id"]
    seen = owner.post(
        f"/api/sequences/{sid}/clips",
        json={"track_id": audio_track, "asset_id": asset, "timeline_start": 20, "src_in": 0, "src_out": 3},
    ).json()
    later_audio = _audio(seen)[0]["id"]
    mate.patch(f"/api/sequences/{sid}/clips/{later_audio}/gain", json={"gain": 0.2, "muted": False})

    base = seen["revision"]
    stale = owner.delete(f"/api/sequences/{sid}/clips/{first}/ripple?all_tracks=true&base_revision={base}")
    assert stale.status_code == 409, "整条时间线左移,同事刚改过的那段音频也被挪了"
    one_track = owner.delete(f"/api/sequences/{sid}/clips/{first}/ripple?base_revision={base}")
    assert one_track.status_code == 200, "只在本轨波纹,碰不到那段音频"


def test_只撤我自己的_同事后来的那一步留着() -> None:
    owner, mate, sid, _seen, first, second = _setup()
    seen = owner.patch(f"/api/sequences/{sid}/clips/{first}/gain", json={"gain": 0.5, "muted": False}).json()["revision"]
    mate.patch(f"/api/sequences/{sid}/clips/{second}/gain", json={"gain": 0.2, "muted": False})

    #: 我手里还是自己做完那一步时的版本(同事那一步还没轮询到):不冲突,照撤。
    undone = owner.post(f"/api/sequences/{sid}/undo?mine=true&expected_revision={seen}")
    assert undone.status_code == 200, undone.text
    after = undone.json()
    assert _clip(after, first)["gain"] == 1.0, "撤的是我自己的那一步"
    assert _clip(after, second)["gain"] == 0.2, "同事那一步还在"

    redone = owner.post(f"/api/sequences/{sid}/redo?mine=true&expected_revision={after['revision']}")
    assert redone.status_code == 200, redone.text
    assert _clip(redone.json(), first)["gain"] == 0.5


def test_只撤我自己的_其间同事动了同一段_拒并说是谁() -> None:
    owner, mate, sid, _seen, first, _second = _setup()
    owner.patch(f"/api/sequences/{sid}/clips/{first}/move", json={"timeline_start": 30})
    mate.patch(f"/api/sequences/{sid}/clips/{first}/gain", json={"gain": 0.2, "muted": False})

    refused = owner.post(f"/api/sequences/{sid}/undo?mine=true")
    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert "mate" in detail["message"]
    assert _clip(detail["sequence"], first)["timeline_start"] == 30, "没撤"


def test_只撤我自己的_其间同事挪了别的片段_两步都依赖坐标_拒() -> None:
    owner, mate, sid, _seen, first, second = _setup()
    owner.patch(f"/api/sequences/{sid}/clips/{first}/move", json={"timeline_start": 30})
    mate.patch(f"/api/sequences/{sid}/clips/{second}/move", json={"timeline_start": 40})

    assert owner.post(f"/api/sequences/{sid}/undo?mine=true").status_code == 409


def test_只撤我自己的_我没做过就说没有() -> None:
    owner, mate, sid, _seen, _first, _second = _setup()
    refused = mate.post(f"/api/sequences/{sid}/undo?mine=true")
    assert refused.status_code == 422
    assert "你自己" in refused.json()["detail"] or "own" in refused.json()["detail"]


def test_撤销版本对不上_409带最新序列和是谁() -> None:
    owner, mate, sid, seen, first, _second = _setup()
    mate.patch(f"/api/sequences/{sid}/clips/{first}/gain", json={"gain": 0.2, "muted": False})

    refused = owner.post(f"/api/sequences/{sid}/undo?expected_revision={seen}")
    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert "mate" in detail["message"]
    assert _clip(detail["sequence"], first)["gain"] == 0.2


def test_只撤我自己的_我撤过又做过的那一步不挡后面的撤销() -> None:
    """自己挪了一下、撤掉、再撤更早的一步:中间那次挪动已经相抵,不该被当成「之后有人挪过」。"""
    owner, mate, sid, _seen, first, second = _setup()
    owner.patch(f"/api/sequences/{sid}/clips/{first}/move", json={"timeline_start": 20})
    owner.patch(f"/api/sequences/{sid}/clips/{second}/move", json={"timeline_start": 30})
    assert owner.post(f"/api/sequences/{sid}/undo?mine=true").status_code == 200
    again = owner.post(f"/api/sequences/{sid}/undo?mine=true")
    assert again.status_code == 200, again.text
    assert _clip(again.json(), first)["timeline_start"] == 0


def test_只重做我自己的_其间同事动了同一段_拒() -> None:
    owner, mate, sid, _seen, first, _second = _setup()
    owner.patch(f"/api/sequences/{sid}/clips/{first}/move", json={"timeline_start": 30})
    owner.post(f"/api/sequences/{sid}/undo?mine=true")
    mate.patch(f"/api/sequences/{sid}/clips/{first}/gain", json={"gain": 0.2, "muted": False})

    refused = owner.post(f"/api/sequences/{sid}/redo?mine=true")
    assert refused.status_code == 409, refused.text
    assert "mate" in refused.json()["detail"]["message"]


def test_只撤我自己的_那一步带着链接音频挪_同事后来改了那段音频_拒() -> None:
    """要撤的那一步碰到的也按改动日志算:挪画面时链接的音频跟着挪了,撤销会把它也挪回去。"""
    owner, mate, sid, _seen, first, _second = _setup()
    audio = _audio(owner.post(f"/api/sequences/{sid}/clips/{first}/detach-audio").json())[0]["id"]
    owner.patch(f"/api/sequences/{sid}/clips/{first}/move", json={"timeline_start": 30})
    mate.patch(f"/api/sequences/{sid}/clips/{audio}/gain", json={"gain": 0.2, "muted": False})

    refused = owner.post(f"/api/sequences/{sid}/undo?mine=true")
    assert refused.status_code == 409, refused.text
    assert "mate" in refused.json()["detail"]["message"]
