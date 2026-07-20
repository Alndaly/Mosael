"""工作流执行引擎:依赖驱动的并行 DAG 执行,进度与结果写任务总线。

引擎本身跑在独立线程里;内部再用线程池,前驱都完成的节点即可运行,彼此独立的
分支**同时**跑(节点多为 I/O 型:LLM/HTTP/子任务)。每个节点产生
workflow.node.started / finished 事件,job.progress 按已完成节点数推进;节点输出
写入上下文供后续节点用 {{节点id.键}} 引用或数据边绑定。子任务型节点(导出/AI 生成)
复用既有 job 执行器,引擎轮询其终态。
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any, Callable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.db.models import Asset, Job, Project, ProviderProfile, TaskEvent, Transcript, Workflow
from app.domain.jobs import create_job
from app.domain.notifications import notify
from app.domain.workflows import (
    NODE_TYPES,
    WorkflowDomainError,
    interpolate,
    topo_order,
    validate_body_graph,
    validate_graph,
)

# Loop nodes carry config that references the loop scope / body nodes ({{loop.*}}, {{body_node.x}}),
# which must NOT be resolved at the outer scope — they're interpolated per-iteration inside the
# loop handler / run_subgraph. LOOP_RAW_KEYS are the config fields kept verbatim for that reason.
LOOP_TYPES = frozenset({"loop_foreach", "loop_while"})
LOOP_RAW_KEYS = ("body", "output", "condition")
LOOP_WHILE_HARD_CAP = 1000
# foreach had no cap at all, while `while` was clamped — an asymmetry that mattered because
# `items` can come from a code, http_request or json_extract node, i.e. from remote data. Every
# iteration also accumulates its result (the whole sub-context when `output` is blank), so an
# unbounded list is a memory problem before it is a time problem, and nested loops multiply.
LOOP_FOREACH_HARD_CAP = 1000


def _interpolate_loop_config(config: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Interpolate a loop node's config against `context` but leave its body/output raw."""
    raw = {key: config.pop(key, None) for key in LOOP_RAW_KEYS if key in config}
    config = interpolate(config, context)
    config.update(raw)
    return config

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


