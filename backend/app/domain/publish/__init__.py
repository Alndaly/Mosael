"""发布内核(计划 §6.9 / Phase 13):账号 = 平台适配器 + 配置,
发布任务 = 成片素材 + 文案元数据 + 目标账号,执行走任务总线。

平台适配器注册表数据驱动(publish_targets 扩展位):v1 内置
folder(交付到本地目录 + 元数据 sidecar)、webhook(POST 给外部
自动化)。真平台(抖音/B站等)按同一契约叠加。
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
from app.db.models import Asset, Job, PublishAccount, PublishTask
from app.domain.jobs import create_job, emit_job_event, register_external_kind
from app.domain.notifications import notify
from app.media.paths import resolve_key

# 发布任务由桌面端执行器经 claim/report 驱动,跨后端重启存活;
# 声明执行模式是领域自己的事,任务总线不点名 publish。
register_external_kind("publish")


class PublishDomainError(ValueError):
    pass


# 平台注册表:config 字段描述驱动 UI 表单与校验。
# executor="local" 在后端线程内完成;executor="browser" 由桌面端发布器
# (Electron 内嵌浏览器 + 账号登录态)认领执行 —— 老版 mibu-video 同款架构。
# title_max 在创建时校验,避免任务在平台侧因超长标题晚失败。
PUBLISH_PLATFORMS: dict[str, dict[str, Any]] = {
    "folder": {
        "label": "本地目录",
        "description": "把成片拷贝到指定目录,并写入同名 .json 元数据(标题/简介/标签),方便手动上传或交给其他工具。",
        "config": {"directory": {"type": "string", "required": True, "description": "目标目录绝对路径"}},
        "executor": "local",
        "title_max": 300,
        "short_title": False,
    },
    "webhook": {
        "label": "Webhook",
        "description": "把文件路径与文案元数据 POST 给外部自动化(n8n / Zapier / 自建服务),由对方完成上传。",
        "config": {"url": {"type": "string", "required": True, "description": "接收 POST 的 URL"}},
        "executor": "local",
        "title_max": 300,
        "short_title": False,
    },
    "douyin": {
        "label": "抖音",
        "description": "由桌面端发布器用你已登录的抖音创作者账号自动上传;首次使用需在弹出的窗口里登录。",
        "config": {},
        "executor": "browser",
        "title_max": 30,
        "short_title": False,
    },
    "xiaohongshu": {
        "label": "小红书",
        "description": "由桌面端发布器用已登录的小红书账号自动上传;首次使用需登录。",
        "config": {},
        "executor": "browser",
        "title_max": 20,
        "short_title": False,
    },
    "weixin-channels": {
        "label": "微信视频号",
        "description": "由桌面端发布器用已登录的视频号助手账号自动上传;支持短标题。",
        "config": {},
        "executor": "browser",
        "title_max": 16,
        "short_title": True,
    },
    "bilibili": {
        "label": "Bilibili",
        "description": "由桌面端发布器用已登录的 B 站账号自动上传;首次使用需登录。",
        "config": {},
        "executor": "browser",
        "title_max": 80,
        "short_title": False,
    },
}

# 别名 → 规范 id(智能体/用户口语直达,老版同款)。
PLATFORM_ALIASES = {
    "抖音": "douyin", "dy": "douyin", "tiktok": "douyin",
    "小红书": "xiaohongshu", "xhs": "xiaohongshu", "rednote": "xiaohongshu",
    "视频号": "weixin-channels", "微信视频号": "weixin-channels", "channels": "weixin-channels",
    "wechat": "weixin-channels", "weixin": "weixin-channels",
    "b站": "bilibili", "哔哩哔哩": "bilibili", "bili": "bilibili",
}

# 老版任务状态词汇 1:1,移植的适配器直接映射。
TASK_STATUSES = (
    "pending", "running", "prepared", "success", "failed",
    "login_required", "waiting_manual", "permission_required", "blocked", "cancelled",
)
TERMINAL_TASK_STATUSES = frozenset({"prepared", "success", "failed", "cancelled"})
BINDING_STATUSES = ("unknown", "checking", "bound", "login_required", "manual_required", "permission_required")


def normalize_platform(platform: str) -> str:
    raw = (platform or "").strip()
    lowered = raw.lower()
    canonical = PLATFORM_ALIASES.get(raw, PLATFORM_ALIASES.get(lowered, lowered))
    if canonical not in PUBLISH_PLATFORMS:
        raise PublishDomainError(f"未知平台: {platform!r}(支持 {', '.join(PUBLISH_PLATFORMS)})")
    return canonical

WEBHOOK_TIMEOUT_SECONDS = 60


def create_account(
    db: Session, *, workspace_id: str, platform: str, name: str, config: dict[str, Any], proxy: str | None = None
) -> PublishAccount:
    platform = normalize_platform(platform)
    meta = PUBLISH_PLATFORMS[platform]
    for key, spec in meta["config"].items():
        if isinstance(spec, dict) and spec.get("required") and not str(config.get(key, "")).strip():
            raise PublishDomainError(f"平台 {platform} 缺少必填配置 {key}")
    account = PublishAccount(
        workspace_id=workspace_id, platform=platform, name=name, config=config, proxy=(proxy or "").strip() or None
    )
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
    short_title: str = "",
) -> PublishTask:
    if not account.enabled:
        raise PublishDomainError("发布账号已停用")
    if not asset.file_key:
        raise PublishDomainError("素材没有本地文件,无法发布")
    meta = PUBLISH_PLATFORMS[account.platform]
    title_max = int(meta.get("title_max", 300))
    if title and len(title) > title_max:
        raise PublishDomainError(f"{meta['label']} 标题最多 {title_max} 字(当前 {len(title)} 字)")

    is_browser = meta.get("executor") == "browser"
    job = create_job(
        db,
        workspace_id=workspace_id,
        kind="publish",
        payload={"account_id": account.id, "asset_id": asset.id, "platform": account.platform},
        message=(
            f"等待桌面发布器认领: {title or asset.name}" if is_browser else f"发布排队中: {title or asset.name}"
        ),
    )
    task = PublishTask(
        workspace_id=workspace_id,
        account_id=account.id,
        asset_id=asset.id,
        title=title,
        description=description,
        tags=tags,
        short_title=short_title,
        status="pending",
        job_id=job.id,
    )
    db.add(task)
    db.flush()
    # job payload 带上 task_id:任务中心点击发布任务可直达对应发布详情。
    job.payload = {**job.payload, "task_id": task.id}
    db.commit()
    db.refresh(task)
    if not is_browser:
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
            task.status = "success"
            emit_job_event(db, job.id, "publish.finished", result)
            notify(
                db,
                task.workspace_id,
                type="publish",
                title=f"发布成功: {task.title or asset.name}",
                link="#/publish",
                payload={"task_id": task.id, "platform": account.platform, "status": "success"},
            )
        except Exception as exc:  # noqa: BLE001 — 适配器失败必须落到 job
            job.status = "failed"
            job.error = str(exc)[:500]
            job.message = "发布失败"
            task.status = "failed"
            task.error_message = str(exc)[:500]
            emit_job_event(db, job.id, "publish.failed", {"error": str(exc)[:500]})
            notify(
                db,
                task.workspace_id,
                type="publish",
                title=f"发布失败: {task.title or asset.name}",
                body=str(exc)[:300],
                link="#/publish",
                payload={"task_id": task.id, "platform": account.platform, "status": "failed"},
            )
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


_ADAPTERS: dict[str, Callable[[dict[str, Any], Asset, PublishTask], dict[str, Any]]] = {
    "folder": _publish_folder,
    "webhook": _publish_webhook,
}


def task_with_status(db: Session, task: PublishTask) -> dict[str, Any]:
    job = db.get(Job, task.job_id) if task.job_id else None
    account = db.get(PublishAccount, task.account_id)
    asset = db.get(Asset, task.asset_id)
    platform = account.platform if account else ""
    is_browser = PUBLISH_PLATFORMS.get(platform, {}).get("executor") == "browser"
    # 浏览器平台展示富状态(pending/running/login_required/...),本地平台跟 job。
    status = task.status if is_browser else (job.status if job else "queued")
    return {
        "id": task.id,
        "workspace_id": task.workspace_id,
        "account_id": task.account_id,
        "account_name": account.name if account else "",
        "platform": platform,
        "asset_id": task.asset_id,
        "asset_name": asset.name if asset else "",
        "title": task.title,
        "description": task.description,
        "tags": list(task.tags or []),
        "status": status,
        "error": task.error_message or (job.error if job else None),
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
