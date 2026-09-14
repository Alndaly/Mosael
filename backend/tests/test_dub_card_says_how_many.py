"""配音确认卡要说清**几条** —— 那是一次花钱的动作,量级不能靠模型那句话捎带。

卡上此前写的是「给整条字幕轨配音」。「整条轨」说清了范围,却没说量级:3 条和 300 条
在这张卡上长得一模一样,而卡右上角挂着「AI 成本」。

**这里有两个不同的零。** `len(clip_ids) == 0` 的意思是「没点名 = 整条轨」,不是「零条字幕」——
所以此前不敢写「0 条」,退回了「整条字幕轨」。那一退把量级也丢了。真去数一遍就没有这个歧义:
零就是真的零。

数的时候用的是**执行时的那一个函数**(`subtitle_clip_ids`)。另写一遍「怎么算整条轨」的话,
两份实现迟早分叉,而分叉了没有任何地方会报错 —— 用户看到的条数和真正配的条数不一样,
只有账单知道。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import User
from app.domain.agent.confirmations import request_confirmation
from tests.util import fresh_client


def _sequence_with_cues(client, texts: list[str]) -> tuple[str, str, str]:
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": workspace["id"], "name": "P"}).json()
    sequence = client.post(
        "/api/sequences",
        json={"workspace_id": workspace["id"], "project_id": project["id"], "name": "S"},
    ).json()
    tracks = client.post(f"/api/sequences/{sequence['id']}/tracks", json={"kind": "subtitle"}).json()
    track_id = next(t["id"] for t in tracks["tracks"] if t["kind"] == "subtitle")
    for index, text in enumerate(texts):
        client.post(
            f"/api/sequences/{sequence['id']}/text-clips",
            json={"track_id": track_id, "text": text, "timeline_start": 1.0 + index * 4, "duration": 3.0},
        )
    return workspace["id"], sequence["id"], track_id


def _card(db, workspace_id: str, payload: dict) -> str:
    user = db.scalars(__import__("sqlalchemy").select(User)).first()
    return request_confirmation(
        db, workspace_id=workspace_id, tool="dub_subtitles", payload=payload, requested_by=user.id
    ).summary


def test_没点名条目时_卡上要写出整条轨有几条() -> None:
    client = fresh_client()
    ws, sequence_id, track_id = _sequence_with_cues(client, ["一", "二", "三"])
    with SessionLocal() as db:
        summary = _card(db, ws, {"sequence_id": sequence_id, "track_id": track_id, "clip_ids": []})
    assert "3 条字幕" in summary, summary
    # 范围和后果照旧要说清。
    assert "压回原段落长度" in summary and "原声不动" in summary


def test_点名了条目就按点名的数() -> None:
    client = fresh_client()
    ws, sequence_id, track_id = _sequence_with_cues(client, ["一", "二", "三"])
    seq = client.get(f"/api/sequences/{sequence_id}").json()
    clips = next(t["clips"] for t in seq["tracks"] if t["id"] == track_id)
    with SessionLocal() as db:
        summary = _card(db, ws, {
            "sequence_id": sequence_id, "track_id": track_id, "clip_ids": [clips[0]["id"], clips[1]["id"]],
        })
    assert "2 条字幕" in summary, summary


def test_空轨就是真的零_这时写出来才是对的() -> None:
    client = fresh_client()
    ws, sequence_id, track_id = _sequence_with_cues(client, [])
    with SessionLocal() as db:
        summary = _card(db, ws, {"sequence_id": sequence_id, "track_id": track_id, "clip_ids": []})
    # 「没点名」的零和「真的一条都没有」的零是两件事;数过之后,后者写出来正是用户需要看到的。
    assert "0 条字幕" in summary, summary