def _apply_data_edges(
    node_id: str,
    config: dict[str, Any],
    edges: list[dict[str, Any]],
    context: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """数据边(kind="data")把上游输出值绑到目标输入,优先于字面量 / 内联 {{var}}。
    上游已执行(数据边同时是排序约束)才有值;拿不到就跳过、保留原字面量。"""
    for edge in edges:
        if str(edge.get("kind", "")) != "data" or str(edge.get("target", "")) != node_id:
            continue
        source = str(edge.get("source", ""))
        output = str(edge.get("source_output", ""))
        target_input = str(edge.get("target_input", ""))
        if target_input and source in context and output in context[source]:
            config[target_input] = context[source][output]
    return config


MAX_PARALLEL_NODES = 8


def run_workflow(db: Session, workflow: Workflow, job: Job, params: dict[str, Any]) -> dict[str, Any]:
    """依赖驱动的并行执行:一个节点的全部前驱都完成后才可运行,彼此独立的分支**同时**跑
    (线程池,节点多为 I/O 型:LLM / HTTP / 子任务)。

    分支语义不变:条件节点把 true/false 写进 result,出边按 source_handle 匹配才算活跃;
    未被任何活跃入边触达的节点整段跳过(Dify 语义)。编排(调度 + 事件 + job)只在主线程用
    传入的 db;每个节点在 worker 线程里用**各自的 SessionLocal**,互不干扰。
    """
    graph = workflow.graph
    order = topo_order(graph)  # 校验 DAG + 稳定顺序
    order_ids = [str(node["id"]) for node in order]
    nodes_by_id = {str(node["id"]): node for node in (graph.get("nodes") or [])}
    edges = list(graph.get("edges") or [])
    node_types = {nid: str(node.get("type")) for nid, node in nodes_by_id.items()}
    incoming: dict[str, list[dict[str, Any]]] = {nid: [] for nid in nodes_by_id}
    for edge in edges:
        source, target = str(edge.get("source")), str(edge.get("target"))
        if source in nodes_by_id and target in nodes_by_id:
            incoming[target].append(edge)
    total = max(len(order_ids), 1)
    wf_id, wf_name = workflow.id, workflow.name

    context: dict[str, dict[str, Any]] = {}
    executed: set[str] = set()
    done: set[str] = set()  # executed ∪ skipped
    lock = threading.Lock()

    def node_label(nid: str) -> str:
        return str(nodes_by_id[nid].get("name") or NODE_TYPES[node_types[nid]]["label"])

    def incoming_active(nid: str) -> bool:
        node_edges = incoming.get(nid, [])
        if not node_edges:
            return False
        for edge in node_edges:
            source = str(edge.get("source"))
            with lock:
                if source not in executed:
                    continue
                source_result = context.get(source, {}).get("result")
            if node_types.get(source) == "condition":
                wanted = str(edge.get("source_handle") or "true")
                if wanted != ("true" if source_result else "false"):
                    continue
            return True
        return False

    def run_node(nid: str) -> dict[str, Any]:
        node = nodes_by_id[nid]
        ntype = node_types[nid]
        with lock:
            snapshot = dict(context)
        config = _apply_data_edges(nid, dict(node.get("config") or {}), edges, snapshot)
        if ntype in LOOP_TYPES:
            config = _interpolate_loop_config(config, snapshot)
        else:
            config = interpolate(config, snapshot)
        if ntype == "start":
            merged = dict(config.get("params") or {})
            merged.update(params or {})
            return merged
        handler = _HANDLERS.get(ntype)
        if handler is None:
            raise WorkflowDomainError(f"节点类型 {ntype} 没有执行器")
        # 每个节点用独立 session(SQLAlchemy Session 非线程安全),workflow 也在本 session 重取。
        with SessionLocal() as node_db:
            wf = node_db.get(Workflow, wf_id)
            return handler(node_db, wf, config)

    job.status = "running"
    job.message = f"工作流运行中: {wf_name}"
    db.commit()

    processed = 0
    scheduled: set[str] = set()
    error: Exception | None = None
    cancelled = False

    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_NODES, total)) as pool:
        futures: dict[Any, str] = {}

        def schedule_ready() -> None:
            nonlocal processed
            for nid in order_ids:
                if nid in scheduled:
                    continue
                if not all(str(edge.get("source")) in done for edge in incoming.get(nid, [])):
                    continue
                scheduled.add(nid)
                # By TYPE, not by the literal id "start". A start node named anything else has
                # no incoming edges, so it failed this check and was skipped — and with it
                # everything downstream, while the run still reported success with an empty
                # context. run_node already dispatches on type, so the two halves disagreed.
                if node_types.get(nid) != "start" and not incoming_active(nid):
                    with lock:
                        done.add(nid)
                    db.add(TaskEvent(job_id=job.id, type="workflow.node.skipped", payload={"node_id": nid, "name": node_label(nid)}))
                    processed += 1
                    job.progress = processed / total
                    db.commit()
                    continue
                db.add(
                    TaskEvent(
                        job_id=job.id,
                        type="workflow.node.started",
                        payload={"node_id": nid, "node_type": node_types[nid], "name": node_label(nid)},
                    )
                )
                db.commit()
                futures[pool.submit(run_node, nid)] = nid

        schedule_ready()
        while futures and error is None and not cancelled:
            # 用户取消(cancel_job 把 job 翻 failed):不再调度新节点,在飞的节点跑完即止。
            db.refresh(job)
            if job.status == "failed":
                cancelled = True
                db.add(TaskEvent(job_id=job.id, type="workflow.cancelled", payload={"pending": len(futures)}))
                db.commit()
                break
            completed, _ = wait(list(futures.keys()), timeout=0.5, return_when=FIRST_COMPLETED)
            for future in completed:
                nid = futures.pop(future)
                try:
                    outputs = future.result()
                except Exception as exc:  # noqa: BLE001 —— 任一节点失败即整流失败
                    error = exc
                    break
                with lock:
                    context[nid] = outputs
                    executed.add(nid)
                    done.add(nid)
                processed += 1
                db.add(
                    TaskEvent(
                        job_id=job.id,
                        type="workflow.node.finished",
                        payload={"node_id": nid, "name": node_label(nid), "outputs": _trim_outputs(outputs)},
                    )
                )
                job.progress = processed / total
                db.commit()
            if error is None and not cancelled:
                schedule_ready()

    if error is not None:
        raise error
    if cancelled:
        return context

    job.status = "succeeded"
    job.progress = 1.0
    job.message = f"工作流完成: {wf_name}"
    job.result = {"context": {nid: _trim_outputs(out) for nid, out in context.items()}}
    db.add(TaskEvent(job_id=job.id, type="workflow.finished", payload={"nodes": len(order_ids), "executed": len(executed)}))
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


