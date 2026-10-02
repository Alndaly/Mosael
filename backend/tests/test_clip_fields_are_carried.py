"""Clip 的每个可写列,切分 / 剪段 / 撤销重建 / 复制序列时都跟着走。

片段被「重建」的地方有好几处:切开的两段、剪掉中间后留下的几段、覆盖切开的邻居、撤销还回来的那一段、
复制出来的整条序列。每一处都只搬它知道的字段,于是 Clip 加一列,就得同时记得改这几处 —— `offline_asset`
就是这样丢的:切开一个脱机片段,两段都成了 asset_id 为空、又没有脱机标记的东西,导出前的脱机
检查认不出它们,成片静默地少一段;复制序列则另有一张手写的字段表。

这条棘轮让「加列」自己说出来:新列要么进 INHERITED_CLIP_FIELDS / RESTORABLE_CLIP_FIELDS,要么在
下面写明为什么都不进。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

from sqlalchemy import inspect as sa_inspect

from app.core.db import SessionLocal
from app.db.models import Clip, Project, Sequence
from app.domain.render import build_plan_for_sequence
from app.domain.sequences import copy_sequence
from app.domain.sequences._timeline import INHERITED_CLIP_FIELDS, RESTORABLE_CLIP_FIELDS
from app.media.render_plan import RenderPlanError
from tests.util import fresh_client, insert_asset

#: 两张表都不收的列 → 为什么。位置与身份每处都单独写(切出来的一段有它自己的位置),时间戳是行自己的。
NOT_CARRIED = {
    "id": "身份:切出来的是新行;撤销重建按记录里的 clip_id 单独写",
    "workspace_id": "归属:取自序列,不取自原片段",
    "sequence_id": "归属:取自序列,不取自原片段",
    "track_id": "位置:每处单独写(移动、跨轨)",
    "asset_id": "位置之一:每处单独写;素材已删时重建成脱机占位(见 undo/rows)",
    "timeline_start": "位置:每处单独算",
    "src_in": "位置:每处单独算",
    "src_out": "位置:每处单独算",
    "created_at": "行自己的时间戳",
    "updated_at": "行自己的时间戳",
}


def test_片段的每个可写列都有去处() -> None:
    columns = {column.key for column in sa_inspect(Clip).columns}
    unaccounted = columns - set(INHERITED_CLIP_FIELDS) - set(RESTORABLE_CLIP_FIELDS) - set(NOT_CARRIED)
    assert not unaccounted, (
        f"Clip 的这些列切分 / 撤销重建 / 复制时会丢:{sorted(unaccounted)}。"
        "放进 _timeline 的 INHERITED_CLIP_FIELDS / RESTORABLE_CLIP_FIELDS,或者在 NOT_CARRIED 写明为什么不带。"
    )
    stale = set(NOT_CARRIED) - columns
    assert not stale, f"NOT_CARRIED 里有已经不存在的列:{sorted(stale)}"
    # 切出来的一段是「同一段素材的一部分」,能重建的它都该继承 —— 只有链接组例外:切出来的每一截和谁一组,
    # 由切它的那一步说(左半跟左半、右半跟右半,见 _timeline.INHERITED_CLIP_FIELDS)。
    assert set(RESTORABLE_CLIP_FIELDS) - set(INHERITED_CLIP_FIELDS) == {"link_group"}
    assert set(INHERITED_CLIP_FIELDS) <= set(RESTORABLE_CLIP_FIELDS)


def _offline_clip():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sequence = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()
    track = next(t["id"] for t in sequence["tracks"] if t["kind"] == "video")
    gone = insert_asset(ws, kind="video", name="gone.mp4", file_key="", media_info={"duration": 10})
    state = client.post(
        f"/api/sequences/{sequence['id']}/clips",
        json={"track_id": track, "asset_id": gone, "timeline_start": 0, "src_in": 0, "src_out": 10},
    ).json()
    clip_id = next(t for t in state["tracks"] if t["kind"] == "video")["clips"][0]["id"]
    assert client.delete(f"/api/assets/{gone}").status_code == 204
    return client, sequence["id"], clip_id, gone


def _video(state: dict) -> list[dict]:
    return sorted(next(t for t in state["tracks"] if t["kind"] == "video")["clips"], key=lambda c: c["timeline_start"])


def test_切开脱机片段_两段仍是脱机_导出照样拦下() -> None:
    client, seq, clip_id, gone = _offline_clip()
    state = client.post(f"/api/sequences/{seq}/clips/{clip_id}/split", json={"src_time": 5}).json()
    pieces = _video(state)
    assert len(pieces) == 2 and all(piece["offline_asset"]["asset_id"] == gone for piece in pieces)
    with SessionLocal() as db:
        try:
            build_plan_for_sequence(db, seq)
        except RenderPlanError as exc:
            assert "gone.mp4" in str(exc)
        else:
            raise AssertionError("切开的脱机片段被当成了空白,导出没有拦下")


def test_剪掉脱机片段的中间_留下的几段和撤销还回的那段都是脱机() -> None:
    client, seq, clip_id, gone = _offline_clip()
    state = client.post(
        f"/api/sequences/{seq}/clips/{clip_id}/cut-ranges", json={"ranges": [{"src_start": 3, "src_end": 6}]}
    ).json()
    assert all(piece["offline_asset"]["asset_id"] == gone for piece in _video(state))
    restored = _video(client.post(f"/api/sequences/{seq}/undo").json())
    assert [piece["id"] for piece in restored] == [clip_id]
    assert restored[0]["offline_asset"]["name"] == "gone.mp4"


def test_复制序列带走片段的全部属性_且与原片互不影响() -> None:
    client, seq, clip_id, gone = _offline_clip()
    assert client.patch(f"/api/sequences/{seq}/clips/{clip_id}/transform", json={"transform": {"scale": 2}}).status_code == 200
    with SessionLocal() as db:
        source = db.get(Sequence, seq)
        copy = copy_sequence(db, source, db.get(Project, source.project_id), name="copy")
        db.commit()
        copied = next(clip for track in copy.tracks for clip in track.clips)
        original = db.get(Clip, clip_id)
        for field in RESTORABLE_CLIP_FIELDS:
            assert getattr(copied, field) == getattr(original, field), field
        assert copied.offline_asset["asset_id"] == gone
        copied.transform["scale"] = 3  # 原地改副本的 JSON
        assert original.transform["scale"] == 2
