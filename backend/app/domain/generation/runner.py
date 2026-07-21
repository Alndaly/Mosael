from __future__ import annotations

import shutil
import tempfile
import threading
from pathlib import Path

from app.ai.providers import GenerationRequest, ProviderError, get_provider
from app.ai.providers.base import sanitize_provider_error
from app.core.db import SessionLocal
from app.db.models import GeneratedAsset, GenerationJob, Job
from app.domain.jobs import dispatch_job, emit_job_event
from app.domain.assets.importer import register_file_asset

"""
Generation runner: executes a generation job off-thread. Results always land
as assets + generated_assets rows (plan §18.4) — never as loose temp files.
"""


def start_generation_thread(generation_id: str) -> None:
    """按 ai_generation 的执行模式派发(名字保留:四个调用方不需要知道派发细节)。

    调用方先 create_generation_job + commit 再调这里,所以能安全地重开会话取 job;
    external 模式下 dispatch 只把 job 标成等待认领,不起线程。"""
    with SessionLocal() as db:
        generation = db.get(GenerationJob, generation_id)
        job = db.get(Job, generation.job_id) if generation is not None and generation.job_id else None
        if job is None:
            return
        dispatch_job(db, job, lambda: _run_generation(generation_id))


def _run_generation(generation_id: str) -> None:
    with SessionLocal() as db:
        generation = db.get(GenerationJob, generation_id)
        if generation is None:
            return
        job = db.get(Job, generation.job_id)
        if job is None:
            return

        provider = get_provider(generation.provider, generation.kind)
        if provider is None:
            _fail(db, job, f"No adapter for provider {generation.provider}/{generation.kind}")
            return

        from app.domain.providers import resolve_secret

        secret = resolve_secret(db, generation.provider)
        request = GenerationRequest(
            kind=generation.kind,
            model=generation.model,
            prompt=str(generation.request.get("prompt", "")),
            negative_prompt=str(generation.request.get("negative_prompt", "")),
            parameters=dict(generation.request.get("parameters") or {}),
        )

        job.status = "running"
        job.message = "Generating"
        emit_job_event(db, job.id, "job.running", {"provider": generation.provider})
        db.commit()

        workdir = Path(tempfile.mkdtemp(prefix="mibu-gen-"))
        try:
            provider.validate_request(request)
            output = provider.generate(request, secret, workdir)
            asset = register_file_asset(
                db,
                workspace_id=job.workspace_id,
                project_id=generation.request.get("project_id"),
                source_path=output,
                name=_asset_name(request.prompt, generation.model),
                source="generated",
            )
            db.add(
                GeneratedAsset(
                    asset_id=asset.id,
                    provider=generation.provider,
                    model=generation.model,
                    prompt=request.prompt,
                    parameters=request.parameters,
                    job_id=job.id,
                )
            )
            generation.result_asset_id = asset.id
            job.status = "succeeded"
            job.progress = 1.0
            job.message = "Generation complete"
            job.result = {"asset_id": asset.id}
            emit_job_event(db, job.id, "job.succeeded", {"asset_id": asset.id})
            db.commit()
        except ProviderError as exc:
            _fail(db, job, str(exc))
        except Exception as exc:  # defensive: worker threads must never die silently
            _fail(db, job, sanitize_provider_error(str(exc), secret))
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


def _fail(db, job: Job, message: str) -> None:
    job.status = "failed"
    job.message = "Generation failed"
    job.error = message[:500]
    emit_job_event(db, job.id, "job.failed", {})
    db.commit()


def _asset_name(prompt: str, model: str) -> str:
    summary = prompt.strip().splitlines()[0][:40] if prompt.strip() else "Generation"
    return f"{summary} · {model}"