# 生成风格预设 → temperature(替代让用户填裸数值)。默认均衡。
_LLM_PRESET_TEMPS = {"precise": 0.1, "balanced": 0.4, "creative": 0.9}


def _handle_llm(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    profile = _pick_profile(db, config.get("profile_id"))
    messages: list[dict[str, Any]] = []
    if config.get("system"):
        messages.append({"role": "system", "content": str(config["system"])})
    messages.append({"role": "user", "content": str(config.get("prompt", ""))})
    base_url = profile.base_url.rstrip("/")
    model = str(config.get("model") or profile.default_model)
    temperature = _LLM_PRESET_TEMPS.get(str(config.get("preset") or "balanced"), 0.4)
    response = httpx.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {profile.api_key}"},
        json={"model": model, "messages": messages, "temperature": temperature},
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
    from app.db.models import KbDataset
    from app.domain.kb import search

    limit = int(config.get("limit") or 5)
    dataset_id = str(config.get("dataset_id", "")).strip()
    dataset = db.get(KbDataset, dataset_id) if dataset_id else None
    if dataset is None:
        # 未指定库时退回工作区内最早的知识库,保持节点可用。
        dataset = db.scalars(
            select(KbDataset)
            .where(KbDataset.workspace_id == workflow.workspace_id)
            .order_by(KbDataset.created_at)
        ).first()
    if dataset is None:
        return {"text": "", "results": []}
    results = search(db, dataset, str(config.get("query", "")), top_k=limit)
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


def _handle_json_extract(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    """Walk a JSON string/object by a dot path (list indices as integers). Missing → None."""
    source = config.get("source")
    data: Any = source
    if isinstance(source, str):
        try:
            data = json.loads(source)
        except ValueError:
            data = source  # not JSON — treat the raw string as the value
    value: Any = data
    for part in [p for p in str(config.get("path", "")).split(".") if p]:
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list):
            try:
                value = value[int(part)]
            except (ValueError, IndexError):
                value = None
        else:
            value = None
        if value is None:
            break
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False)
    return {"value": value, "text": text}


