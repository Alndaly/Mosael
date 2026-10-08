"""ffmpeg 写的那个文件是**中转**,不是成品 —— 三种结局都不该把它留在磁盘上。

(它现在写在 `<数据目录>/tmp/export/<这一次>/{job_id}.mp4`,成功时**搬**进素材库,见 media/scratch。)
此前的 `output_path = data_dir/exports/{job_id}.mp4` 从来没人删:

· **成功**时 `register_file_asset` 是流式拷贝(不搬走源文件),于是同一段成片在磁盘上存两份。
· **取消/失败**时留下一截永远没人清。

实测某台机器上 `~/.mosael/exports` 攒了 66 个文件 445 MB,全是这么来的;其中一次取消
(进度 28%)留下的半截就有 6.0 MB。job 结果里那个 `output_key` 指向它,而全仓库没有任何地方
读过 —— 它是个死字段,跟着一起去掉。
"""

from __future__ import annotations

from types import SimpleNamespace

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Job
from app.domain import render
from app.media.render_executor import RenderExecutionError
from tests.util import fresh_client


def _job(workspace_id: str) -> str:
    with SessionLocal() as db:
        job = Job(workspace_id=workspace_id, kind="render", status="queued")
        db.add(job)
        db.commit()
        return job.id


def _plan() -> SimpleNamespace:
    # 成片登记时要记出处(计划里用到的素材,见 render._export_sources):这里一份都没有。
    return SimpleNamespace(render_plan_hash="test", sequence_id="seq-1", sequence_revision=1,
                           video_segments=(), overlays=(), audio_overlays=(), timeline_duration=1.0,
                           output=SimpleNamespace(width=320, height=180, fps=30.0, crf=20))


def _workspace() -> str:
    client = fresh_client()
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def test_取消之后不留半截文件(monkeypatch) -> None:
    job_id = _job(_workspace())
    written: list = []

    def half_written(plan, resolve_key, output_path, on_progress, on_child, on_phase):
        written.append(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\x00" * 1024)  # ffmpeg 已经写了一截
        raise RenderExecutionError("已取消", stderr_tail="")

    monkeypatch.setattr(render, "execute_render", half_written)
    render._run_export(job_id, _plan())

    [out] = written
    assert not out.parent.exists(), "取消的导出留下了半截文件"
    with SessionLocal() as db:
        assert db.get(Job, job_id).status == "failed"


def test_成功之后也不留_它已经拷进素材库了(monkeypatch) -> None:
    job_id = _job(_workspace())
    written: list = []
    registered: list = []

    def wrote_it(plan, resolve_key, output_path, on_progress, on_child, on_phase):
        written.append(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\x00" * 2048)

    def fake_register(db, **kwargs):
        assert kwargs.get("move") is True, "成片是自己的中转:搬进素材库,不再复制一份"
        registered.append(kwargs["source_path"].read_bytes())
        return SimpleNamespace(id="asset-1", media_info={"size": 2048})

    monkeypatch.setattr(render, "execute_render", wrote_it)
    monkeypatch.setattr(render, "register_file_asset", fake_register)
    render._run_export(job_id, _plan())

    assert registered and len(registered[0]) == 2048, "素材库该拿到完整的那一份"
    [out] = written
    assert not out.parent.exists(), "成功的导出在磁盘上留了第二份"
    assert settings.data_dir in out.parents, "中转要写在数据目录里(和素材库同一块盘,搬过去是一次改名)"
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job.status == "succeeded"
        # output_key 指向一个已经不存在的文件,而且从来没人读它。
        assert "output_key" not in (job.result or {})
