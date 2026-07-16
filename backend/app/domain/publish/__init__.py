"""发布内核(计划 §6.9 / Phase 13):账号 = 平台适配器 + 配置,
发布任务 = 成片素材 + 文案元数据 + 目标账号,执行走任务总线。

平台适配器注册表数据驱动(publish_targets 扩展位):v1 内置
folder(交付到本地目录 + 元数据 sidecar)、webhook(POST 给外部
自动化)、mock(演示/测试)。真平台(抖音/B站等)按同一契约叠加。
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
from app.db.models import Asset, Job, PublishAccount, PublishTask, TaskEvent
from app.domain.jobs import create_job
from app.media.paths import resolve_key


class PublishDomainError(ValueError):
    pass


# 平台注册表:config 字段描述驱动 UI 表单与校验。
PUBLISH_PLATFORMS: dict[str, dict[str, Any]] = {
    "folder": {
        "label": "本地目录",
        "description": "把成片拷贝到指定目录,并写入同名 .json 元数据(标题/简介/标签),方便手动上传或交给其他工具。",
        "config": {"directory": {"type": "string", "required": True, "description": "目标目录绝对路径"}},
    },
    "webhook": {
        "label": "Webhook",
        "description": "把文件路径与文案元数据 POST 给外部自动化(n8n / Zapier / 自建服务),由对方完成上传。",
        "config": {"url": {"type": "string", "required": True, "description": "接收 POST 的 URL"}},
    },
    "mock": {
        "label": "演示平台",
        "description": "不做真实上传,直接返回成功。用于演示与测试。",
        "config": {},
    },
}

WEBHOOK_TIMEOUT_SECONDS = 60


def create_account(
    db: Session, *, workspace_id: str, platform: str, name: str, config: dict[str, Any]
) -> PublishAccount:
    meta = PUBLISH_PLATFORMS.get(platform)
    if meta is None:
        raise PublishDomainError(f"未知发布平台: {platform}")
    for key, spec in meta["config"].items():
        if isinstance(spec, dict) and spec.get("required") and not str(config.get(key, "")).strip():
            raise PublishDomainError(f"平台 {platform} 缺少必填配置 {key}")
    account = PublishAccount(workspace_id=workspace_id, platform=platform, name=name, config=config)
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def start_publish(
    db: Session,
    *,
    workspace_id: str,
    account: PublishAccount,
    asset: Asset,
    title: str,
    description: str,
    tags: list[str],
) -> PublishTask:
    if not account.enabled:
        raise PublishDomainError("发布账号已停用")
    if not asset.file_key:
        raise PublishDomainError("素材没有本地文件,无法发布")

    job = create_job(
        db,
        workspace_id=workspace_id,
        kind="publish",
        payload={"account_id": account.id, "asset_id": asset.id, "platform": account.platform},
        message=f"发布排队中: {title or asset.name}",
    )
    task = PublishTask(
        workspace_id=workspace_id,
        account_id=account.id,
        asset_id=asset.id,
        title=title,
        description=description,
        tags=tags,
        job_id=job.id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    threading.Thread(target=_run_publish_thread, args=(task.id,), daemon=True).start()
    return task


def _run_publish_thread(task_id: str) -> None:
    with SessionLocal() as db:
        task = db.get(PublishTask, task_id)
        if task is None or task.job_id is None:
            return
        job = db.get(Job, task.job_id)
        account = db.get(PublishAccount, task.account_id)
        asset = db.get(Asset, task.asset_id)
        if job is None or account is None or asset is None:
            return
        job.status = "running"
        job.message = f"发布中: {task.title or asset.name}"
        db.commit()
        try:
            handler = _ADAPTERS[account.platform]
            result = handler(account.config, asset, task)
            job.status = "succeeded"
            job.progress = 1.0
            job.result = result
            job.message = f"发布完成: {task.title or asset.name}"
            db.add(TaskEvent(job_id=job.id, type="publish.finished", payload=result))
        except Exception as exc:  # noqa: BLE001 — 适配器失败必须落到 job
            job.status = "failed"
            job.error = str(exc)[:500]
            job.message = "发布失败"
            db.add(TaskEvent(job_id=job.id, type="publish.failed", payload={"error": str(exc)[:500]}))
        db.commit()


def _metadata(task: PublishTask, asset: Asset) -> dict[str, Any]:
    return {
        "title": task.title,
        "description": task.description,
        "tags": list(task.tags or []),
        "asset_name": asset.name,
        "asset_id": asset.id,
    }


def _publish_folder(config: dict[str, Any], asset: Asset, task: PublishTask) -> dict[str, Any]:
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


def _publish_webhook(config: dict[str, Any], asset: Asset, task: PublishTask) -> dict[str, Any]:
    url = str(config.get("url", ""))
    payload = {**_metadata(task, asset), "file_path": str(resolve_key(asset.file_key))}
    response = httpx.post(url, json=payload, timeout=WEBHOOK_TIMEOUT_SECONDS)
    response.raise_for_status()
    return {"status_code": response.status_code, "response": response.text[:500]}


def _publish_mock(config: dict[str, Any], asset: Asset, task: PublishTask) -> dict[str, Any]:
    return {"mock": True, **_metadata(task, asset)}


_ADAPTERS: dict[str, Callable[[dict[str, Any], Asset, PublishTask], dict[str, Any]]] = {
    "folder": _publish_folder,
    "webhook": _publish_webhook,
    "mock": _publish_mock,
}


def task_with_status(db: Session, task: PublishTask) -> dict[str, Any]:
    job = db.get(Job, task.job_id) if task.job_id else None
    account = db.get(PublishAccount, task.account_id)
    asset = db.get(Asset, task.asset_id)
    return {
        "id": task.id,
        "workspace_id": task.workspace_id,
        "account_id": task.account_id,
        "account_name": account.name if account else "",
        "platform": account.platform if account else "",
        "asset_id": task.asset_id,
        "asset_name": asset.name if asset else "",
        "title": task.title,
        "description": task.description,
        "tags": list(task.tags or []),
        "status": job.status if job else "queued",
        "error": job.error if job else None,
        "result": job.result if job else {},
        "job_id": task.job_id,
        "created_at": task.created_at,
    }


def list_tasks(db: Session, workspace_id: str) -> list[PublishTask]:
    return list(
        db.scalars(
            select(PublishTask).where(PublishTask.workspace_id == workspace_id).order_by(PublishTask.created_at.desc())
        )
    )
