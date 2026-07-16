"""工作流执行引擎:拓扑序逐节点执行,进度与结果写任务总线。

引擎跑在独立线程里,每个节点产生 workflow.node.started / finished 事件,
job.progress 按已完成节点数推进;节点输出写入上下文供后续节点用
{{节点id.键}} 引用。子任务型节点(导出/AI 生成)复用既有 job 执行器,
引擎轮询其终态。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.db.models import Job, ProviderProfile, TaskEvent, Transcript, Workflow
from app.domain.jobs import create_job
from app.domain.notifications import notify
from app.domain.workflows import NODE_TYPES, WorkflowDomainError, interpolate, topo_order, validate_graph

logger = logging.getLogger(__name__)

CHILD_JOB_TIMEOUT_SECONDS = 15 * 60
CHILD_POLL_SECONDS = 2.0
LLM_TIMEOUT_SECONDS = 120


def start_workflow_job(
    db: Session, workflow: Workflow, *, params: dict[str, Any] | None = None, job: Job | None = None
) -> Job:
    """创建(或复用)workflow job 并启动执行线程。"""
    errors = validate_graph(workflow.graph)
    if errors:
        raise WorkflowDomainError("；".join(errors))
    if job is None:
        job = create_job(
            db,
            workspace_id=workflow.workspace_id,
            kind="workflow",
            payload={"workflow_id": workflow.id, "params": params or {}},
            message=f"工作流排队中: {workflow.name}",
        )
        db.commit()
    threading.Thread(
        target=_run_workflow_thread,
        args=(workflow.id, job.id, params or {}),
        daemon=True,
    ).start()
    return job


def _run_workflow_thread(workflow_id: str, job_id: str, params: dict[str, Any]) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        workflow = db.get(Workflow, workflow_id)
        if job is None or workflow is None:
            return
        try:
            run_workflow(db, workflow, job, params)
        except Exception as exc:  # noqa: BLE001 — 线程内兜底,失败必须落到 job 上
            logger.exception("Workflow %s failed", workflow_id)
            job.status = "failed"
            job.error = str(exc)[:500]
            job.message = "工作流失败"
            db.add(TaskEvent(job_id=job.id, type="workflow.failed", payload={"error": str(exc)[:500]}))
            notify(
                db,
                workflow.workspace_id,
                type="workflow",
                title=f"工作流失败: {workflow.name}",
                body=str(exc)[:300],
                link="#/workflows",
                payload={"workflow_id": workflow.id, "job_id": job.id},
            )
            db.commit()


def run_workflow(db: Session, workflow: Workflow, job: Job, params: dict[str, Any]) -> dict[str, Any]:
    """分支感知执行:只有从 start 沿「活跃连线」可达的节点才会运行。

    条件节点把 true/false 写进 result,出边按 source_handle 匹配才算活跃;
    未被任何活跃入边触达的节点整段跳过(Dify 语义),并发 skipped 事件。
    """
    order = topo_order(workflow.graph)
    edges = list(workflow.graph.get("edges") or [])
    total = max(len(order), 1)
    context: dict[str, dict[str, Any]] = {}
    executed: set[str] = set()

    def incoming_active(node_id: str) -> bool:
        node_edges = [edge for edge in edges if str(edge.get("target")) == node_id]
        if not node_edges:
            return False
        for edge in node_edges:
            source = str(edge.get("source"))
            if source not in executed:
                continue
            source_type = next((str(n.get("type")) for n in order if str(n.get("id")) == source), "")
            if source_type == "condition":
                wanted = str(edge.get("source_handle") or "true")
                actual = "true" if context.get(source, {}).get("result") else "false"
                if wanted != actual:
                    continue
            return True
        return False

    job.status = "running"
    job.message = f"工作流运行中: {workflow.name}"
    db.commit()

    for index, node in enumerate(order):
        node_id = str(node["id"])
        node_type = str(node["type"])
        node_name = str(node.get("name") or NODE_TYPES[node_type]["label"])

        if node_type != "start" and not incoming_active(node_id):
            db.add(
                TaskEvent(
                    job_id=job.id,
                    type="workflow.node.skipped",
                    payload={"node_id": node_id, "name": node_name},
                )
            )
            job.progress = (index + 1) / total
            db.commit()
            continue

        db.add(
            TaskEvent(
                job_id=job.id,
                type="workflow.node.started",
                payload={"node_id": node_id, "node_type": node_type, "name": node_name},
            )
        )
        db.commit()

        handler = _HANDLERS.get(node_type)
        if handler is None:
            raise WorkflowDomainError(f"节点类型 {node_type} 没有执行器")
        config = interpolate(dict(node.get("config") or {}), context)
        if node_type == "start":
            merged = dict(config.get("params") or {})
            merged.update(params or {})
            outputs = merged
        else:
            outputs = handler(db, workflow, config)
        context[node_id] = outputs
        executed.add(node_id)

        db.add(
            TaskEvent(
                job_id=job.id,
                type="workflow.node.finished",
                payload={"node_id": node_id, "name": node_name, "outputs": _trim_outputs(outputs)},
            )
        )
        job.progress = (index + 1) / total
        db.commit()

    job.status = "succeeded"
    job.progress = 1.0
    job.message = f"工作流完成: {workflow.name}"
    job.result = {"context": {node_id: _trim_outputs(outputs) for node_id, outputs in context.items()}}
    db.add(TaskEvent(job_id=job.id, type="workflow.finished", payload={"nodes": len(order), "executed": len(executed)}))
    db.commit()
    return context


def _trim_outputs(outputs: dict[str, Any]) -> dict[str, Any]:
    """事件/结果里只存可读摘要,长文本截断,复杂对象计数。"""
    trimmed: dict[str, Any] = {}
    for key, value in outputs.items():
        if isinstance(value, str):
            trimmed[key] = value if len(value) <= 2000 else value[:2000] + "…"
        elif isinstance(value, list):
            trimmed[key] = f"[{len(value)} items]"
        elif isinstance(value, (int, float, bool)) or value is None:
            trimmed[key] = value
        else:
            trimmed[key] = str(value)[:500]
    return trimmed


# ---------- 节点执行器 ----------


def _handle_llm(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    profile = _pick_profile(db, config.get("profile_id"))
    messages: list[dict[str, Any]] = []
    if config.get("system"):
        messages.append({"role": "system", "content": str(config["system"])})
    messages.append({"role": "user", "content": str(config.get("prompt", ""))})
    base_url = profile.base_url.rstrip("/")
    model = str(config.get("model") or profile.default_model)
    response = httpx.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {profile.api_key}"},
        json={"model": model, "messages": messages, "temperature": 0.4},
        timeout=LLM_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    text = str(response.json()["choices"][0]["message"]["content"]).strip()
    return {"text": text}


def _pick_profile(db: Session, profile_id: Any) -> ProviderProfile:
    if profile_id:
        profile = db.get(ProviderProfile, str(profile_id))
        if profile is None or not profile.enabled:
            raise WorkflowDomainError("指定的供应商配置不存在或已停用")
        return profile
    profile = db.scalars(
        select(ProviderProfile).where(ProviderProfile.enabled.is_(True)).order_by(ProviderProfile.created_at)
    ).first()
    if profile is None:
        raise WorkflowDomainError("没有可用的 AI 供应商,请先在设置里添加")
    return profile


def _handle_kb_search(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    from app.domain.kb import search

    limit = int(config.get("limit") or 5)
    results = search(db, workflow.workspace_id, str(config.get("query", "")), limit=limit)
    text = "\n\n".join(f"[{item['title']}] {item['snippet']}" for item in results)
    return {"text": text, "results": results}


def _handle_plugin_tool(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    from app.domain.plugins.registry import invoke_plugin_tool

    invocation = invoke_plugin_tool(
        db, str(config.get("plugin_id", "")), str(config.get("tool_name", "")), dict(config.get("input") or {})
    )
    if invocation.status != "succeeded":
        raise WorkflowDomainError(f"插件工具失败: {invocation.error or invocation.status}")
    return {"output": invocation.output}


def _handle_transcribe(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    from app.audio.service import start_transcription

    asset_id = str(config.get("asset_id", ""))
    child = start_transcription(db, asset_id)
    _wait_for_job(child.id)
    transcript = db.scalars(
        select(Transcript).where(Transcript.asset_id == asset_id).order_by(Transcript.id.desc())
    ).first()
    if transcript is None:
        raise WorkflowDomainError("转写完成但没有找到文稿")
    db.refresh(transcript)
    text = "\n".join(segment.text for segment in transcript.segments)
    return {"text": text}


def _handle_export(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    from app.domain.render import start_export

    child = start_export(db, str(config.get("sequence_id", "")))
    final = _wait_for_job(child.id)
    asset_id = str((final.result or {}).get("asset_id", ""))
    return {"asset_id": asset_id}


def _handle_generate(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    from app.domain.generation import create_generation_job
    from app.domain.generation.runner import start_generation_thread

    generation, child = create_generation_job(
        db,
        workspace_id=workflow.workspace_id,
        project_id=None,
        provider=str(config.get("provider", "mock")),
        model=str(config.get("model", "mock-image")),
        kind=str(config.get("kind", "image")),
        prompt=str(config.get("prompt", "")),
        parameters=dict(config.get("parameters") or {}),
        source_asset_ids=[],
    )
    db.commit()
    start_generation_thread(generation.id)
    _wait_for_job(child.id)
    db.refresh(generation)
    return {"asset_id": generation.result_asset_id or "", "generation_id": generation.id}


def _handle_condition(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    left = config.get("left")
    right = config.get("right")
    op = str(config.get("op", "equals"))
    left_text = "" if left is None else str(left)
    right_text = "" if right is None else str(right)

    def as_number(value: Any) -> float | None:
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return None

    if op == "equals":
        result = left_text == right_text
    elif op == "not_equals":
        result = left_text != right_text
    elif op == "contains":
        result = right_text in left_text
    elif op == "not_contains":
        result = right_text not in left_text
    elif op == "empty":
        result = not left_text.strip()
    elif op == "not_empty":
        result = bool(left_text.strip())
    elif op in ("gt", "lt"):
        left_num, right_num = as_number(left), as_number(right)
        if left_num is None or right_num is None:
            raise WorkflowDomainError(f"条件 {op} 需要数值,得到: {left_text!r} / {right_text!r}")
        result = left_num > right_num if op == "gt" else left_num < right_num
    else:
        raise WorkflowDomainError(f"未知条件运算符: {op}")
    return {"result": result}


HTTP_NODE_TIMEOUT_SECONDS = 60
HTTP_TEXT_CAP = 100_000


def _handle_http(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    method = str(config.get("method") or "GET").upper()
    url = str(config.get("url", ""))
    headers = {str(k): str(v) for k, v in dict(config.get("headers") or {}).items()}
    body = config.get("body")
    content = None if body in (None, "") or method == "GET" else str(body).encode()
    response = httpx.request(method, url, headers=headers, content=content, timeout=HTTP_NODE_TIMEOUT_SECONDS)
    text = response.text[:HTTP_TEXT_CAP]
    try:
        parsed: Any = response.json()
    except ValueError:
        parsed = None
    return {"status": response.status_code, "text": text, "json": parsed}


CODE_TIMEOUT_SECONDS = 20
CODE_OUTPUT_CAP = 256 * 1024
# 与插件运行时同一信任级别:本地用户自己写的代码,进程隔离 + 超时 + 输出上限。
_CODE_WRAPPER = """\
import json, sys
payload = json.load(sys.stdin)
scope = {"inputs": payload.get("inputs") or {}}
exec(payload["code"], scope)
print(json.dumps({"output": scope.get("output")}, ensure_ascii=False, default=str))
"""


def _handle_code(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    import subprocess
    import sys

    payload = json.dumps({"code": str(config.get("code", "")), "inputs": dict(config.get("input") or {})})
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-c", _CODE_WRAPPER],
            input=payload.encode(),
            capture_output=True,
            timeout=CODE_TIMEOUT_SECONDS,
            env={"PATH": "/usr/bin:/bin"},
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkflowDomainError(f"代码节点超时({CODE_TIMEOUT_SECONDS}s)") from exc
    if completed.returncode != 0:
        raise WorkflowDomainError(f"代码节点出错: {completed.stderr.decode(errors='replace')[:500]}")
    stdout = completed.stdout[:CODE_OUTPUT_CAP]
    try:
        return {"output": json.loads(stdout.decode())["output"]}
    except (ValueError, KeyError) as exc:
        raise WorkflowDomainError("代码节点输出无法解析(请把结果赋给 output 变量)") from exc


def _handle_template(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    # interpolate 已在 config 解析阶段完成,这里只需转成文本。
    return {"text": str(config.get("template", ""))}


def _handle_publish(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    from app.db.models import Asset, PublishAccount
    from app.domain.publish import start_publish

    account = db.get(PublishAccount, str(config.get("account_id", "")))
    if account is None or account.workspace_id != workflow.workspace_id:
        raise WorkflowDomainError("发布账号不存在")
    asset = db.get(Asset, str(config.get("asset_id", "")))
    if asset is None or asset.workspace_id != workflow.workspace_id:
        raise WorkflowDomainError("发布素材不存在")
    task = start_publish(
        db,
        workspace_id=workflow.workspace_id,
        account=account,
        asset=asset,
        title=str(config.get("title", "")),
        description=str(config.get("description", "")),
        tags=[],
    )
    final = _wait_for_job(task.job_id or "")
    return {"result": final.result or {}}


def _wait_for_job(job_id: str) -> Job:
    """轮询子 job 到终态(用独立会话,避免长事务)。"""
    deadline = time.monotonic() + CHILD_JOB_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is None:
                raise WorkflowDomainError("子任务不存在")
            if job.status == "succeeded":
                db.expunge(job)
                return job
            if job.status == "failed":
                raise WorkflowDomainError(f"子任务失败: {job.error or job.message}")
        time.sleep(CHILD_POLL_SECONDS)
    raise WorkflowDomainError("子任务超时")


_HANDLERS: dict[str, Callable[[Session, Workflow, dict[str, Any]], dict[str, Any]]] = {
    "start": lambda db, workflow, config: dict(config.get("params") or {}),
    "llm": _handle_llm,
    "kb_search": _handle_kb_search,
    "plugin_tool": _handle_plugin_tool,
    "transcribe_asset": _handle_transcribe,
    "export_sequence": _handle_export,
    "ai_generate": _handle_generate,
    "publish": _handle_publish,
    "condition": _handle_condition,
    "http_request": _handle_http,
    "code": _handle_code,
    "template": _handle_template,
}