def _handle_text_transform(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    text = str(config.get("text", ""))
    op = str(config.get("op", "trim"))
    find = str(config.get("find", ""))
    if op == "trim":
        out = text.strip()
    elif op == "upper":
        out = text.upper()
    elif op == "lower":
        out = text.lower()
    elif op == "replace":
        out = text.replace(find, str(config.get("replace", "")))
    elif op == "regex_extract":
        match = re.search(find, text) if find else None
        out = "" if match is None else (match.group(1) if match.groups() else match.group(0))
    elif op == "length":
        out = str(len(text))
    else:
        raise WorkflowDomainError(f"未知文本处理方式: {op}")
    return {"text": out, "length": len(out)}


DELAY_MAX_SECONDS = 300


def _handle_delay(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    try:
        seconds = float(config.get("seconds") if config.get("seconds") not in (None, "") else 1)
    except (TypeError, ValueError):
        seconds = 1.0
    seconds = max(0.0, min(DELAY_MAX_SECONDS, seconds))
    time.sleep(seconds)
    return {"waited": seconds}


def _handle_synthesize(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    from app.audio.voices import start_synthesis

    child = start_synthesis(
        db, voice_id=str(config.get("voice_id", "")), text=str(config.get("text", "")), project_id=None
    )
    final = _wait_for_job(child.id)
    return {"asset_id": str((final.result or {}).get("asset_id", ""))}


def _handle_translate(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    from app.domain.translate import translate as translate_text

    text = str(config.get("text", ""))
    if not text.strip():
        return {"text": ""}
    return {
        "text": translate_text(
            db,
            text,
            str(config.get("target_lang") or "en"),
            engine=str(config.get("engine") or "google").lower(),
            profile_id=str(config.get("profile_id") or "") or None,
        )
    }


def _handle_notify(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    title = str(config.get("title", "")).strip()
    if not title:
        raise WorkflowDomainError("通知标题不能为空")
    notify(
        db,
        workflow.workspace_id,
        type="workflow",
        title=title,
        body=str(config.get("body", "")),
        link="#/workflows",
        payload={"workflow_id": workflow.id},
    )
    db.commit()
    return {"sent": True}


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


def run_subgraph(body: dict[str, Any], base_context: dict[str, Any], *, workflow_id: str) -> dict[str, Any]:
    """Run a nested loop-body sub-graph synchronously (topo order) and return its context.

    Reuses the same handlers, data-edge binding, {{var}} interpolation and condition-branch
    semantics as the main engine, minus the job/TaskEvent/parallelism machinery. `base_context`
    seeds the loop scope (e.g. {"loop": {"item": ..., "index": ...}}); body nodes reference it as
    {{loop.item}} / {{loop.index}} and each other as {{node_id.output}}.
    """
    errors = validate_body_graph(body)
    if errors:
        raise WorkflowDomainError("；".join(errors))
    nodes = list(body.get("nodes") or [])
    edges = list(body.get("edges") or [])
    nodes_by_id = {str(n["id"]): n for n in nodes}
    node_types = {nid: str(n.get("type")) for nid, n in nodes_by_id.items()}
    incoming: dict[str, list[dict[str, Any]]] = {nid: [] for nid in nodes_by_id}
    for edge in edges:
        source, target = str(edge.get("source")), str(edge.get("target"))
        if source in nodes_by_id and target in nodes_by_id:
            incoming[target].append(edge)

    context: dict[str, Any] = dict(base_context)
    executed: set[str] = set()

    def incoming_active(nid: str) -> bool:
        node_edges = incoming.get(nid, [])
        if not node_edges:
            return True  # a body root (no incoming) is an entry point → always runs
        for edge in node_edges:
            source = str(edge.get("source"))
            if source not in executed:
                continue
            if node_types.get(source) == "condition":
                wanted = str(edge.get("source_handle") or "true")
                if wanted != ("true" if context.get(source, {}).get("result") else "false"):
                    continue
            return True
        return False

    for node in topo_order(body):
        nid = str(node["id"])
        ntype = node_types[nid]
        if not incoming_active(nid):
            continue  # unreached branch — skip (Dify semantics)
        config = _apply_data_edges(nid, dict(node.get("config") or {}), edges, context)
        if ntype in LOOP_TYPES:
            config = _interpolate_loop_config(config, context)
        else:
            config = interpolate(config, context)
        handler = _HANDLERS.get(ntype)
        if handler is None:
            raise WorkflowDomainError(f"节点类型 {ntype} 没有执行器")
        with SessionLocal() as sub_db:
            wf = sub_db.get(Workflow, workflow_id)
            context[nid] = handler(sub_db, wf, config)
        executed.add(nid)
    return context


def _handle_loop_foreach(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    items = config.get("items")
    if isinstance(items, str):
        items = [line.strip() for line in items.splitlines() if line.strip()]
    if not isinstance(items, list):
        raise WorkflowDomainError("循环·遍历的 items 必须是列表(或多行文本)")
    body = config.get("body") or {"nodes": [], "edges": []}
    output_tpl = config.get("output", "")
    if len(items) > LOOP_FOREACH_HARD_CAP:
        raise WorkflowDomainError(
            f"循环·遍历的 items 有 {len(items)} 项,超过上限 {LOOP_FOREACH_HARD_CAP};请先筛选或分批"
        )
    results: list[Any] = []
    for index, item in enumerate(items):
        ctx = run_subgraph(body, {"loop": {"item": item, "index": index}}, workflow_id=workflow.id)
        if output_tpl:
            results.append(interpolate(output_tpl, ctx))
        else:
            results.append({nid: out for nid, out in ctx.items() if nid != "loop"})
    return {"results": results, "count": len(results)}


def _handle_asset_query(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    """Batch-select workspace assets by filters → {assets, ids, count}. Feeds loop_foreach.items."""
    kind = str(config.get("kind") or "all").strip()
    name_contains = str(config.get("name_contains") or "").strip()
    tags_raw = str(config.get("tags") or "").strip().replace("，", ",")
    wanted_tags = {tag.strip() for tag in tags_raw.split(",") if tag.strip()}
    try:
        limit = int(config.get("limit") or 50)
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 500))

    stmt = select(Asset).where(Asset.workspace_id == workflow.workspace_id)
    if kind and kind != "all":
        stmt = stmt.where(Asset.kind == kind)
    if name_contains:
        stmt = stmt.where(Asset.name.contains(name_contains))
    stmt = stmt.order_by(Asset.created_at.desc())
    rows = list(db.scalars(stmt))
    if wanted_tags:
        rows = [asset for asset in rows if wanted_tags & set(asset.tags or [])]
    rows = rows[:limit]

    assets = [
        {
            "id": asset.id,
            "name": asset.name,
            "kind": asset.kind,
            "duration": (asset.media_info or {}).get("duration"),
            "tags": list(asset.tags or []),
        }
        for asset in rows
    ]
    return {"assets": assets, "ids": [asset["id"] for asset in assets], "count": len(assets)}


def _id_list(value: Any) -> list[str]:
    """Accept either a comma-separated string or a real list.

    Both reach here legitimately: a hand-typed config gives a string, while `{{查询.ids}}`
    resolves to the list asset_query produced. Treating the list case as a string would
    stringify it and match nothing, with no error to show for it.
    """
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").replace("，", ",")
    return [part.strip() for part in text.split(",") if part.strip()]


def _handle_asset_tag(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    """Add / remove / replace tags on a batch of assets → {updated, count}."""
    asset_ids = _id_list(config.get("asset_ids"))
    tags = _id_list(config.get("tags"))
    mode = str(config.get("mode") or "add").strip() or "add"
    if mode not in ("add", "remove", "replace"):
        raise WorkflowDomainError(f"素材打标签:未知的模式 {mode}")
    if not asset_ids:
        raise WorkflowDomainError("素材打标签:没有可处理的素材 id")
    if not tags and mode != "replace":
        raise WorkflowDomainError("素材打标签:标签不能为空")

    updated: list[dict[str, Any]] = []
    for asset_id in asset_ids:
        asset = db.get(Asset, asset_id)
        # Cross-workspace ids are skipped rather than fatal: a workflow fed by a query cannot
        # produce them, and one fed by hand should not be able to reach another workspace.
        if asset is None or asset.workspace_id != workflow.workspace_id:
            continue
        current = list(asset.tags or [])
        if mode == "add":
            merged = current + [tag for tag in tags if tag not in current]
        elif mode == "remove":
            merged = [tag for tag in current if tag not in tags]
        else:
            merged = list(tags)
        # Assigning a new list matters: mutating asset.tags in place leaves the JSON column
        # unchanged as far as SQLAlchemy is concerned, and the write silently does nothing.
        asset.tags = merged
        updated.append({"id": asset.id, "name": asset.name, "tags": merged})
    db.commit()
    return {"updated": updated, "count": len(updated)}


def _handle_asset_update(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    """Rename assets and/or file them under a project → {updated, count}."""
    asset_ids = _id_list(config.get("asset_ids"))
    name = str(config.get("name") or "").strip()
    project_id = str(config.get("project_id") or "").strip()
    if not asset_ids:
        raise WorkflowDomainError("素材整理:没有可处理的素材 id")
    if not name and not project_id:
        raise WorkflowDomainError("素材整理:至少要设置新名称或目标项目")
    if project_id:
        project = db.get(Project, project_id)
        if project is None or project.workspace_id != workflow.workspace_id:
            raise WorkflowDomainError("素材整理:目标项目不存在,或不属于当前工作区")

    updated: list[dict[str, Any]] = []
    for index, asset_id in enumerate(asset_ids):
        asset = db.get(Asset, asset_id)
        if asset is None or asset.workspace_id != workflow.workspace_id:
            continue
        if name:
            # One name across many assets would produce N identical names, which is unusable
            # in a picker — number them instead.
            asset.name = name if len(asset_ids) == 1 else f"{name} {index + 1}"
        if project_id:
            asset.project_id = project_id
        updated.append({"id": asset.id, "name": asset.name, "project_id": asset.project_id})
    db.commit()
    return {"updated": updated, "count": len(updated)}


def _handle_project_create(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    name = str(config.get("name") or "").strip()
    if not name:
        raise WorkflowDomainError("新建项目:项目名不能为空")
    project = Project(workspace_id=workflow.workspace_id, name=name)
    db.add(project)
    db.commit()
    db.refresh(project)
    return {"project_id": project.id, "name": project.name}


def _truthy(value: Any) -> bool:
    """Loop-condition truthiness: real bools/None as-is; strings "false"/"0"/"" (any case) are False."""
    if isinstance(value, str):
        return value.strip().lower() not in ("", "false", "0", "no", "none")
    return bool(value)


def _handle_loop_while(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    body = config.get("body") or {"nodes": [], "edges": []}
    condition_tpl = str(config.get("condition") or "")
    output_tpl = config.get("output", "")
    try:
        max_iter = int(config.get("max_iterations") or 50)
    except (TypeError, ValueError):
        max_iter = 50
    max_iter = max(1, min(max_iter, LOOP_WHILE_HARD_CAP))
    results: list[Any] = []
    index = 0
    # Do-while: the condition references body outputs, so it can only be evaluated after a run.
    while index < max_iter:
        ctx = run_subgraph(body, {"loop": {"index": index}}, workflow_id=workflow.id)
        if output_tpl:
            results.append(interpolate(output_tpl, ctx))
        else:
            results.append({nid: out for nid, out in ctx.items() if nid != "loop"})
        index += 1
        if not condition_tpl:
            break  # no condition → run exactly once
        if not _truthy(interpolate(condition_tpl, ctx)):
            break
    return {"results": results, "count": len(results), "iterations": index}


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
    "json_extract": _handle_json_extract,
    "text_transform": _handle_text_transform,
    "delay": _handle_delay,
    "synthesize_speech": _handle_synthesize,
    "notify": _handle_notify,
    "translate": _handle_translate,
    "loop_foreach": _handle_loop_foreach,
    "loop_while": _handle_loop_while,
    "asset_query": _handle_asset_query,
    "asset_tag": _handle_asset_tag,
    "asset_update": _handle_asset_update,
    "project_create": _handle_project_create,
}
