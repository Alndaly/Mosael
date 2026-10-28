"""拆镜头三节点(ADR 0061 §4):detect_shots / describe_shots / shot_report 执行器。

真的跑 ffmpeg 造 4 秒四刀口小片子;视觉调用打桩(app.domain.analysis.service.call_vision_model);
连接用 API 建一条 moonshot。判据照节点声明:detect 不花钱只量,describe 逐批判 + 对账,
report 纯代码;没拆过就报「先拆镜头」。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset, Workflow
from app.domain.shots import breakdowns
from app.domain.workflows.errors import WorkflowDomainError
from app.domain.workflows.executors.shots import describe_shots, detect_shots, shot_report
from tests.util import fresh_client

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
    return fresh_client()


@pytest.fixture
def scope(client):
    ws_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws_id, name="wf", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        return db.get(Workflow, workflow.id)


def _workspace_of(scope) -> str:
    with SessionLocal() as db:
        return db.get(Workflow, scope.id).workspace_id


@pytest.fixture
def video_asset(client, scope):
    ws_id = _workspace_of(scope)
    media = settings.media_dir / "test-shots-nodes"
    media.mkdir(parents=True, exist_ok=True)
    source = media / f"cuts-{uuid4().hex[:8]}.mp4"
    _make_cut_video(source)
    from tests.util import insert_asset

    asset_id = insert_asset(
        ws_id, kind="video", name="参考视频",
        file_key=source.relative_to(settings.data_dir).as_posix(),
        media_info={"duration": 4.0, "width": 320, "height": 180, "fps": 25},
    )
    with SessionLocal() as db:
        yield db.get(Asset, asset_id)
    shutil.rmtree(media / "test-shots-nodes", ignore_errors=True)


def _run(handler, workflow, config, *, as_user: bool = False):
    """as_user:套一个父任务(created_by = 第一个账号)再跑 —— 花钱节点要按人解析连接和钥匙。"""
    from app.db.models import User
    from app.domain.jobs import create_job, reset_parent_job, set_parent_job

    token = None
    if as_user:
        with SessionLocal() as db:
            me = db.query(User).order_by(User.created_at).first().id
            job = create_job(db, workspace_id=workflow.workspace_id, kind="workflow_run",
                             created_by=me, payload={"workflow_id": workflow.id})
            db.commit()
            token = set_parent_job(job.id)
    try:
        with SessionLocal() as db:
            out = handler(db, db.get(Workflow, workflow.id), config)
            db.commit()
            return out
    finally:
        if token is not None:
            reset_parent_job(token)


def test_detect_shots_measures_and_stores(client, scope, video_asset) -> None:
    out = _run(detect_shots, scope, {"asset_id": video_asset.id})
    assert out["shot_count"] == 4
    assert out["sheets"] and out["sheets"][0]["first"] == "S01"
    assert out["asset_ids"] == []  # 默认不存联系表
    with SessionLocal() as db:
        row = breakdowns.breakdown_for(db, video_asset.id)
        assert row is not None and len(row.shots) == 4


def test_detect_shots_save_sheets_registers_assets(client, scope, video_asset) -> None:
    out = _run(detect_shots, scope, {"asset_id": video_asset.id, "save_sheets": "yes"})
    assert len(out["asset_ids"]) == 2  # 一批 4 镜 → 一张 A 表 + 一张 B 表
    with SessionLocal() as db:
        for asset_id in out["asset_ids"]:
            sheet = db.get(Asset, asset_id)
            assert sheet.kind == "image"
            derived_from = sheet.derived_from
            assert any(item.get("asset_id") == video_asset.id and item.get("op") == "frame"
                       for item in derived_from)


def test_detect_shots_rejects_non_video(client, scope) -> None:
    from tests.util import insert_asset

    image_id = insert_asset(_workspace_of(scope), kind="image", name="图", file_key="", media_info={})
    with pytest.raises(WorkflowDomainError) as err:
        _run(detect_shots, scope, {"asset_id": image_id})
    assert err.value.key == "wfErr_shotsNotVideo"


def test_describe_shots_requires_breakdown(client, scope, video_asset) -> None:
    with pytest.raises(WorkflowDomainError) as err:
        _run(describe_shots, scope, {"asset_id": video_asset.id})
    assert err.value.key == "wfErr_shotsNotBrokenDown"


def _add_connection(client) -> str:
    profile = client.post(
        "/api/settings/providers",
        json={"name": "Kimi", "vendor": "moonshot", "config": {"api_key": "sk-moonshot"}},
    ).json()
    return profile["id"]


def test_describe_shots_judges_with_reconciliation(client, scope, video_asset, monkeypatch) -> None:
    _run(detect_shots, scope, {"asset_id": video_asset.id})
    profile_id = _add_connection(client)
    seen: list = []

    def fake_call(db, connection, messages, call=None, **kwargs):
        seen.append(messages)
        import re as re_mod

        text = messages[1]["content"][0]["text"] if isinstance(messages[1]["content"], list) else ""
        ids = re_mod.findall(r"^S\d+", text, flags=re_mod.M) or ["S01", "S02", "S03", "S04"]
        return json.dumps({"shots": [
            {"id": shot_id, "size": "close", "category": "subject", "camera": ["push-in"],
             "transition_in": "cut", "rhythm": "beat", "subjects": ["主播"], "onscreen_text": "",
             "audio": "", "frame": f"{shot_id} 的画面:主播坐在桌前,背后是书架,光从左前方打来",
             "rhythm_note": "", "prompt": f"{shot_id} 特写固定主播", "note": ""}
            for shot_id in ids
        ]}, ensure_ascii=False)

    from app.domain.analysis import service as analysis_service

    monkeypatch.setattr(analysis_service, "call_vision_model", fake_call)
    out = _run(describe_shots, scope, {"asset_id": video_asset.id, "profile_id": profile_id}, as_user=True)
    assert out["judged"] == 1 and out["batches"] == 1
    with SessionLocal() as db:
        row = breakdowns.breakdown_for(db, video_asset.id)
        assert all(shot.get("size") == "close" for shot in row.shots)
        #: 实测几乎没动却声称推镜头 → 对账拦下、记 hints。
        assert all(shot.get("camera") == ["static"] for shot in row.shots)
        assert any(h["kind"] == "camera_corrected" for h in row.hints)
        assert row.describe["provider"] == "moonshot"


def test_shot_report_after_detect(client, scope, video_asset) -> None:
    _run(detect_shots, scope, {"asset_id": video_asset.id})
    out = _run(shot_report, scope, {"asset_id": video_asset.id})
    assert out["shot_count"] == 4
    assert "## 镜头表" in out["report_markdown"]
    assert "**S01**" in out["storyboard_markdown"]
    assert out["stats"]["shots"] == 4
    assert out["stats"]["cuts_per_minute"] > 0


def test_shot_report_requires_breakdown(client, scope, video_asset) -> None:
    with pytest.raises(WorkflowDomainError) as err:
        _run(shot_report, scope, {"asset_id": video_asset.id})
    assert err.value.key == "wfErr_shotsNotBrokenDown"


def test_node_types_registered() -> None:
    from app.domain.workflows.node_types import NODE_TYPES
    from app.domain.workflows.executors.registry import get_executor

    for node_type, spends in (("detect_shots", False), ("describe_shots", True), ("shot_report", False)):
        assert node_type in NODE_TYPES
        assert NODE_TYPES[node_type]["spends"] is spends
        assert get_executor(node_type) is not None
