"""交付域:把成片和文案送到「不需要登录的目的地」。

和发布域的分界:
- **发布**(domain/publish)= 带着登录态去平台上传。有账号、有风控、有 login_required /
  waiting_manual 这类需要人介入的中间态,由桌面端内嵌浏览器执行。
- **交付**(这里)= 把文件放到某处。没有账号、没有登录、没有中间态,后端线程里直接跑完。

这两件事原先挤在 publish 域里,靠 `executor` 字段分叉。分叉的代价见 models.DeliveryTarget
的类注释。拆开之后这里没有一处需要问「我到底是哪一类」。
"""

from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path
from typing import Any, Callable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.db.models import Asset, DeliveryTarget, DeliveryTask, Job
from app.domain.jobs import create_job, emit_job_event
from app.domain.notifications import notify
from app.media.paths import resolve_key

WEBHOOK_TIMEOUT_SECONDS = 60


class DeliveryDomainError(ValueError):
    pass


#: 交付方式注册表。config 字段描述同时驱动表单与校验(和发布平台注册表同样的约定)。
DELIVERY_KINDS: dict[str, dict[str, Any]] = {
    "folder": {
        "label": "本地目录",
        "description": "把成片拷到指定目录,并写入同名 .json 元数据(标题/简介/标签),方便手动上传或交给其他工具。",
        "config": {"directory": {"type": "string", "required": True, "description": "目标目录绝对路径"}},
    },
    "webhook": {
        "label": "Webhook",
        "description": "把文件路径与文案元数据 POST 给外部自动化(n8n / Zapier / 自建服务),由对方完成上传。",
        "config": {"url": {"type": "string", "required": True, "description": "接收 POST 的 URL"}},
    },
}


def normalize_kind(kind: str) -> str:
    value = (kind or "").strip().lower()
    if value not in DELIVERY_KINDS:
        raise DeliveryDomainError(f"未知交付方式: {kind!r}(支持 {', '.join(DELIVERY_KINDS)})")
    return value


def create_target(
    db: Session, *, workspace_id: str, kind: str, name: str, config: dict[str, Any]
) -> DeliveryTarget:
    kind = normalize_kind(kind)
    spec = DELIVERY_KINDS[kind]["config"]
    for key, field in spec.items():
        if isinstance(field, dict) and field.get("required") and not str(config.get(key, "")).strip():
            raise DeliveryDomainError(f"{DELIVERY_KINDS[kind]['label']} 缺少必填配置 {key}")
    target = DeliveryTarget(workspace_id=workspace_id, kind=kind, name=name or DELIVERY_KINDS[kind]["label"], config=config)
    db.add(target)
    db.commit()
    db.refresh(target)
    return target


def list_targets(db: Session, workspace_id: str) -> list[DeliveryTarget]:
    return list(
        db.scalars(
            select(DeliveryTarget)
            .where(DeliveryTarget.workspace_id == workspace_id)
            .order_by(DeliveryTarget.created_at.desc())
        )
    )


def start_delivery(
    db: Session,
    *,
    workspace_id: str,
    target: DeliveryTarget,
    asset: Asset,
    title: str = "",
    description: str = "",
    tags: list[str] | None = None,
) -> DeliveryTask:
    if not target.enabled:
        raise DeliveryDomainError("交付目标已停用")
    if not asset.file_key:
        raise DeliveryDomainError("素材没有本地文件,无法交付")

    job = create_job(
        db,
        workspace_id=workspace_id,
        kind="delivery",
        payload={"target_id": target.id, "asset_id": asset.id, "kind": target.kind},
        message=f"交付排队中: {title or asset.name}",
    )
    task = DeliveryTask(
        workspace_id=workspace_id,
        target_id=target.id,
        asset_id=asset.id,
        title=title,
        description=description,
        tags=list(tags or []),
        job_id=job.id,
    )
    db.add(task)
    db.flush()
    # 任务中心点开这个 job 时能直达交付详情。
    job.payload = {**job.payload, "task_id": task.id}
    db.commit()
    db.refresh(task)
    threading.Thread(target=_run_delivery_thread, args=(task.id,), daemon=True).start()
    return task


