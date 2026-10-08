"""入库到一半出错不留孤儿文件;导出、生成、下载的中转**搬**进素材库、不再复制一份;导出前看盘够不够,写满了说人话(MED-6)。

此前:
- 入库落盘之后任何一步出错(盘满、探测出错、提交时库被锁),文件留在 media/assets 下,没有任何一行指着它;
- 导出编完再把成片整份复制进素材库:几个 GB 的成片要占两倍的盘,复制到一半盘满,刚编完的成片在 finally 里被删掉,
  用户只看到一句「[Errno 28]」;ffmpeg 自己写满盘时是「FFmpeg 异常退出,退出码 N」;
- 导出中途后端被杀,半截文件永远留在 <数据目录>/exports(某台机器上攒过 433 MB)。
"""

from __future__ import annotations

import errno
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ai.providers import register_generation_adapter_source
from app.ai.providers.contracts.generation import GenerationAdapter, GenerationRequest, GenerationResult
from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset, GenerationJob, Job
from app.domain import render
from app.domain.assets import importer
from app.domain.assets.importer import register_file_asset
from app.media.render_executor import RenderExecutionError
from tests.test_export_leaves_no_file_behind import _job, _plan
from tests.util import fresh_client, user_id

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _workspace() -> str:
    return fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]


def _asset_dirs(workspace_id: str) -> list[Path]:
    root = settings.media_dir / "assets" / workspace_id
    return sorted(root.iterdir()) if root.is_dir() else []


def test_落了盘之后出错_目录整个清掉_不留孤儿(monkeypatch, tmp_path: Path) -> None:
    workspace = _workspace()
    source = tmp_path / "pic.png"
    source.write_bytes(PNG)

    def disk_full(*_args, **_kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(importer, "generate_thumbnail", disk_full)
    with SessionLocal() as db, pytest.raises(OSError):
        register_file_asset(db, workspace_id=workspace, project_id=None, source_path=source, name="pic")

    assert _asset_dirs(workspace) == [], "落了盘、行没进库,文件留在 media/assets 下没人认领"


def test_自己的中转搬进素材库_同一份字节不复制(tmp_path: Path) -> None:
    workspace = _workspace()
    source = tmp_path / "rendered.png"
    source.write_bytes(PNG)
    inode = source.stat().st_ino

    with SessionLocal() as db:
        asset = register_file_asset(db, workspace_id=workspace, project_id=None, source_path=source, name="r", move=True)
        stored = settings.data_dir / asset.file_key

    assert not source.exists(), "搬走了,源不该还在"
    assert stored.read_bytes() == PNG
    if source.parent.stat().st_dev == stored.parent.stat().st_dev:
        assert stored.stat().st_ino == inode, "同一块盘上应该是一次改名,不是复制"


def test_不是自己的文件照旧复制_源不动(tmp_path: Path) -> None:
    workspace = _workspace()
    source = tmp_path / "users-own.png"
    source.write_bytes(PNG)
    with SessionLocal() as db:
        register_file_asset(db, workspace_id=workspace, project_id=None, source_path=source, name="u")
    assert source.read_bytes() == PNG


# --------------------------------------------------------------------- 导出


def test_盘不够_导出开始前就说清要多少_剩多少_不开始编码(monkeypatch) -> None:
    job_id = _job(_workspace())
    started: list = []
    monkeypatch.setattr(render, "execute_render", lambda *a, **kw: started.append(1))
    monkeypatch.setattr(render.shutil, "disk_usage", lambda _path: SimpleNamespace(total=1 << 40, used=0, free=1024))

    render._run_export(job_id, _plan())

    assert started == [], "盘不够还开始编码"
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job.status == "failed" and "磁盘空间不够" in (job.error or "") and "GB" in job.error


@pytest.mark.parametrize("where", ["编码时", "搬进素材库时"])
def test_写到一半盘满了_说人话(monkeypatch, where: str) -> None:
    job_id = _job(_workspace())

    def encode(plan, resolve_key, output_path, on_progress, on_child, on_phase):
        if where == "编码时":
            raise RenderExecutionError("FFmpeg exited with code 228", stderr_tail="av_interleaved_write_frame(): No space left on device")
        output_path.write_bytes(b"\x00" * 64)

    def register(db, **_kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(render, "execute_render", encode)
    monkeypatch.setattr(render, "register_file_asset", register)
    render._run_export(job_id, _plan())

    with SessionLocal() as db:
        error = db.get(Job, job_id).error or ""
    assert error.startswith("磁盘空间不够"), error


def test_老版本的导出中转目录_列进存储清理_管理员确认后才删() -> None:
    from app.domain.storage_cleanup import ORPHAN_GRACE_SECONDS, delete_orphans, find_orphans

    fresh_client()
    legacy = settings.data_dir / "exports"
    legacy.mkdir(parents=True, exist_ok=True)
    for name in ("a.mp4", "b.ass", "c.png"):
        (legacy / name).write_bytes(b"x" * 100)
    stamp = time.time() - ORPHAN_GRACE_SECONDS - 60
    for one in (legacy, *legacy.iterdir()):
        os.utime(one, (stamp, stamp))

    with SessionLocal() as db:
        listed = {orphan.key: orphan for orphan in find_orphans(db)}
        assert listed["exports"].reason == "export_leftover" and listed["exports"].bytes == 300
        assert legacy.exists(), "列出来不等于删"
        assert delete_orphans(db, ["exports"]) == (["exports"], [])
    assert not legacy.exists()


# --------------------------------------------------------------------- 生成


class _Writes(GenerationAdapter):
    vendor_id = "fake-move"
    media_kind = "image"
    inodes: list[int] = []

    def requires_credentials(self) -> bool:
        return False

    def generate(self, request: GenerationRequest, context, output_dir: Path) -> GenerationResult:
        target = output_dir / "out.png"
        target.write_bytes(PNG)
        self.inodes.append(target.stat().st_ino)
        return GenerationResult(output_paths=[target], usage={"images": 1}, raw_usage={})


_WRITES = _Writes()
register_generation_adapter_source(lambda vendor, kind: _WRITES if (vendor, kind) == ("fake-move", "image") else None)


def test_生成下回来的成片搬进素材库(monkeypatch) -> None:
    from app.domain.generation import runner

    workspace = _workspace()
    monkeypatch.setattr("app.domain.providers.selection.resolve_connection", lambda *a, **kw: None)
    monkeypatch.setattr(runner.provider_models, "model_id_for", lambda *a, **kw: "")
    with SessionLocal() as db:
        job = Job(workspace_id=workspace, kind="ai_generation", status="queued", payload={}, created_by=user_id())
        db.add(job)
        db.flush()
        generation = GenerationJob(workspace_id=workspace, job_id=job.id, kind="image", provider="fake-move", model="m",
                                   request={"prompt": "猫", "parameters": {}})
        db.add(generation)
        db.commit()
        generation_id, job_id = generation.id, job.id
    _WRITES.inodes.clear()

    runner._run_generation(generation_id)

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job.status == "succeeded", job.error
        stored = settings.data_dir / db.get(Asset, job.result["asset_ids"][0]).file_key
    assert stored.stat().st_ino == _WRITES.inodes[0], "同一块盘上的成片应该搬进去,不是再复制一份"
