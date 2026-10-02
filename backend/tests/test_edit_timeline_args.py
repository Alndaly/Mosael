"""智能体的 edit_timeline:每种操作的参数按模型认,开卡时就照着现在的时间线做一遍,说明从模型生成。

## 现场(审查实测,照工具说明的参数名下单)

- `split_clip(clip_id, at)`:说明写 `at`,真实参数是 `src_time` —— TypeError。
- `set_sequence_reframe(..., fit)`:说明写 `fit`,真实是 `fill_mode` —— TypeError。
- `move_clips_batch(moves: [{clip_id, timeline_start}])`:moves 原样是字典,领域要 ClipMove —— AttributeError。
- `set_clip_gain(clip_id, muted)`:只给 muted —— 缺参数崩。数字给成字符串 —— 比大小时 TypeError。
- 而这些全都**开卡成功**,等用户批准之后才炸:卡开出来了,批了,失败。
"""

from __future__ import annotations

import asyncio
import math

import pytest

from app.core.db import SessionLocal
from app.db.models import Sequence, SequenceOperation, ToolConfirmation
from tests.util import fresh_client, insert_asset


def _setup():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sequence = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()
    video = next(track for track in sequence["tracks"] if track["kind"] == "video")["id"]
    asset = insert_asset(ws, kind="video", name="v", file_key="x", media_info={"duration": 20})
    state = client.post(
        f"/api/sequences/{sequence['id']}/clips",
        json={"track_id": video, "asset_id": asset, "timeline_start": 0, "src_in": 0, "src_out": 10},
    ).json()
    clip = next(track for track in state["tracks"] if track["kind"] == "video")["clips"][0]["id"]
    return client, ws, sequence["id"], clip


def _open(client, ws: str, sid: str, operations: list[dict]):
    return client.post(
        "/api/confirmations",
        json={"workspace_id": ws, "tool": "edit_timeline", "payload": {"sequence_id": sid, "operations": operations}},
    )


def _approve(client, card: dict) -> dict:
    approved = client.post(f"/api/confirmations/{card['id']}/approve").json()
    assert approved["status"] == "executed", approved.get("error")
    return client.get(f"/api/sequences/{approved['payload']['sequence_id']}").json()


def _video(state: dict) -> list[dict]:
    return next(track for track in state["tracks"] if track["kind"] == "video")["clips"]


@pytest.mark.parametrize(
    ("operation", "wrong", "right"),
    [
        ({"kind": "split_clip", "at": 5.0}, "'at'", "split_clip*(clip_id, src_time)"),
        ({"kind": "set_sequence_reframe", "width": 1080, "height": 1920, "fit": "cover"}, "'fit'", "fill_mode"),
    ],
)
def test_照旧说明的参数名下单_开卡就拒_并给出正确写法(operation, wrong, right) -> None:
    client, ws, sid, clip = _setup()
    operation = {**operation, "clip_id": clip} if operation["kind"] == "split_clip" else operation
    refused = _open(client, ws, sid, [operation])
    assert refused.status_code >= 400, refused.text
    assert wrong in refused.text and right in refused.text
    with SessionLocal() as db:
        assert db.query(ToolConfirmation).count() == 0, "没开卡"


def test_move_clips_batch_的条目是字典_照样能做() -> None:
    client, ws, sid, clip = _setup()
    card = _open(client, ws, sid, [{"kind": "move_clips_batch", "moves": [{"clip_id": clip, "timeline_start": 4}]}])
    assert card.status_code == 200, card.text
    assert _video(_approve(client, card.json()))[0]["timeline_start"] == 4


def test_set_clip_gain_只给muted_音量不变() -> None:
    client, ws, sid, clip = _setup()
    _approve(client, _open(client, ws, sid, [{"kind": "set_clip_gain", "clip_id": clip, "gain": 0.5}]).json())
    state = _approve(client, _open(client, ws, sid, [{"kind": "set_clip_gain", "clip_id": clip, "muted": True}]).json())
    assert _video(state)[0]["muted"] is True
    assert _video(state)[0]["gain"] == 0.5, "只说了静音,音量不该被改回 1"


def test_数字给成字符串照样认_非有限数当场拒() -> None:
    client, ws, sid, clip = _setup()
    card = _open(client, ws, sid, [{"kind": "set_clip_speed", "clip_id": clip, "speed": "1.5"}])
    assert card.status_code == 200, card.text
    assert card.json()["payload"]["operations"][0]["speed"] == 1.5, "卡上存的是认过的那一份"
    assert _video(_approve(client, card.json()))[0]["speed"] == 1.5

    for bad in ("NaN", "Infinity", "-inf"):
        refused = _open(client, ws, sid, [{"kind": "move_clip", "clip_id": clip, "timeline_start": bad}])
        assert refused.status_code >= 400, f"{bad!r} 开了卡"
    # 进程内的智能体工具直接递 Python 对象,真的 inf 也到得了这里。
    from app.domain.sequences.errors import SequenceDomainError
    from app.domain.sequences.operations import parse_edit_operations

    with pytest.raises(SequenceDomainError, match="timeline_start"):
        parse_edit_operations([{"kind": "move_clip", "clip_id": clip, "timeline_start": math.inf}])