def _run_delivery_thread(task_id: str) -> None:
    with SessionLocal() as db:
        task = db.get(DeliveryTask, task_id)
        if task is None or task.job_id is None:
            return
        job = db.get(Job, task.job_id)
        target = db.get(DeliveryTarget, task.target_id)
        asset = db.get(Asset, task.asset_id)
        if job is None or target is None or asset is None:
            return
        job.status = "running"
        job.message = f"交付中: {task.title or asset.name}"
        db.commit()
        try:
            result = _HANDLERS[target.kind](target.config, asset, task)
            job.status = "succeeded"
            job.progress = 1.0
            job.result = result
            job.message = f"交付完成: {task.title or asset.name}"
            emit_job_event(db, job.id, "delivery.finished", result)
            notify(
                db,
                task.workspace_id,
                type="delivery",
                title=f"交付成功: {task.title or asset.name}",
                link="#/publish",
                payload={"task_id": task.id, "kind": target.kind, "status": "success"},
            )
        except Exception as exc:  # noqa: BLE001 — 处理器失败必须落到 job
            job.status = "failed"
            job.error = str(exc)[:500]
            job.message = "交付失败"
            emit_job_event(db, job.id, "delivery.failed", {"error": str(exc)[:500]})
            notify(
                db,
                task.workspace_id,
                type="delivery",
                title=f"交付失败: {task.title or asset.name}",
                body=str(exc)[:300],
                link="#/publish",
                payload={"task_id": task.id, "kind": target.kind, "status": "failed"},
            )
        db.commit()


def _metadata(task: DeliveryTask, asset: Asset) -> dict[str, Any]:
    return {
        "title": task.title,
        "description": task.description,
        "tags": list(task.tags or []),
        "asset_name": asset.name,
        "asset_id": asset.id,
    }


def _deliver_folder(config: dict[str, Any], asset: Asset, task: DeliveryTask) -> dict[str, Any]:
    directory = Path(str(config.get("directory", ""))).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    source = resolve_key(asset.file_key)
    safe_title = (task.title or asset.name).strip().replace("/", "_") or asset.id
    target = directory / f"{safe_title}{source.suffix}"
    counter = 1
    while target.exists():
        target = directory / f"{safe_title}-{counter}{source.suffix}"
        counter += 1
    shutil.copy2(source, target)
    sidecar = target.with_suffix(target.suffix + ".json")
    sidecar.write_text(json.dumps(_metadata(task, asset), ensure_ascii=False, indent=2), encoding="utf-8")
    return {"target": str(target), "sidecar": str(sidecar)}


def _deliver_webhook(config: dict[str, Any], asset: Asset, task: DeliveryTask) -> dict[str, Any]:
    url = str(config.get("url", ""))
    payload = {**_metadata(task, asset), "file_path": str(resolve_key(asset.file_key))}
    response = httpx.post(url, json=payload, timeout=WEBHOOK_TIMEOUT_SECONDS)
    response.raise_for_status()
    return {"status_code": response.status_code, "response": response.text[:500]}


_HANDLERS: dict[str, Callable[[dict[str, Any], Asset, DeliveryTask], dict[str, Any]]] = {
    "folder": _deliver_folder,
    "webhook": _deliver_webhook,
}


def task_with_status(db: Session, task: DeliveryTask) -> dict[str, Any]:
    """交付任务 + 状态。状态直接来自 job —— 交付没有 job 表达不了的中间态。"""
    job = db.get(Job, task.job_id) if task.job_id else None
    target = db.get(DeliveryTarget, task.target_id)
    asset = db.get(Asset, task.asset_id)
    return {
        "id": task.id,
        "workspace_id": task.workspace_id,
        "target_id": task.target_id,
        "target_name": target.name if target else "",
        "kind": target.kind if target else "",
        "asset_id": task.asset_id,
        "asset_name": asset.name if asset else "",
        "title": task.title,
        "description": task.description,
        "tags": list(task.tags or []),
        "job_id": task.job_id,
        "status": job.status if job else "queued",
        "error": job.error if job else None,
        "result": (job.result or {}) if job else {},
        "created_at": task.created_at,
    }
