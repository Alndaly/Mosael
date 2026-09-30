"""几个节点的小毛病:整数格认不了 "10.0"、转写取错了逐字稿、失败原因冻成一种语言。

- 整数格插值 / 绑定之后常常是 `"12.0"`:`int()` 抛一句英文、不说是哪一格,或者被 except 吞掉悄悄换成默认值。
- 「转写素材」等完自己那一单,取的却是这份素材**最新**的逐字稿 —— 同一份素材同时被别处转写时拿到的是别人的那份。
- 3D 场景节点把场景域的错误 `str(exc)` 进参数:执行线程里那一刻就成了缺省语言,切到英文界面看历史还是中文。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.db.models import Asset, Transcript, TranscriptSegment, Workflow
from app.domain.jobs import create_job
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors import get_executor
from tests.util import fresh_client


def _workspace() -> tuple[str, str]:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="节点", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        return ws, workflow.id


def _run(node: str, wf_id: str, config: dict) -> dict:
    with SessionLocal() as db:
        out = get_executor(node)(db, db.get(Workflow, wf_id), config)
        db.commit()
        return out


def test_转写取的是自己这一单转出来的那份(monkeypatch) -> None:
    """只换掉 ASR 本身(外部能力):它按真实的契约在任务结果里交出 transcript_id。
    这一单写完之后,同一份素材又有别处写了一份更新的 —— 节点该拿的是自己那份。"""
    from app.domain.voices import transcription

    ws, wf_id = _workspace()
    with SessionLocal() as db:
        asset = Asset(workspace_id=ws, kind="video", name="v", source="imported", file_key="x",
                      media_info={"duration": 5.0})
        db.add(asset)
        db.commit()
        asset_id = asset.id

    def transcribe(db, asset_id, *, created_by=None, language="", engine=""):
        mine = Transcript(workspace_id=ws, asset_id=asset_id, language="zh")
        db.add(mine)
        db.flush()
        db.add(TranscriptSegment(transcript_id=mine.id, start_time=0.0, end_time=1.0, text="我这一单"))
        job = create_job(db, workspace_id=ws, kind="transcribe", payload={}, created_by=created_by)
        job.status = "succeeded"
        job.result = {"transcript_id": mine.id, "segments": 1}
        db.flush()
        # 别处(另一条分支、剪辑页)随后又给同一份素材写了一份。
        other = Transcript(workspace_id=ws, asset_id=asset_id, language="en")
        db.add(other)
        db.flush()
        db.add(TranscriptSegment(transcript_id=other.id, start_time=0.0, end_time=1.0, text="别人的"))
        db.commit()
        return job

    monkeypatch.setattr(transcription, "start_transcription", transcribe)
    out = _run("transcribe_asset", wf_id, {"asset_id": asset_id})
    assert out["text"] == "我这一单"
    assert out["language"] == "zh"


def test_整数格认得小数形式的整数_不认的说是哪一格(monkeypatch) -> None:
    from app.domain.assets import video_gif

    ws, wf_id = _workspace()
    with SessionLocal() as db:
        asset = Asset(workspace_id=ws, kind="video", name="v", source="imported", file_key="x",
                      media_info={"duration": 5.0})
        db.add(asset)
        db.commit()
        asset_id = asset.id
    seen: dict = {}

    def to_gif(db, *, asset, created_by, fps, width, start, duration):
        seen.update(fps=fps, width=width)
        job = create_job(db, workspace_id=ws, kind="video_gif", payload={}, created_by=created_by)
        job.status = "succeeded"
        job.result = {"asset_id": asset.id}
        db.commit()
        return job

    monkeypatch.setattr(video_gif, "start_video_to_gif", to_gif)
    _run("video_to_gif", wf_id, {"asset_id": asset_id, "fps": "12.0", "width": 480.0})
    assert seen == {"fps": 12, "width": 480}
    with pytest.raises(WorkflowDomainError) as caught:
        _run("video_to_gif", wf_id, {"asset_id": asset_id, "fps": "12.5"})
    assert caught.value.key == "wfErr_mustBeInteger"


def test_场景节点的失败原因按读的人的语言说() -> None:
    from app.core.i18n import render_message
    from app.domain.scenes.operations import create_scene
    from app.domain.scenes.types import SceneContent

    ws, wf_id = _workspace()
    with SessionLocal() as db:
        scene_id = create_scene(db, ws, "场景", SceneContent()).id
        db.commit()
    with pytest.raises(WorkflowDomainError) as caught:
        _run("scene_render", wf_id, {"scene_id": scene_id, "shot_id": "没有这一镜"})
    reason = caught.value.params["reason"]
    assert isinstance(reason, dict) and "__key" in reason, "原因被 str() 冻成了执行线程那一刻的语言"
    assert render_message(caught.value.key, "en", caught.value.params) != render_message(
        caught.value.key, "zh", caught.value.params
    )
