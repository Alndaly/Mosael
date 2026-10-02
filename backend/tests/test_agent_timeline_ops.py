"""智能体能做的时间线操作补齐:同一段连剪几刀、一次铺一整条字幕、一次改一批字幕文字、轨道静音 / 闪避 / 独奏 /
锁定、撤销 / 重做。全都作为 edit_timeline 的操作,不新加工具(工具定义每轮重发,本机模型的兜底窗口已经很紧)。

## 现场

- 「把第 2–3 秒和第 8–9 秒剪掉」:逐条发 cut_clip_range,第一刀之后原片段换成了切出来的新片段,第二刀
  报「片段不存在」(审查探针 P9)。
- 「给这段加字幕」只能一条一条 insert_text_clip:N 条字幕 N 次撤销;「把字幕都改成英文」同理。
- 轨道静音、闪避、独奏、锁定,撤销 / 重做 —— 剪辑页有,智能体没有。
"""

from __future__ import annotations

from tests.test_edit_timeline_args import _approve, _open, _setup, _video


def _track(state: dict, kind: str) -> dict:
    return next(track for track in state["tracks"] if track["kind"] == kind)


def test_同一段上连剪两刀_一次做完() -> None:
    client, ws, sid, clip = _setup()
    card = _open(client, ws, sid, [{
        "kind": "cut_clip_ranges_batch",
        "cuts": [{"clip_id": clip, "ranges": [{"src_start": 2, "src_end": 3}, {"src_start": 8, "src_end": 9}]}],
    }])
    assert card.status_code == 200, card.text
    pieces = _video(_approve(client, card.json()))
    assert [(one["src_in"], one["src_out"]) for one in pieces] == [(0, 2), (3, 8), (9, 10)]
    assert sum(one["src_out"] - one["src_in"] for one in pieces) == 8


def test_一次铺一整条字幕_一次改一批文字_各是一步撤销() -> None:
    client, ws, sid, _clip = _setup()
    state = client.post(f"/api/sequences/{sid}/tracks", json={"kind": "subtitle"}).json()
    subtitle = _track(state, "subtitle")["id"]
    state = _approve(client, _open(client, ws, sid, [{
        "kind": "generate_subtitles", "track_id": subtitle,
        "cues": [{"text": "你好", "timeline_start": 0, "duration": 1.5}, {"text": "再见", "timeline_start": 2, "duration": 1}],
    }]).json())
    cues = _track(state, "subtitle")["clips"]
    assert [cue["text_override"] for cue in cues] == ["你好", "再见"]

    state = _approve(client, _open(client, ws, sid, [{
        "kind": "set_clip_texts_batch", "texts": [{"clip_id": cues[0]["id"], "text": "Hello"}, {"clip_id": cues[1]["id"], "text": "Bye"}],
    }]).json())
    assert [cue["text_override"] for cue in _track(state, "subtitle")["clips"]] == ["Hello", "Bye"]

    undone = client.post(f"/api/sequences/{sid}/undo").json()
    assert [cue["text_override"] for cue in _track(undone, "subtitle")["clips"]] == ["你好", "再见"], "一批改文字一步撤回"


def test_轨道静音闪避独奏锁定() -> None:
    client, ws, sid, _clip = _setup()
    audio = _track(client.get(f"/api/sequences/{sid}").json(), "audio")["id"]
    state = _approve(client, _open(client, ws, sid, [
        {"kind": "set_track_state", "track_id": audio, "muted": True, "duck": True},
        {"kind": "set_track_state", "track_id": audio, "solo": True, "locked": True},
    ]).json())
    track = _track(state, "audio")
    assert (track["muted"], track["duck"], track["solo"], track["locked"]) == (True, True, True, True)


def test_字幕轨不能静音_开卡时就说() -> None:
    client, ws, sid, _clip = _setup()
    state = client.post(f"/api/sequences/{sid}/tracks", json={"kind": "subtitle"}).json()
    refused = _open(client, ws, sid, [{"kind": "set_track_state", "track_id": _track(state, "subtitle")["id"], "muted": True}])
    assert refused.status_code >= 400 and "set_track_state" in refused.text


def test_撤销重做() -> None:
    client, ws, sid, clip = _setup()
    _approve(client, _open(client, ws, sid, [{"kind": "set_clip_gain", "clip_id": clip, "gain": 0.4}]).json())
    revision = client.get(f"/api/sequences/{sid}").json()["revision"]

    undone = _approve(client, _open(client, ws, sid, [{"kind": "undo", "expected_revision": revision}]).json())
    assert _video(undone)[0]["gain"] == 1.0
    redone = _approve(client, _open(client, ws, sid, [{"kind": "redo"}]).json())
    assert _video(redone)[0]["gain"] == 0.4


def test_撤销带的版本号已经过时_开卡时就拒() -> None:
    client, ws, sid, clip = _setup()
    revision = client.get(f"/api/sequences/{sid}").json()["revision"]
    client.patch(f"/api/sequences/{sid}/clips/{clip}/gain", json={"gain": 0.4, "muted": False})  # 用户刚在剪辑页改了一下

    refused = _open(client, ws, sid, [{"kind": "undo", "expected_revision": revision}])
    assert refused.status_code >= 400, refused.text
    assert _video(client.get(f"/api/sequences/{sid}").json())[0]["gain"] == 0.4, "用户那一步没被撤"
