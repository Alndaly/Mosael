"""智能体的 edit_timeline 补上三件剪辑页早就能做的事:复制片段、替换媒体、加轨道时指定第几行。

## 现场

- 「把这段复制一份放到后面」:剪辑页的复制(深拷贝,速度 / 调色 / 关键帧 / 花字文字都带过去)早有了,
  智能体只能拿 insert_clip 去凑 —— 带得过去的只有素材和出入点,字幕和花字(没有素材)根本插不进去。
- 「把这段换成降噪后的那份」:剪辑页有片段级「替换媒体」,智能体只能删掉再插,这一段上做过的调整全丢。
- 「加一条音频轨放在最上面」:加轨道的接口能指定行号,edit_timeline 的 add_track 没有这个参数。

当时卡在工具定义的预算上(见 test_tool_definitions_budget):本机回退窗口 32K 已被工具定义占满。

这里每一条都走**智能体真实的执行入口** —— sidecar 发的那个请求(POST /api/agent/tools/edit_timeline,带这次
对话的 turn 令牌)开卡,用户在对话里点批准落地;越权和写错的入参在开卡时就拒;撤销一步回到原样。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.core.security import mint_service_session
from app.db.models import SequenceOperation, ToolConfirmation, User
from tests.util import fresh_client, insert_asset, second_client


class Agent:
    """一个人、一个工作区、一条有一段视频的时间线,和他这次对话的 turn 令牌 —— 智能体开卡用的就是它。"""

    def __init__(self, client=None, username: str = "tester") -> None:
        self.client = client or fresh_client()
        self.workspace_id = self.client.post("/api/workspaces", json={"name": f"W-{username}"}).json()["id"]
        project = self.client.post("/api/projects", json={"workspace_id": self.workspace_id, "name": "P"}).json()["id"]
        sequence = self.client.post(
            "/api/sequences", json={"workspace_id": self.workspace_id, "project_id": project, "name": "S"}
        ).json()
        self.sequence_id = sequence["id"]
        self.video_track = next(track for track in sequence["tracks"] if track["kind"] == "video")["id"]
        self.asset_id = insert_asset(self.workspace_id, kind="video", name="v", file_key="v.mp4", media_info={"duration": 20})
        state = self.client.post(
            f"/api/sequences/{self.sequence_id}/clips",
            json={"track_id": self.video_track, "asset_id": self.asset_id, "timeline_start": 0, "src_in": 0, "src_out": 10},
        ).json()
        self.clip_id = self.clips(state)[0]["id"]
        session = self.client.post("/api/agent/sessions", json={"home": {"kind": "studio"}, "workspace_id": self.workspace_id, "title": "T"}).json()["id"]
        with SessionLocal() as db:
            user = db.query(User).filter(User.username == username).one()
            self.turn_token = mint_service_session(db, user.id, agent_session_id=session)

    def edit(self, operations: list[dict], *, sequence_id: str | None = None) -> dict:
        """智能体调 edit_timeline —— 和 sidecar 发的是同一个请求。返回工具结果(开了卡是 result,被拒是 error)。"""
        response = self.client.post(
            "/api/agent/tools/edit_timeline",
            json={
                "arguments": {
                    "sequence_id": sequence_id or self.sequence_id,
                    "operations": operations,
                    "workspace_id": self.workspace_id,
                },
                "requested_by": "pi",
            },
            headers={"Authorization": f"Bearer {self.turn_token}"},
        )
        assert response.status_code == 200, response.text
        return response.json()

    def approve(self, reply: dict) -> dict:
        """用户在对话里点批准。返回批准之后的整条时间线。"""
        assert "result" in reply, reply.get("error")
        approved = self.client.post(f"/api/confirmations/{reply['result']['confirmation_id']}/approve").json()
        assert approved["status"] == "executed", approved.get("error")
        return self.state()

    def state(self) -> dict:
        return self.client.get(f"/api/sequences/{self.sequence_id}").json()

    def undo(self) -> dict:
        undone = self.client.post(f"/api/sequences/{self.sequence_id}/undo")
        assert undone.status_code == 200, undone.text
        return undone.json()

    def clips(self, state: dict, track_id: str | None = None) -> list[dict]:
        track = next(one for one in state["tracks"] if one["id"] == (track_id or self.video_track))
        return sorted(track["clips"], key=lambda clip: clip["timeline_start"])


def _refused(reply: dict, *needles: str) -> None:
    """开卡时就拒:工具回的是 error、卡根本没开 —— 不是开出来、批了、再失败。"""
    assert "error" in reply and "result" not in reply, reply
    for needle in needles:
        assert needle in reply["error"], reply["error"]
    with SessionLocal() as db:
        assert db.query(ToolConfirmation).count() == 0, "被拒的编辑不该留下一张卡"


def _operation_count(sequence_id: str) -> int:
    with SessionLocal() as db:
        return db.query(SequenceOperation).filter_by(sequence_id=sequence_id).count()


# —— duplicate_clips ——


def test_复制片段_属性照原样接在后面_一步撤销() -> None:
    agent = Agent()
    agent.client.patch(f"/api/sequences/{agent.sequence_id}/clips/{agent.clip_id}/gain", json={"gain": 0.4, "muted": False})
    before = agent.state()
    steps = _operation_count(agent.sequence_id)

    state = agent.approve(agent.edit([{"kind": "duplicate_clips", "clip_ids": [agent.clip_id]}]))

    original, copy = agent.clips(state)
    assert copy["id"] != original["id"]
    assert copy["timeline_start"] == 10, "不给起点就紧接在原片段之后"
    assert (copy["asset_id"], copy["src_in"], copy["src_out"], copy["gain"]) == (agent.asset_id, 0, 10, 0.4)
    assert _operation_count(agent.sequence_id) == steps + 1, "一次复制是一步"

    undone = agent.undo()
    assert [clip["id"] for clip in agent.clips(undone)] == [clip["id"] for clip in agent.clips(before)]


def test_复制别人时间线上的片段_开卡就拒() -> None:
    """片段 id 拿得到不等于动得了:点名的片段必须在这条时间线上(别人的、别的工作区的一律当不存在)。"""
    owner = Agent()
    stranger = Agent(client=second_client("other"), username="other")
    reply = stranger.edit([{"kind": "duplicate_clips", "clip_ids": [owner.clip_id]}])
    _refused(reply, "duplicate_clips", "Clip not found")
    assert len(owner.clips(owner.state())) == 1


def test_复制的入参写错_开卡就拒并给出写法() -> None:
    agent = Agent()
    _refused(agent.edit([{"kind": "duplicate_clips", "clip_ids": []}]), "clip_ids", "duplicate_clips(clip_ids")
    _refused(agent.edit([{"kind": "duplicate_clips", "clip_id": agent.clip_id}]), "unknown argument 'clip_id'")
    _refused(agent.edit([{"kind": "duplicate_clips", "clip_ids": [agent.clip_id], "timeline_start": -1}]), "timeline_start")


# —— replace_clip_media ——


def test_替换媒体_片段留在原地_一步撤销() -> None:
    agent = Agent()
    cleaned = insert_asset(agent.workspace_id, kind="video", name="v-denoised", file_key="v2.mp4", media_info={"duration": 20})
    before = agent.clips(agent.state())[0]

    state = agent.approve(agent.edit([{"kind": "replace_clip_media", "clip_ids": [agent.clip_id], "asset_id": cleaned}]))

    after = agent.clips(state)[0]
    assert after["asset_id"] == cleaned
    assert (after["id"], after["timeline_start"], after["src_in"], after["src_out"]) == (
        before["id"], before["timeline_start"], before["src_in"], before["src_out"]
    ), "换的只是放的哪份素材"

    assert agent.clips(agent.undo())[0]["asset_id"] == agent.asset_id


def test_换成别的工作区的素材_开卡就拒() -> None:
    """素材 id 拿得到不等于用得了:别人工作区的素材不能借一张卡挪进自己的时间线。"""
    owner = Agent()
    stranger = Agent(client=second_client("other"), username="other")
    reply = stranger.edit([{"kind": "replace_clip_media", "clip_ids": [stranger.clip_id], "asset_id": owner.asset_id}])
    _refused(reply, "replace_clip_media", "Asset not found")
    assert stranger.clips(stranger.state())[0]["asset_id"] == stranger.asset_id


def test_替换媒体的入参不对_开卡就拒() -> None:
    agent = Agent()
    _refused(agent.edit([{"kind": "replace_clip_media", "clip_ids": [agent.clip_id]}]), "missing 'asset_id'")
    voice = insert_asset(agent.workspace_id, kind="audio", name="a", file_key="a.wav", media_info={"duration": 20})
    _refused(agent.edit([{"kind": "replace_clip_media", "clip_ids": [agent.clip_id], "asset_id": voice}]), "replace_clip_media", "audio")
    short = insert_asset(agent.workspace_id, kind="video", name="short", file_key="s.mp4", media_info={"duration": 3})
    _refused(agent.edit([{"kind": "replace_clip_media", "clip_ids": [agent.clip_id], "asset_id": short}]), "replace_clip_media", "3.0")


# —— add_track 的 index ——


def test_加轨道放在指定的那一行_一步撤销() -> None:
    agent = Agent()
    before = [(track["id"], track["position"]) for track in agent.state()["tracks"]]

    state = agent.approve(agent.edit([{"kind": "add_track", "track_kind": "audio", "index": 0}]))

    rows = sorted(state["tracks"], key=lambda track: track["position"])
    assert rows[0]["kind"] == "audio" and rows[0]["id"] not in dict(before), "新轨在第 0 行"
    assert [track["id"] for track in rows[1:]] == [one for one, _ in sorted(before, key=lambda pair: pair[1])]

    undone = agent.undo()
    assert [(track["id"], track["position"]) for track in undone["tracks"]] == before


def test_别人对我的时间线加轨道_开卡就拒() -> None:
    owner = Agent()
    stranger = Agent(client=second_client("other"), username="other")
    reply = stranger.edit([{"kind": "add_track", "track_kind": "video", "index": 0}], sequence_id=owner.sequence_id)
    _refused(reply, "Sequence not found")
    assert len(owner.state()["tracks"]) == 2


def test_行号越界或是负数_开卡就拒() -> None:
    agent = Agent()
    _refused(agent.edit([{"kind": "add_track", "track_kind": "video", "index": -1}]), "index")
    # 现在只有两条轨:能放的行是 0、1、2,99 只有照着这条时间线做一遍才知道不行 —— 开卡时的试做就拒了。
    _refused(agent.edit([{"kind": "add_track", "track_kind": "video", "index": 99}]), "add_track")


# —— 并发足迹 ——


def test_三种新操作的并发足迹_和剪辑页那条路是同一份() -> None:
    """edit_timeline 认出来的请求体和剪辑页路由造的是同一个领域 dataclass,concurrency 判「能不能交换」用的足迹
    也就是同一份:复制和加轨道依赖坐标(放下会覆盖邻居、插一行会挪别的轨),换素材不依赖坐标、只碰点名的片段
    (用到哪份素材不算「碰」—— 两段片段用同一份素材互不相干)。"""
    from app.domain.sequences.concurrency import Footprint, footprint_of_request
    from app.domain.sequences.operations import parse_edit_operations

    parsed = dict(parse_edit_operations([
        {"kind": "duplicate_clips", "clip_ids": ["c1", "c2"], "track_id": "t1"},
        {"kind": "replace_clip_media", "clip_ids": ["c1"], "asset_id": "a9"},
        {"kind": "add_track", "track_kind": "audio", "index": 0},
    ]))
    footprints = {kind: footprint_of_request(args.to_request("u")) for kind, args in parsed.items()}
    assert footprints["duplicate_clips"] == Footprint(coordinate_free=False, ids=frozenset({"c1", "c2", "t1"}))
    assert footprints["replace_clip_media"] == Footprint(coordinate_free=True, ids=frozenset({"c1"}))
    assert footprints["add_track"] == Footprint(coordinate_free=False, ids=frozenset())
