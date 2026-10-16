"""镜头表的存取和整条流程(domain/shots/breakdowns.py):量 → 取帧拼表 → 逐批判 → 落库。

量 + 取帧用 ffmpeg 现造的小片子(四段纯色,刀口在 1/2/3 秒);判画面用假的 `ask`(不碰网络)。
判据照 ADR 0061:一份视频一份表、重拆覆盖;一批失败不连坐;没配视觉模型时机器那一半照样交。
"""

from __future__ import annotations

import shutil
import subprocess
from uuid import uuid4
from pathlib import Path

import pytest
from PIL import Image

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.i18n import LocalizedError
from app.db.models import Asset, ShotBreakdown
from app.domain.shots import breakdowns, frames
from tests.util import fresh_client, insert_asset, wait_settled

HAS_FFMPEG = shutil.which("ffmpeg") is not None
pytestmark = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")


def _make_cut_video(target: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "color=c=red:s=320x180:r=25:d=1",
         "-f", "lavfi", "-i", "color=c=white:s=320x180:r=25:d=1",
         "-f", "lavfi", "-i", "color=c=black:s=320x180:r=25:d=1",
         "-f", "lavfi", "-i", "color=c=yellow:s=320x180:r=25:d=1",
         "-filter_complex", "[0:v][1:v][2:v][3:v]concat=n=4:v=1:a=0", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         str(target)],
        check=True, timeout=60,
    )


@pytest.fixture
def client():
    """整张库只在第一个用例前重置一次(fresh_client 会 drop 重建)。"""
    return fresh_client()


@pytest.fixture
def video_asset(client):
    """素材库里一份真实的 4 秒四刀口小片子。"""
    ws_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    media = settings.media_dir / "test-shots"
    media.mkdir(parents=True, exist_ok=True)
    source = media / f"cuts-{uuid4().hex[:8]}.mp4"
    _make_cut_video(source)
    asset_id = insert_asset(
        ws_id, kind="video", name="刀口样片",
        file_key=source.relative_to(settings.data_dir).as_posix(),
        media_info={"duration": 4.0, "width": 320, "height": 180, "fps": 25},
    )
    with SessionLocal() as db:
        yield db.get(Asset, asset_id)
    shutil.rmtree(media / "test-shots", ignore_errors=True)


# --------------------------------------------------------------------------------------
# measure_into:量 + 取帧 + 落库;重拆覆盖
# --------------------------------------------------------------------------------------

def test_measure_into_builds_breakdown_and_files(video_asset) -> None:
    with SessionLocal() as db:
        row = breakdowns.measure_into(
            db, video_asset, created_by=None, lang="zh",
            segments=[{"start": 0.2, "end": 0.9, "text": "开场"}],
        )
        db.commit()
        assert row.id and row.asset_id == video_asset.id
        assert len(row.cuts) == 3
        assert len(row.shots) == 4
        assert row.shots[0]["dialogue"] == "开场"
        assert row.meta["duration"] == pytest.approx(4.0, abs=0.2)
        assert row.sheets and row.sheets[0]["first"] == "S01" and row.sheets[0]["last"] == "S04"
        assert row.describe == {}
        folder = breakdowns.shots_dir(video_asset)
        for point in frames.FRAME_POINTS:
            assert (folder / "frames" / f"S01{point}.jpg").is_file()
            assert (folder / "sheets" / f"sheet-01{point}.jpg").is_file()


def test_sheet_file_only_serves_sheets_inside_the_asset_dir(video_asset) -> None:
    """联系表的文件名收窄(和帧图同一个理由):`shots/sheets/` 是素材目录里面的目录,
    名字任由调用方给就等于开了一条走出去的路。"""
    with SessionLocal() as db:
        breakdowns.measure_into(db, video_asset, created_by=None, lang="zh")
        db.commit()
    assert breakdowns.sheet_file(video_asset, "sheet-01a.jpg") is not None
    assert breakdowns.sheet_file(video_asset, "sheet-99b.jpg") is None  # 名字对但文件不在
    assert breakdowns.sheet_file(video_asset, "../../secret.jpg") is None
    assert breakdowns.sheet_file(video_asset, "sheet-1a.jpg") is None  # 位数不对
    assert breakdowns.sheet_file(video_asset, "sheet-01c.jpg") is None