def test_开卡时照现在的时间线做一遍_做不了就不开卡_说清第几条() -> None:
    client, ws, sid, clip = _setup()
    with SessionLocal() as db:
        before = db.get(Sequence, sid).revision
    refused = _open(client, ws, sid, [
        {"kind": "set_clip_gain", "clip_id": clip, "gain": 0.5},
        {"kind": "split_clip", "clip_id": clip, "src_time": 99},  # 切点在片段外面
    ])
    assert refused.status_code >= 400, refused.text
    assert "2" in refused.text and "split_clip" in refused.text
    with SessionLocal() as db:
        assert db.get(Sequence, sid).revision == before, "试做的那一遍回滚干净了"
        assert db.query(SequenceOperation).filter_by(sequence_id=sid).count() == 1, "没有留下操作记录"
    assert _video(client.get(f"/api/sequences/{sid}").json())[0]["gain"] == 1.0


def test_试做不留痕迹_卡照常开_批准后才真的做() -> None:
    client, ws, sid, clip = _setup()
    card = _open(client, ws, sid, [{"kind": "set_clip_gain", "clip_id": clip, "gain": 0.3}])
    assert card.status_code == 200, card.text
    state = client.get(f"/api/sequences/{sid}").json()
    assert _video(state)[0]["gain"] == 1.0 and state["revision"] == 2
    after = _approve(client, card.json())
    assert _video(after)[0]["gain"] == 0.3 and after["revision"] == 3


def test_批准之后的编辑算在批准的人头上() -> None:
    client, ws, sid, clip = _setup()
    _approve(client, _open(client, ws, sid, [{"kind": "set_clip_gain", "clip_id": clip, "gain": 0.3}]).json())
    me = client.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        last = db.query(SequenceOperation).filter_by(sequence_id=sid).order_by(SequenceOperation.revision_after.desc()).first()
        assert last.actor_id == me


def test_请求体里的actor_id_冒充不了() -> None:
    client, ws, sid, clip = _setup()
    refused = _open(client, ws, sid, [{"kind": "set_clip_gain", "clip_id": clip, "gain": 0.3, "actor_id": "someone"}])
    assert refused.status_code >= 400 and "actor_id" in refused.text


def test_说明从模型生成_参数名和校验是同一份() -> None:
    import mcp_server

    from app.domain.sequences.operations import EDIT_OP_KINDS

    doc = next(t for t in asyncio.run(mcp_server.mcp.list_tools()) if t.name == "edit_timeline").description
    assert "split_clip*(clip_id, src_time)" in doc, "作用于链接组的标 *,linked 开关在开头说一次"
    assert "linked:false" in doc
    assert "fill_mode?:cover|contain|blur" in doc
    assert "moves:[{clip_id, timeline_start, track_id?}]" in doc
    assert "split_clip (clip_id, at)" not in doc and "fit" not in doc
    assert all(f"{kind}(" in doc or f"{kind}*(" in doc for kind in EDIT_OP_KINDS)


def test_链接组_插入倍速_变速推不推开都说得出() -> None:
    """时间线这一侧有的开关,智能体也发得出:临时解链、插入时就给倍速、变速时后面的跟不跟。"""
    client, ws, sid, clip = _setup()
    state = client.post(f"/api/sequences/{sid}/clips/{clip}/detach-audio").json()
    audio = next(track for track in state["tracks"] if track["kind"] == "audio")["clips"][0]

    alone = _approve(client, _open(client, ws, sid, [{"kind": "move_clip", "clip_id": clip, "timeline_start": 3, "linked": False}]).json())
    assert _video(alone)[0]["timeline_start"] == 3
    assert next(track for track in alone["tracks"] if track["kind"] == "audio")["clips"][0]["timeline_start"] == audio["timeline_start"]

    video = next(track for track in state["tracks"] if track["kind"] == "video")["id"]
    asset = _video(state)[0]["asset_id"]
    fast = _approve(client, _open(client, ws, sid, [
        {"kind": "insert_clip", "track_id": video, "asset_id": asset, "timeline_start": 20, "src_out": 4, "speed": 2},
    ]).json())
    assert next(one for one in _video(fast) if one["timeline_start"] == 20)["speed"] == 2

    refused = _open(client, ws, sid, [{"kind": "set_clip_speed", "clip_id": clip, "speed": 0.25, "ripple": False}])
    assert refused.status_code >= 400, "慢放会盖住后面那段、又说了不推开 —— 开卡时就该知道做不了"
