"""「人声分离」「降噪」节点和它们的兄弟节点一样,把活儿交给子任务、再等它。

此前这两个节点在**节点线程里**直接跑模型(「工作流本身已经在任务里,所以直接调」),于是:

· **绕开了准入**:界面上发起的分离/降噪占 RENDER_SLOTS(「这台机器要忙很久」的活不该几个一起
  抢 CPU),而循环里并行的几个节点一起把模型拉进内存;
· **分离产出不记来历**:派生关系只写在任务的执行体里,节点拆出来的两份素材不知道自己是从
  哪一份来的、哪份是人声。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ai.providers.contracts.separation import BACKGROUND, VOCALS, SeparationRequest
from app.core.db import SessionLocal
from app.db.models import Asset, Workflow
from app.domain import denoise, separation
from app.domain.jobs import RENDER_SLOTS
from app.domain.workflows.executors import common, get_executor
from tests.util import fresh_client


class _Separator:
    engine_id = "fake"
    label_key = "sepEngine_fake"

    def __init__(self) -> None:
        self.slots_free_while_running: int | None = None

    def runtime_ready(self) -> bool:
        return True

    def ensure_runtime(self) -> None:
        return None

    def separate(self, request: SeparationRequest, out_dir: Path) -> dict[str, Path]:
        self.slots_free_while_running = RENDER_SLOTS._value
        out_dir.mkdir(parents=True, exist_ok=True)
        made = {}
        for stem in (VOCALS, BACKGROUND):
            made[stem] = out_dir / f"{stem}.wav"
            made[stem].write_bytes(b"RIFF....WAVE")
        return made


class _Denoiser:
    engine_id = "fake"
    strengths = ()

    def __init__(self) -> None:
        self.slots_free_while_running: int | None = None

    def denoise(self, request, out_path: Path) -> Path:
        self.slots_free_while_running = RENDER_SLOTS._value
        out_path.write_bytes(b"RIFF....WAVE")
        return out_path


@pytest.fixture
def audio(monkeypatch, tmp_path) -> tuple[str, str]:
    monkeypatch.setattr(common, "CHILD_POLL_SECONDS", 0.05)
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    source = tmp_path / "talk.wav"
    source.write_bytes(b"RIFF....WAVE")
    monkeypatch.setattr(separation, "_source_path", lambda one: source)
    monkeypatch.setattr(denoise, "_source_path", lambda one: source)
    # 输入是 wav,as_audio 照原样用;这里不关心 ffmpeg,只关心节点怎么跑这件活。
    monkeypatch.setattr(separation, "as_audio", lambda path, work: path)
    monkeypatch.setattr(denoise, "as_audio", lambda path, work: path)
    with SessionLocal() as db:
        asset = Asset(workspace_id=ws, kind="audio", name="访谈", file_key="media/talk.wav")
        db.add(asset)
        db.commit()
        return ws, asset.id


def _install(monkeypatch, node: str):
    if node == "separate_audio":
        engine = _Separator()
        monkeypatch.setattr(separation, "get_separation_adapter", lambda name="": engine)
    else:
        engine = _Denoiser()
        monkeypatch.setattr(denoise, "ready_adapter", lambda name="": engine)
    return engine


def _node(ws: str, node: str, asset_id: str) -> dict:
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="W", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        return get_executor(node)(db, workflow, {"asset_id": asset_id})


@pytest.mark.parametrize("node", ["separate_audio", "denoise_audio"])
def test_占着渲染槽位跑_和界面上发起的一样(monkeypatch, audio, node: str) -> None:
    ws, asset_id = audio
    engine = _install(monkeypatch, node)
    free = RENDER_SLOTS._value
    _node(ws, node, asset_id)
    assert engine.slots_free_while_running == free - 1, "节点绕开了 RENDER_SLOTS,并行几个就一起抢 CPU"


def test_节点拆出来的两份也记着自己是从哪儿来的(monkeypatch, audio) -> None:
    ws, asset_id = audio
    _install(monkeypatch, "separate_audio")
    out = _node(ws, "separate_audio", asset_id)
    with SessionLocal() as db:
        vocals = db.get(Asset, out["vocals_asset_id"]).media_info
        background = db.get(Asset, out["background_asset_id"]).media_info
    assert (vocals.get("derived_from_asset_id"), vocals.get("stem")) == (asset_id, VOCALS)
    assert (background.get("derived_from_asset_id"), background.get("stem")) == (asset_id, BACKGROUND)


@pytest.mark.parametrize("node", ["separate_audio", "denoise_audio"])
def test_跑到一半被取消_收尾时不把自己写回完成(monkeypatch, audio, node: str) -> None:
    """节点改成等子任务之后,取消工作流会级联到这条分离/降噪任务。模型本身停不下来,
    但它跑完时不能把「已取消」盖成「完成」—— 那样任务中心里取消过的活又成了成功的。
    和字幕配音、导出同一条规矩:状态经 finish_job 写。"""
    from app.db.models import Job
    from app.domain.jobs import cancel_job

    ws, asset_id = audio
    engine = _install(monkeypatch, node)
    with SessionLocal() as db:
        job = Job(workspace_id=ws, kind=node, status="queued")
        db.add(job)
        db.commit()
        job_id = job.id

    def cancel_midway(run):
        def wrapped(*args, **kwargs):
            with SessionLocal() as other:
                cancel_job(other, other.get(Job, job_id))
            return run(*args, **kwargs)

        return wrapped

    if node == "separate_audio":
        engine.separate = cancel_midway(engine.separate)
        separation._job_body(job_id, asset_id, "")
    else:
        engine.denoise = cancel_midway(engine.denoise)
        denoise._job_body(job_id, asset_id, "", "")
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert (job.status, job.error_key) == ("failed", "jobErr_cancelled"), job.status