def test_measure_into_overwrites_existing_row(video_asset) -> None:
    with SessionLocal() as db:
        first = breakdowns.measure_into(db, video_asset, created_by=None, lang="zh")
        db.commit()
        first_id = first.id
    with SessionLocal() as db:
        asset = db.get(Asset, video_asset.id)
        breakdowns.measure_into(db, asset, created_by=None, lang="zh", threshold=0.15)
        db.commit()
    with SessionLocal() as db:
        rows = db.query(ShotBreakdown).filter_by(asset_id=video_asset.id).all()
        assert len(rows) == 1, "一份视频只留一份镜头表"
        assert rows[0].id == first_id
        assert rows[0].params["threshold"] == 0.15


def test_measure_into_rejects_bad_params(video_asset) -> None:
    with SessionLocal() as db:
        with pytest.raises(breakdowns.ShotBreakdownError):
            breakdowns.measure_into(db, video_asset, created_by=None, lang="zh", threshold=0.99)


def test_measure_into_rejects_non_video(client) -> None:
    ws_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    image_id = insert_asset(ws_id, kind="image", name="图", file_key="", media_info={})
    with SessionLocal() as db:
        image = db.get(Asset, image_id)
        with pytest.raises(breakdowns.ShotBreakdownError) as err:
            breakdowns.measure_into(db, image, created_by=None, lang="zh")
        assert err.value.key == "shotsErr_notVideo"


# --------------------------------------------------------------------------------------
# judge:逐批判、对账、每批落库、一批失败不连坐
# --------------------------------------------------------------------------------------

def _fake_sheet(folder: Path, name: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 36), (40, 40, 40)).save(folder / name, "JPEG")


def _fabricated_row(asset, count: int = 30) -> str:
    """直接造一行 30 镜的表(两批):不去量,专注验判的画面那一半。"""
    shots = [{"id": f"S{i:02d}", "start": float(i - 1), "end": float(i), "seconds": 1.0, "motion": 0.5}
             for i in range(1, count + 1)]
    sheets = [
        {"index": index, "first": shots[first]["id"], "last": shots[min(first + 24, count - 1)]["id"],
         "a": f"sheet-{index:02d}a.jpg", "b": f"sheet-{index:02d}b.jpg"}
        for index, first in enumerate(range(0, count, 25), start=1)
    ]
    folder = breakdowns.shots_dir(asset) / "sheets"
    for sheet in sheets:
        _fake_sheet(folder, sheet["a"])
        _fake_sheet(folder, sheet["b"])
    with SessionLocal() as db:
        row = ShotBreakdown(
            asset_id=asset.id, workspace_id=asset.workspace_id, lang="zh",
            params={}, meta={"duration": float(count)}, cuts=[], shots=shots, sheets=sheets,
        )
        db.add(row)
        db.commit()
        return row.id


def _answer_for(batch: list[dict]) -> str:
    import json as jsonlib

    return jsonlib.dumps({"shots": [
        {"id": shot["id"], "size": "medium", "category": "subject", "camera": ["static"],
         "transition_in": "cut", "rhythm": "beat", "subjects": [], "onscreen_text": "",
         "audio": "", "frame": f"第 {shot['id']} 镜的画面:主体站在正中,背后有窗", "rhythm_note": "",
         "prompt": f"{shot['id']} 的分镜提示词", "note": ""}
        for shot in batch
    ]}, ensure_ascii=False)


def test_judge_marks_describe_and_keeps_rows(video_asset) -> None:
    row_id = _fabricated_row(video_asset)

    def ask(messages: list) -> str:
        #: 按提示词里列的镜号回答(一批一张联系表 ≤25 镜)。
        import re as re_mod

        text = messages[1]["content"][0]["text"]
        ids = re_mod.findall(r"^S\d+", text, flags=re_mod.M)
        return _answer_for([{"id": shot_id} for shot_id in ids])

    with SessionLocal() as db:
        row = db.get(ShotBreakdown, row_id)
        asset = db.get(Asset, video_asset.id)
        breakdowns.judge(db, row, asset, ask, provider="moonshot", model="kimi")
        db.commit()
    with SessionLocal() as db:
        row = db.get(ShotBreakdown, row_id)
        assert row.describe["provider"] == "moonshot"
        assert row.describe["batches"] == 2 and row.describe["judged_batches"] == 2
        assert all(shot.get("size") == "medium" for shot in row.shots)
        assert row.shots[0]["prompt"].startswith("S01") and row.shots[29]["prompt"].startswith("S30")


