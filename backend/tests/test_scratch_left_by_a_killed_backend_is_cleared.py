"""生成和插件的暂存放在数据目录里,进程中途没了留下的,下次启动清掉(GEN-9)。

此前它们在系统临时目录(`mosael-gen-*`、`mosael-plugin-out-*`),只在 finally 里删;任务线程是 daemon,进程被杀、
`--reload` 时 finally 不执行。生成一段大视频中途重启一次,系统临时目录里就留下几百 MB 没人收(Windows 的 %TEMP% 不会
自己清)。插件的「请停下」开关文件更是从来没人删。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from app.ai.providers import register_generation_adapter_source
from app.ai.providers.contracts.generation import GenerationAdapter, GenerationRequest, GenerationResult
from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import GenerationJob, Job
from app.domain.generation import runner
from app.media.scratch import GENERATION, PLUGIN_OUTPUT, clear_scratch, scratch_dir, scratch_root

_SEEN: list[Path] = []


class _RecordsWhereItWrites(GenerationAdapter):
    vendor_id = "fake-scratch"
    media_kind = "image"

    def requires_credentials(self) -> bool:
        return False

    def generate(self, request: GenerationRequest, context, output_dir: Path) -> GenerationResult:
        _SEEN.append(output_dir)
        target = output_dir / "out.png"
        target.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
        return GenerationResult(output_paths=[target], usage={"images": 1}, raw_usage={})


_ADAPTER = _RecordsWhereItWrites()
register_generation_adapter_source(lambda vendor, kind: _ADAPTER if (vendor, kind) == ("fake-scratch", "image") else None)


def test_生成的暂存在数据目录里_用完就删(monkeypatch) -> None:
    from tests.util import fresh_client, user_id

    client = fresh_client()
    monkeypatch.setattr("app.domain.providers.selection.resolve_connection", lambda *a, **kw: None)
    monkeypatch.setattr(runner.provider_models, "model_id_for", lambda *a, **kw: "")
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        job = Job(workspace_id=workspace, kind="ai_generation", status="queued", payload={}, created_by=user_id())
        db.add(job)
        db.flush()
        generation = GenerationJob(workspace_id=workspace, job_id=job.id, kind="image", provider="fake-scratch",
                                   model="m", request={"prompt": "猫", "parameters": {}})
        db.add(generation)
        db.commit()
        generation_id = generation.id
    _SEEN.clear()

    runner._run_generation(generation_id)

    [workdir] = _SEEN
    assert workdir.parent == scratch_root() / GENERATION, f"暂存在 {workdir},不在数据目录里"
    assert not workdir.exists(), "用完要删"


def test_插件产物的暂存在数据目录里_收尾连停下开关一起删() -> None:
    from app.domain.plugins import artifacts

    scratch = artifacts.make_scratch_dir()
    switch = artifacts.cancel_file_for(scratch)
    switch.touch()
    assert scratch.parent == scratch_root() / PLUGIN_OUTPUT

    artifacts.cleanup_scratch_dir(scratch)

    assert not scratch.exists() and not switch.exists(), "「请停下」开关文件此前从来没人删"


def _aged(path: Path, seconds: float) -> Path:
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))
    return path


def test_启动时清掉上一个进程留下的_这一次刚建的不动() -> None:
    from app.domain.plugins import artifacts

    left_gen = _aged(scratch_dir(GENERATION), 600)
    (left_gen / "generated.mp4.part").write_bytes(b"half")
    _aged(left_gen, 600)
    left_plugin = artifacts.make_scratch_dir()
    left_switch = artifacts.cancel_file_for(left_plugin)
    left_switch.touch()
    _aged(left_plugin, 600)
    _aged(left_switch, 600)
    started = time.time()
    fresh = scratch_dir(GENERATION)

    cleared = clear_scratch(older_than=started - 1)

    assert cleared == 3
    assert not left_gen.exists() and not left_plugin.exists() and not left_switch.exists()
    assert fresh.exists(), "按时间判:这个进程刚建的不能被当成上一次留下的"
    fresh.rmdir()


def test_启动收尾在接着取远端任务之前清暂存() -> None:
    """接着取会新建暂存目录;清在它之后的话,刚建的就被当成旧的删了。看 lifespan 的顺序。"""
    import inspect

    from app import main

    source = inspect.getsource(main.lifespan)
    assert 0 < source.index("clear_scratch(") < source.index("settle_previous_run("), "启动时没清暂存,或者清在收尾之后"
    assert settings.data_dir in scratch_root().parents
