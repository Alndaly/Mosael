"""智能体的 inspect_sequence 和工作流的「看一眼时间线」读同一份,而且说的是实话。

## 现场(审查实测)

- 智能体那份把片段时长算成 `src_out - src_in`:2 倍速的 10 秒素材在时间线上占 5 秒,它报 10 秒,总时长也跟着错。
- 不给 src_in / src_out / speed —— 「把这段的第 3 秒切开」要的是素材时间,模型只能猜。
- 看不出哪段静音了、哪条轨在闪避 / 独奏 / 锁着;脱机片段和字幕条都显示成 `asset: null`。
- 工作流那份按速度算对了时长,却不带字幕的文字 —— 两份各错各的。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Workflow
from app.domain.workflows.executors import get_executor
from tests.util import fresh_client, insert_asset


def _setup():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sequence = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()
    sid = sequence["id"]
    video = next(track for track in sequence["tracks"] if track["kind"] == "video")["id"]
    audio = next(track for track in sequence["tracks"] if track["kind"] == "audio")["id"]
    kept = insert_asset(ws, kind="video", name="kept.mp4", file_key="x", media_info={"duration": 20})
    gone = insert_asset(ws, kind="video", name="gone.mp4", file_key="", media_info={"duration": 20})
    state = client.post(f"/api/sequences/{sid}/clips",
                        json={"track_id": video, "asset_id": kept, "timeline_start": 0, "src_in": 2, "src_out": 12}).json()
    fast = next(track for track in state["tracks"] if track["kind"] == "video")["clips"][0]["id"]
    client.patch(f"/api/sequences/{sid}/clips/{fast}/speed", json={"speed": 2})
    client.patch(f"/api/sequences/{sid}/clips/{fast}/gain", json={"gain": 0.5, "muted": True})
    client.post(f"/api/sequences/{sid}/clips",
                json={"track_id": video, "asset_id": gone, "timeline_start": 6, "src_in": 0, "src_out": 4})
    assert client.delete(f"/api/assets/{gone}").status_code in (200, 204)
    client.patch(f"/api/sequences/{sid}/tracks/{audio}", json={"duck": True, "solo": True, "locked": True})
    state = client.post(f"/api/sequences/{sid}/tracks", json={"kind": "subtitle"}).json()
    subtitle = next(track for track in state["tracks"] if track["kind"] == "subtitle")["id"]
    client.post(f"/api/sequences/{sid}/text-clips",
                json={"track_id": subtitle, "text": "你好", "timeline_start": 1, "duration": 2})
    return client, ws, sid, fast


def _agent_view(client, sid: str) -> dict:
    import mcp_server

    me = client.get("/api/auth/me").json()["id"]
    with mcp_server.calling_as(user_id=me):
        return mcp_server.inspect_sequence(sequence_id=sid)


def _workflow_view(ws: str, sid: str) -> dict:
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="W", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        return get_executor("inspect_sequence")(db, workflow, {"sequence_id": sid})


def _clips(view: dict, kind: str) -> list[dict]:
    return next(track for track in view["tracks"] if track["kind"] == kind)["clips"]


def test_智能体和工作流读的是同一份() -> None:
    client, ws, sid, _fast = _setup()
    agent, workflow = _agent_view(client, sid), _workflow_view(ws, sid)
    assert workflow == {key: agent[key] for key in workflow}, "工作流交出的每一项都和智能体看到的一样"
    assert set(workflow) >= {"tracks", "duration", "revision"}


def test_时长按速度算_给出素材区间速度和音量() -> None:
    client, _ws, sid, fast = _setup()
    view = _agent_view(client, sid)
    clip = next(one for one in _clips(view, "video") if one["clip_id"] == fast)
    assert clip["duration"] == 5.0, "10 秒素材 2 倍速,在时间线上占 5 秒"
    assert (clip["src_in"], clip["src_out"], clip["speed"]) == (2, 12, 2)
    assert (clip["gain"], clip["muted"]) == (0.5, True)
    assert clip["asset"] == "kept.mp4"
    assert view["duration"] == 10.0, "脱机那段 6–10 秒,总长按时间线上的算"


def test_脱机片段和字幕条分得开() -> None:
    client, _ws, sid, _fast = _setup()
    view = _agent_view(client, sid)
    offline = next(one for one in _clips(view, "video") if one.get("offline"))
    assert offline["asset"] == "gone.mp4"
    cue = _clips(view, "subtitle")[0]
    assert cue["text"] == "你好" and "offline" not in cue and "asset" not in cue


def test_轨道的声音状态和锁() -> None:
    client, _ws, sid, _fast = _setup()
    audio = next(track for track in _agent_view(client, sid)["tracks"] if track["kind"] == "audio")
    assert (audio["muted"], audio["duck"], audio["solo"], audio["locked"]) == (False, True, True, True)


def test_链接组给出来_模型知道哪几段会一起动() -> None:
    client, _ws, sid, fast = _setup()
    client.post(f"/api/sequences/{sid}/clips/{fast}/detach-audio")
    view = _agent_view(client, sid)
    picture = next(one for one in _clips(view, "video") if one["clip_id"] == fast)
    sound = next(one for one in _clips(view, "audio") if one.get("link_group"))
    assert picture["link_group"] == sound["link_group"]
    assert "link_group" not in next(one for one in _clips(view, "video") if one.get("offline")), "没链接的不带这一项"