def test_judge_one_bad_batch_does_not_sink_the_other(video_asset) -> None:
    row_id = _fabricated_row(video_asset)
    calls = iter(range(2))

    def flaky(messages: list) -> str:
        next(calls)
        raise LocalizedError("analysisErr_noVisionProvider")

    with SessionLocal() as db:
        row = db.get(ShotBreakdown, row_id)
        asset = db.get(Asset, video_asset.id)
        breakdowns.judge(db, row, asset, flaky, provider="moonshot", model="kimi")
        db.commit()
    with SessionLocal() as db:
        row = db.get(ShotBreakdown, row_id)
        assert row.describe["judged_batches"] == 0
        assert row.describe["error"], "记下了第一批失败的原因"
        kinds = [h["kind"] for h in row.hints]
        assert kinds.count("batch_failed") == 2
        #: 判失败的镜留着机器量那一半。
        assert all("size" not in shot for shot in row.shots)


def test_judge_reassigns_dialogue_from_transcript(video_asset, monkeypatch) -> None:
    """转写晚于拆镜头到位(官方模板就是先拆后转写):判之前按最新逐字稿重分台词。"""
    row_id = _fabricated_row(video_asset, count=4)
    monkeypatch.setattr(
        breakdowns, "transcript_segments",
        lambda _db, _asset_id: [{"start": 0.2, "end": 0.9, "text": "晚到的台词"}],
    )
    seen_rows: list[str] = []

    def ask(messages: list) -> str:
        seen_rows.append(messages[1]["content"][0]["text"])
        return _answer_for([{"id": f"S{i:02d}"} for i in range(1, 5)])

    with SessionLocal() as db:
        row = db.get(ShotBreakdown, row_id)
        asset = db.get(Asset, video_asset.id)
        assert all("dialogue" not in shot for shot in row.shots)
        breakdowns.judge(db, row, asset, ask, provider="moonshot", model="kimi")
        db.commit()
    assert "晚到的台词" in seen_rows[0], "判画面时把分好的台词交进了提示词"
    with SessionLocal() as db:
        row = db.get(ShotBreakdown, row_id)
        assert row.shots[0]["dialogue"] == "晚到的台词"


# --------------------------------------------------------------------------------------
# start_breakdown:素材页那条后台任务(没有视觉模型 → 机器那一半照样交)。编排住在
# analysis.shots_task:挑视觉模型是分析域的事,shots 域不认识任何连接 / 模型。
# --------------------------------------------------------------------------------------

def test_start_breakdown_job_machine_half_only(client, video_asset) -> None:
    from app.domain.analysis import shots_task

    with SessionLocal() as db:
        asset = db.get(Asset, video_asset.id)
        job = shots_task.start_breakdown(db, asset, created_by=None)
        db.commit()
        job_id = job.id
    assert wait_settled(client, job_id) == "succeeded"
    with SessionLocal() as db:
        row = breakdowns.breakdown_for(db, video_asset.id)
        assert row is not None and len(row.shots) == 4
        #: 没有可挑的视觉连接:describe 记一句没判,hints 说明原因。
        assert row.describe.get("error")
        assert any(h["kind"] == "not_described" for h in row.hints)


def test_public_shape_and_prompt_context(video_asset) -> None:
    row_id = _fabricated_row(video_asset, count=4)
    with SessionLocal() as db:
        row = db.get(ShotBreakdown, row_id)
        asset = db.get(Asset, video_asset.id)
        shape = breakdowns.public_shape(row, asset)
        assert shape["asset_id"] == asset.id
        assert shape["stats"]["shots"] == 4
        assert "## 镜头表" in shape["report_markdown"]
        assert "**S01**" in shape["storyboard_markdown"]
        context = breakdowns.prompt_context(row, asset)
        assert "【镜头表" in context
        assert "刀口和时长是代码量的" in context
