"""工作流执行引擎:依赖驱动的并行 DAG 调度,进度与结果写任务总线。

引擎是纯调度器——拓扑排序、并行调度、条件分支路由、取消边界、事件与进度。
节点**行为**全部在执行器注册表(executors/)里;引擎对具体领域零 import,
新增节点类型不需要改这里。

引擎本身跑在独立线程里;内部再用线程池,前驱都完成的节点即可运行,彼此独立的
分支**同时**跑(节点多为 I/O 型:LLM/HTTP/子任务)。每个节点产生
workflow.node.started / finished 事件,job.progress 按已完成节点数推进;节点输出
写入上下文供后续节点用 {{节点id.键}} 引用或数据边绑定。
"""

from __future__ import annotations

import contextvars
import logging
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any

from sqlalchemy.orm import Session

from app.core.db import POOL_RESERVE, SessionLocal, pool_capacity
from app.core.i18n import DEFAULT_LOCALE, t, tr
from app.core.unit_of_work import unit_of_work
from app.db.models import Job, Workflow, WorkflowRevision
from app.domain.jobs import (
    blame,
    create_job,
    current_parent_job_id,
    dispatch_job,
    emit_job_event,
    finish_job,
    listening_for_progress,
    reset_parent_job,
    say,
    set_parent_job,
    stop_listening_for_progress,
)
from app.domain.billing.usage import run_costs
from app.domain.notifications import notify
from app.domain.workflows import (
    BRANCHING_NODE_TYPES,
    NESTED_BODY_TYPES,
    WorkflowDomainError,
    available_node_types,
    reference_dependencies,
    topo_order,
    validate_graph,
    with_run_params,
)
from app.domain.workflows.graph_rules import run_params
from app.domain.workflows.node_types import node_title
from app.domain.workflows.binding import apply_data_edges, check_number_fields, interpolate_node_config
from app.domain.workflows.executors import get_executor, run_preflights
from app.domain.workflows.executors.common import connection_handed_back
from app.domain.workflows.graph_run import GraphRun
from app.domain.workflows.revisions import WorkflowRevisionError, current_workflow_revision
from app.domain.workflows.run_outputs import keep_full_texts, snapshot
from app.domain.workflows.run_scope import halt_scope, halted, node_scope

logger = logging.getLogger(__name__)

MAX_PARALLEL_NODES = 8

#: **同时能有多少个节点占着数据库连接。**
#:
#: 这是全仓"先拿槽再开会话"那条规矩(见 domain/jobs 的 RENDER_SLOTS 那段注释)在工作流这一层
#: 的落地 —— 而此前它在这一层**不存在**:`MAX_PARALLEL_NODES = 8`、循环体的 4、嵌套深度 8,
#: 三个常数写在三个文件里,每一个单看都克制,**而它们是相乘的**。一个"8 个并行节点、每个都是
#: call_workflow"的图就要 8 + 8 ×(子驱动 + 子节点)条连接,而池子只有 15。越线之后是
#: `QueuePool limit of size 5 overflow 10 reached`,由 blame() 原样记进 job.error。
#:
#: **嵌套天然被压住**:这是模块级的一个信号量,子图的节点和父图的节点从同一份预算里取,
#: 所以乘积进不来。数从池子自己算出来(见 core/db.pool_capacity),不另写一个。
#:
#: 同一份预算里取,就不能有人攥着它等别人:在等的节点(executors.common.wait_until)和跑体的
#: 容器节点(循环 / 子图,见 run_node)都把它交还 —— 只有真在用数据库的叶子占着它。
NODE_CONNECTIONS = threading.Semaphore(max(1, pool_capacity() - POOL_RESERVE))


def start_workflow_job(
    db: Session, workflow: Workflow, *, created_by: str | None, params: dict[str, Any] | None = None, job: Job | None = None
) -> Job:
    """创建(或复用)workflow job，并把它固定到启动瞬间的不可变修订。"""
    try:
        revision = current_workflow_revision(db, workflow)
    except WorkflowRevisionError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    #: 开跑前的那一套检查(结构、必填、插件按跑的人、生成节点的文字、节点的运行前检查、字面量指定的
    #: 子工作流)只在 check_runnable 一处 —— 智能体开卡、定时任务启用与触发问的是同一个函数。
    check_runnable(db, workflow, params, job.created_by if job is not None else created_by)
    pinned_payload = {
        "workflow_id": workflow.id,
        "workflow_revision_id": revision.id,
        "workflow_revision": revision.revision,
        "workflow_graph_hash": revision.graph_hash,
        "params": params or {},
        "subject": workflow.name,
    }
    if job is None:
        job = create_job(
            db,
            workspace_id=workflow.workspace_id,
            kind="workflow",
            created_by=created_by,
            payload=pinned_payload,
            message="jobMsg_workflowQueued", message_params={"name": workflow.name},
        )
    else:
        # 调度器/子工作流可复用外部创建的 job；同样必须把修订钉进审计载荷。
        job.payload = {**(job.payload or {}), **pinned_payload}
    # 经总线派发,不自己起线程。此前这里是一句裸的 threading.Thread —— 于是工作流成了唯一
    # 绕开 dispatch_job 的 job kind,代价有两个:一是它的执行模式形同虚设(把 workflow 注册成
    # external 也照样在进程内跑),二是线程没有 JOB_THREAD_NAME,`wait_for_idle_jobs()` 按名字
    # 找不到它 —— 测试里 fresh_client() 就会在一个还活着的工作流线程底下 drop_all,炸成
    # 「no such table: task_events」,而且记在当时恰好在跑的那条**无关**用例头上。
    # (那正是 jobs.py 里 JOB_THREAD_NAME 的注释所断言的不变量:派发点只有一处 ——
    # 由 tests/test_jobs_are_dispatched_by_the_bus.py 守着。)
    workflow_id, revision_id, job_id, run_params = workflow.id, revision.id, job.id, params or {}
    dispatch_job(db, job, lambda: _run_workflow_thread(workflow_id, revision_id, job_id, run_params))
    return job


# ---------------- 开跑之前:这张图现在跑得起来吗 ----------------
#
# **这张图现在跑得起来吗** —— 开跑之前的那一套检查,只在这一处。
#
# 此前这套检查只写在 engine.start_workflow_job 里:点「运行」走得到它,别的入口走不到 ——
# 智能体的「运行工作流」卡开卡时只看工作流在不在,用户批准之后才在建任务时报缺参数;定时任务启用、
# 触发时只看工作流在不在,到点才失败;`call_workflow` 调的子工作流缺什么,要等父工作流前面的付费
# 节点全跑完、轮到它时才说。
#
# 检查不花钱、不写东西,任何一项不过就抛 WorkflowDomainError(说清是哪一项):
#
# 1. 结构与必填(validate_graph,开始节点叠上这一次的参数,见 with_run_params);插件节点按**跑的人**
#    能用的来判,用不了的说清为什么;
# 2. 「AI 生成素材」节点的提示词按选中的模型判(_check_generation_text);
# 3. 节点自己登记的运行前检查(executors.register_preflight / register_prefix_preflight)—— 插件节点选的连接
#    这个人用不用得了也在这里(和执行时 resolve_instance 同一条规矩);
# 4. 字面量指定的 `call_workflow` 子工作流:它那一版、带着这里交给它的入参,把同一套检查再走一遍;
# 5. 开始节点的选项参数选中的那一项要的前置条件(选项的 `requires`,见 _check_chosen_options)。
#
# 写在引擎里而不是单独一个模块:它要用执行器登记的运行前检查(executors.run_preflights),而执行器
# 回头调引擎(call_workflow)—— 单独拎出去就是又一个进环的模块(见 tests/test_import_layering)。


#: 子工作流最多往下查几层 —— 和执行时 call_workflow 的嵌套上限同一个数(见 executors.subworkflow)。
_MAX_CALL_DEPTH = 8


def check_runnable(
    db: Session,
    target: Workflow | dict[str, Any],
    params: dict[str, Any] | None,
    actor: str | None,
    *,
    workspace_id: str | None = None,
) -> None:
    """`target` 是一张工作流(查它**当前那一版**)或一张图;`params` 是这一次运行的参数;`actor` 是跑的人。

    给的是图时,`workspace_id` 必须说它在哪个工作区:节点的运行前检查按工作区判,字面量指定的子工作流也要
    在同一个工作区里才查得下去。
    """
    if isinstance(target, Workflow):
        _check_graph_runnable(db, _revision_graph(db, target), target.workspace_id, params, actor, seen=frozenset({target.id}))
        return
    if workspace_id is None:
        raise ValueError("check_runnable(graph) needs workspace_id")
    _check_graph_runnable(db, target, workspace_id, params, actor, seen=frozenset())


def _revision_graph(db: Session, workflow: Workflow) -> dict[str, Any]:
    try:
        return current_workflow_revision(db, workflow).graph
    except WorkflowRevisionError as exc:
        raise WorkflowDomainError.from_error(exc) from exc


def _check_graph_runnable(
    db: Session,
    graph: dict[str, Any],
    workspace_id: str,
    params: dict[str, Any] | None,
    actor: str | None,
    *,
    seen: frozenset[str],
) -> None:
    from app.domain.plugins.nodes import plugin_node_types

    extra_types = plugin_node_types(db, actor)
    errors = validate_graph(
        with_run_params(graph, params),
        extra_types=extra_types,
        explain_plugin_node=lambda node_type: _why_plugin_node_unusable(db, node_type, actor),
    )
    if errors:
        #: 几处问题连成一段,按这次请求的语言(每一句 validate_graph 已经按它翻好了)。
        raise WorkflowDomainError(tr("punct_sentenceSep").join(errors))
    _check_chosen_options(db, with_run_params(graph, params), workspace_id, actor)
    _check_generation_text(db, graph, actor)
    #: 节点登记的运行前检查,连同插件节点「轮到它时落得到一条连接吗」(按前缀登记的那一族,见 executors.content)。
    #: 带上这一次的开始参数:只引用开始参数的配置(音色、画幅……)在这里就有值(见 run_preflights)。
    run_preflights(db, graph, actor, workspace_id=workspace_id, params=params)
    if len(seen) <= _MAX_CALL_DEPTH:
        _check_called_workflows(db, graph, workspace_id, actor, seen=seen)


def _check_chosen_options(db: Session, graph: dict[str, Any], workspace_id: str, actor: str | None) -> None:
    """开始节点的选项参数(`param_options`)**选中的那一项**要的东西,此刻备齐了吗。

    选项可以声明它要什么(`requires`,模板前置条件的检查键):分析类模板的「数据来源」选了 TikHub,就得装了插件、
    接了连接、勾了工具。此前要等认完链接、跑到 TikHub 那一步才失败。只查**选中的**那一项 —— 选浏览器的人不该被
    TikHub 没配好拦住(图里 TikHub 那几个节点是通用插件节点,本来就没有运行前检查)。判据和模板库的前置条件同一个
    (templates.requirement_problem)。`graph` 是叠过这一次参数的(with_run_params);值不在选项里的已由校验拦下。
    """
    from app.core.i18n import tr
    from app.domain.workflows.templates import requirement_problem

    for node in graph.get("nodes") or []:
        if not isinstance(node, dict) or node.get("type") != "start":
            continue
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        params = config.get("params") if isinstance(config.get("params"), dict) else {}
        declared = config.get("param_options") if isinstance(config.get("param_options"), dict) else {}
        for name, options in declared.items():
            chosen = next((one for one in options if isinstance(one, dict) and one.get("value") == params.get(name)), None)
            if chosen is None or not chosen.get("requires"):
                continue
            problem = requirement_problem(db, user_id=actor or "", workspace_id=workspace_id, check=str(chosen["requires"]))
            if problem is None:
                continue
            others = tr("punct_listSep").join(
                str(one.get("label") or one.get("value")) for one in options if isinstance(one, dict) and one is not chosen
            )
            raise WorkflowDomainError(
                "wfErr_startOptionUnavailable",
                params={"param": name, "choice": chosen.get("label") or chosen.get("value"), "reason": problem, "others": others},
            )


def _why_plugin_node_unusable(db: Session, node_type: str, actor: str | None) -> str | None:
    from app.domain.plugins.nodes import why_unusable

    reason = why_unusable(db, node_type, actor)
    return str(reason) if reason is not None else None


def _templated(value: Any) -> bool:
    return isinstance(value, str) and "{{" in value


def _bound(graph: dict[str, Any]) -> set[tuple[str, str]]:
    """哪些 (节点, 字段) 由数据边供值 —— 它们的值要到运行时才知道。"""
    edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
    return {
        (str(edge.get("target")), str(edge.get("target_input")))
        for edge in edges
        if isinstance(edge, dict) and edge.get("kind") == "data" and edge.get("target_input")
    }


def _nodes(graph: Any, path: tuple[str, ...] = ()):
    """这张图里的节点,连同循环体 / 子图体里的,带着它所在那一层的图(数据边按层算)和报错时它叫什么
    (「外层容器 › 节点」,同 validate_graph)。"""
    if not isinstance(graph, dict):
        return
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        yield graph, node, " › ".join((*path, node_title(node)))
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        if str(node.get("type") or "") in NESTED_BODY_TYPES:
            yield from _nodes(config.get("body"), (*path, node_title(node)))


def _check_called_workflows(
    db: Session, graph: dict[str, Any], workspace_id: str, actor: str | None, *, seen: frozenset[str]
) -> None:
    """字面量指定的子工作流,带着这里交给它的入参,把同一套检查再走一遍;不过就说是调哪一张时不过。

    子工作流的名字是引用、由数据边供、入参整格是引用或由数据边供的,到运行时才知道,不在这里判。
    已经在这条调用链上的(自己调自己、互相调)不再往下查 —— 那是执行时防递归的事。
    """
    for layer, node, title in _nodes(graph):
        if node.get("type") != "call_workflow":
            continue
        node_id = str(node.get("id") or "")
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        bound = _bound(layer)
        target_id = config.get("workflow_id")
        inputs = config.get("inputs")
        if (
            not isinstance(target_id, str)
            or not target_id.strip()
            or _templated(target_id)
            or (node_id, "workflow_id") in bound
            or (node_id, "inputs") in bound
            or not isinstance(inputs if inputs is not None else {}, dict)
        ):
            continue
        child = db.get(Workflow, target_id.strip())
        if child is None or child.workspace_id != workspace_id:
            raise WorkflowDomainError(
                "wfErr_callNodeNotRunnable", params={"node": title, "reason": WorkflowDomainError("wfErr_calledWorkflowMissing")}
            )
        if child.id in seen:
            continue
        given = dict(inputs or {})
        #: 写成引用的入参(`{{start.v}}`、`小{{start.v}}`)值要到运行时才知道:运行前只能算「给了」。
        #: 把引用原文当参数交下去的话,它会被当成子工作流自己的配置去校验(「开始节点没有这些参数:start.v」),
        #: 接上游值的调用一律跑不起来。真到运行时它是空的、或不在选项里,由子工作流开跑时那一道照样拦下。
        later = {name for name, value in given.items() if _templated(value)}
        literal = {name: value for name, value in given.items() if name not in later}
        try:
            _check_graph_runnable(
                db, _given_at_run_time(_revision_graph(db, child), later), child.workspace_id, literal, actor,
                seen=seen | {child.id},
            )
        except WorkflowDomainError as exc:
            raise WorkflowDomainError(
                "wfErr_calledWorkflowNotRunnable", params={"node": title, "name": child.name, "reason": exc}
            ) from exc


def _given_at_run_time(graph: dict[str, Any], names: set[str]) -> dict[str, Any]:
    """这几个开始参数**会给、但运行前不知道值**:运行前不按必填、不按选项判它们,其余照旧。"""
    if not names:
        return graph
    nodes = []
    for node in graph.get("nodes") or []:
        if isinstance(node, dict) and node.get("type") == "start":
            config = dict(node.get("config") or {})
            required = config.get("required_params")
            if isinstance(required, list):
                config["required_params"] = [name for name in required if name not in names]
            options = config.get("param_options")
            if isinstance(options, dict):
                config["param_options"] = {name: one for name, one in options.items() if name not in names}
            node = {**node, "config": config}
        nodes.append(node)
    return {**graph, "nodes": nodes}


def _check_generation_text(db: Session, graph: Any, actor: str | None) -> None:
    """「AI 生成素材」节点的提示词要不要写,**运行前**按它选中的模型判(连同循环体 / 子图里的)。

    提示词不在节点声明里标必填 —— 要不要写是模型说的(描述符的 `prompt`,放大工作流不收),纯的
    validate_graph 看不到模型。可不在这里判的话,一个要提示词却空着的生成节点要等前面那些付费节点
    全跑完、轮到它时才报错(「工作流花了钱才说缺什么」,修过一次的那类)。所以在建任务之前,用和执行时
    同一条规矩(operations.check_text_inputs)、同一种解析(同一个人、同一个 provider / 连接 / 模型)
    判一遍。

    只判**字面量**:提示词是引用(`{{…}}`)或由数据边供值的,算给了 —— 它的值要到运行时才知道,那时
    漏斗照样会判;模型选择本身是引用的也跳过。模型解析不出来(没设默认、连接没了)不在这里说,那是执行时
    漏斗的事 —— 这里只管文字。
    """
    from app.core.i18n import fragment
    from app.domain.generation.operations import GenerationDomainError, check_text_inputs

    if not isinstance(graph, dict):
        return
    bound = _bound(graph)
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        for value in config.values():
            if isinstance(value, dict) and isinstance(value.get("nodes"), list):
                _check_generation_text(db, value, actor)
        if node.get("type") != "ai_generate":
            continue
        node_id = str(node.get("id") or "")
        prompt = config.get("prompt")
        choice = (config.get("provider"), config.get("provider_profile_id"), config.get("model"), config.get("kind"))
        if _templated(prompt) or (node_id, "prompt") in bound or any(_templated(one) for one in choice):
            continue
        # 点名了资产:它们的提示词描述在运行时才拼进来(domain/entities/mentions),空着的提示词不算缺。
        if config.get("entity_ids") and not str(prompt or "").strip():
            continue
        parameters = config.get("parameters") if isinstance(config.get("parameters"), dict) else {}
        try:
            check_text_inputs(
                db,
                user_id=actor,
                kind=str(config.get("kind", "image")).strip() or "image",
                provider=str(config.get("provider", "")),
                provider_profile_id=str(config.get("provider_profile_id") or "").strip() or None,
                model=str(config.get("model", "")),
                prompt=str(prompt or ""),
                parameters=dict(parameters),
            )
        except GenerationDomainError as exc:
            # 原因留成 key(fragment),按读的人的语言翻,不在这里冻成一种语言。
            raise WorkflowDomainError(
                "wfErr_generateNodeText",
                params={"node": str(node.get("name") or node_id), "reason": fragment(exc.key, **exc.params)},
            ) from exc


def _run_workflow_thread(workflow_id: str, revision_id: str, job_id: str, params: dict[str, Any]) -> None:
    # 线程就是入口:正常走完提交(失败也记在任务上、正常走完),真抛出去才回滚。
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        workflow = db.get(Workflow, workflow_id)
        revision = db.get(WorkflowRevision, revision_id)
        if job is None or workflow is None:
            return
        try:
            if revision is None or revision.workflow_id != workflow.id:
                raise WorkflowDomainError("wfErr_revisionMissing")
            logger.info("workflow job %s: running '%s'", job_id, workflow.name)
            run_workflow(db, workflow, revision, job, params)
            db.refresh(job)
            logger.info("workflow job %s: '%s' finished (%s)", job_id, workflow.name, job.status)
        except Exception as exc:  # noqa: BLE001 — 线程内兜底,失败必须落到 job 上
            logger.exception("workflow job %s ('%s') crashed", job_id, workflow.name)
            failure = _failure_payload(exc)
            #: 失败原因连同它的 key 一起落库 —— 接口按读的人的语言翻(见 jobs.blame)。
            if not finish_job(db, job, status="failed", **blame(exc)):
                return
            # JobOut 也保留一份终态现场。事件流是完整时间线；result.failure 让只读取 job 的
            # 消费方同样能展示诊断，而不是只能看到一句“失败”。
            job.result = {**(job.result or {}), "failure": failure}
            say(job, "jobMsg_workflowFailed", name=workflow.name)
            emit_job_event(db, job.id, "workflow.failed", failure)
            notify(
                db,
                workflow.workspace_id,
                type="workflow",
                title=f"工作流失败: {workflow.name}",
                body=str(exc),
                link="#/workflows",
                payload={"workflow_id": workflow.id, "job_id": job.id},
            )


def _failure_payload(exc: Exception) -> dict[str, Any]:
    """把异常变成任务总线可持久化的失败现场。

    **和任务上的失败原因同一个形状**(见 jobs.blame):那句话本身、它的文案 key 和参数 ——
    和节点事件的 `name` / `name_key` 同构,出口可以按读的人的语言重翻。不按位置截:此前
    `str(exc)[:500]` 把长一点的原因(条件节点带着两边的原值)切成半句话,切掉的恰好是后半截。
    """
    payload: dict[str, Any] = {key: value for key, value in blame(exc).items() if value}
    details = getattr(exc, "details", None)
    if isinstance(details, dict) and details:
        payload["details"] = details
    return payload


def execute_graph(
    graph: dict[str, Any],
    *,
    wf_id: str,
    initial_context: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    job: Job | None = None,
    db: Session | None = None,
    entry_is_root: bool = False,
) -> tuple[dict[str, Any], bool]:
    """跑一张图，有节点失败就把那个原因抛出来。返回 (最终上下文, 是否被取消)。

    要在失败时拿到已经落定的那些产物的，用 run_graph。
    """
    run = run_graph(
        graph, wf_id=wf_id, initial_context=initial_context, params=params, job=job, db=db, entry_is_root=entry_is_root,
    )
    if run.error is not None:
        raise run.error
    return run.context, run.cancelled


def run_graph(
    graph: dict[str, Any],
    *,
    wf_id: str,
    initial_context: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    job: Job | None = None,
    db: Session | None = None,
    entry_is_root: bool = False,
) -> GraphRun:
    """依赖驱动的并行执行内核(顶层工作流与循环体/子图共用):前驱全完成才可运行,彼此独立的
    分支**同时**跑(线程池)。条件分支按 source_handle 匹配才算活跃;未被活跃入边触达的节点整段
    跳过(Dify 语义)。节点失败不抛出，连同失败那一刻已经落定的上下文一起交回(见 GraphRun)。

    - 顶层:传 job + db,发事件/进度、支持取消;只有 start 类型是入口。
    - 子图(循环体等):不传 job;`entry_is_root=True` 让无入边节点也作为入口;用 initial_context
      播种(如 {loop:{item,index}})。子图捕获外层 parent job，并在每层线程池节点里恢复归属和取消边界。
    """
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
    #: 一个节点要等**所有**上游落定才开始:连线的来源,加上它 `{{…}}` 引用到的节点(引用即依赖,
    #: 见 workflows.reference_dependencies)。后者只管先后,不管该不该跑 —— 那是 incoming_active 的事。
    references = reference_dependencies(graph)
    waits_for = {nid: {str(edge.get("source")) for edge in incoming[nid]} | references.get(nid, set()) for nid in nodes_by_id}
    total = max(len(order_ids), 1)
    wf_job_id = job.id if job is not None else current_parent_job_id()
    has_job = job is not None and db is not None

    context: dict[str, Any] = dict(initial_context or {})
    executed: set[str] = set()
    done: set[str] = set()  # executed ∪ skipped
    lock = threading.Lock()

    def is_cancelled(db: Session | None = None) -> bool:
        """这一轮被取消了吗。

        `db` 给了就**复用它**,别再开第二条连接。原先 `run_node` 在自己的会话里面调这个函数,
        而它又开一条 —— 每个节点起步的一瞬间占 2 条,8 个并行节点加驱动线程就是 17,而池子
        只有 15:**顶层单独就能越线**。
        """
        if wf_job_id is None:
            return False
        if db is not None:
            parent = db.get(Job, wf_job_id)
            return parent is None or parent.status not in ("queued", "running")
        with SessionLocal() as check_db:
            parent = check_db.get(Job, wf_job_id)
            return parent is None or parent.status not in ("queued", "running")

    #: 节点类型的元数据 —— 只有要发事件时才用得到(节点叫什么)。**和启动前校验同一份组装**
    #: (内置 + 插件,见 available_node_types):此前这里只查内置的 NODE_TYPES,于是一个没起名字的
    #: 插件节点(智能体加节点时就不写名字,见 graph_ops.add_node)一开跑就在取名字这一步
    #: KeyError —— 校验认得它、执行器也认得它,偏偏是给事件取个名字把整条工作流带崩了。
    registry = available_node_types(db) if has_job else {}

    def node_label(nid: str) -> str:
        """这个节点在事件里叫什么。**回退到目录时要翻** —— 那一格存的是 i18n key。

        事件进 `task_events`,前端的执行历史原样把 `name` 画出来,而前端**没有任何
        `wfNode_` 的字典**(全仓零命中)。所以不翻的话,执行历史里那一行就是
        `wfNode_scene_render`。

        和 `say()` 同构:这里渲染成默认语言,`name_key` 一起进 payload,出口可以按读的人
        的语言重翻。平时走不到这条回退(模板和手工建的节点都有名字),只有智能体建的、
        或者名字被清空的才会露出来 —— 而那正是最难发现的那一类。
        """
        return str(nodes_by_id[nid].get("name") or t(registry[node_types[nid]]["label"], DEFAULT_LOCALE))

    def node_label_key(nid: str) -> str:
        """节点名的 key(节点自己有名字时为空 —— 那是用户写的字,不是文案)。"""
        return "" if nodes_by_id[nid].get("name") else str(registry[node_types[nid]]["label"])

    def event(kind: str, payload: dict[str, Any]) -> None:
        if has_job:
            emit_job_event(db, job.id, kind, payload)
            db.commit()

    def node_event(kind: str, nid: str, **fields: Any) -> None:
        """节点事件。名字只在真要发的时候才取 —— 内嵌子图(循环体 / subgraph)不发事件。"""
        if has_job:
            event(kind, {"node_id": nid, "name": node_label(nid), "name_key": node_label_key(nid), **fields})

    def node_finished(nid: str, outputs: dict[str, Any]) -> None:
        """节点跑完:事件里是有界的快照。被截断的文字(顶层的、嵌在列表 / 对象里的)另存全文(见
        run_outputs.snapshot),事件里的 `truncated` 说哪几处被截了(从输出名开始的点号路径)、全文多少字
        —— 界面据此标明「已截断」,复制 / 下载按路径去取全文。"""
        shown, texts = snapshot(outputs)
        if has_job and texts:
            keep_full_texts(db, job.id, nid, texts)
        truncated = {"truncated": {key: len(value) for key, value in texts.items()}} if texts else {}
        node_event("workflow.node.finished", nid, outputs=shown, **truncated)

    def is_entry(nid: str) -> bool:
        # start 类型永远是入口;子图里无入边的根也是入口。
        if node_types.get(nid) == "start":
            return True
        return entry_is_root and not incoming.get(nid)

    def incoming_active(nid: str) -> bool:
        node_edges = incoming.get(nid, [])
        if not node_edges:
            return False
        # **有控制边时只看控制边。** 数据边只说"这个值从哪来"(同时约束先后),不说"该不该跑"。
        # 此前两种边一视同仁:一个挂在条件分支"真"出口上的节点,只要另有一条数据边从别处取值,
        # 分支为假时也照跑 —— 整片生成里没有口播的那一镜,就这样拿着空素材去接口播而失败。
        # 只有数据边(画布上把控制边折叠成了数据边)时,由数据边决定,和以前一样。
        control = [edge for edge in node_edges if str(edge.get("kind", "")) != "data"]
        if control:
            node_edges = control
        for edge in node_edges:
            source = str(edge.get("source"))
            with lock:
                if source not in executed:
                    continue
                source_result = context.get(source, {}).get("result") if isinstance(context.get(source), dict) else None
            # 路由只属于控制边(见 BRANCHING_NODE_TYPES):接 `result` 输出的数据边两个分支都要跑。
            if node_types.get(source) in BRANCHING_NODE_TYPES and str(edge.get("kind", "")) != "data":
                wanted = str(edge.get("source_handle") or "true")
                if wanted != ("true" if source_result else "false"):
                    continue
            return True
        return False

    def run_node(nid: str) -> dict[str, Any]:
        # 排队到这一刻,这一轮(或外面哪一层)已经在停了:不开始(见 stopping)。
        if halted():
            raise WorkflowDomainError("wfErr_cancelled")
        node = nodes_by_id[nid]
        ntype = node_types[nid]
        with lock:
            snapshot = dict(context)
        # **先插值字面量,再覆盖数据边的值** —— 顺序就是这条规矩的全部(见 binding.apply_data_edges)。
        config = interpolate_node_config(ntype, dict(node.get("config") or {}), snapshot)
        config = check_number_fields(ntype, apply_data_edges(nid, config, edges, snapshot))
        if ntype == "start":
            return run_params(config.get("params"), params)
        handler = get_executor(ntype)
        if handler is None:
            raise WorkflowDomainError("wfErr_noExecutor", params={"type": ntype})
        # Each pool has new threads, including nested graphs: restore the captured parent explicitly.
        token = set_parent_job(wf_job_id)
        # 节点里的长活(插件跑一张 ComfyUI 工作流)报的进度,记成这个节点的事件 —— 执行面板上看得到
        # 「采样 12/20」,而不是一个转了十分钟的圈。内嵌子图不发节点事件,也就不听。
        listening = listening_for_progress(progress_listener(nid) if has_job else None)
        try:
            # **先拿预算,再开会话** —— 顺序就是这条规矩的全部(见 NODE_CONNECTIONS)。
            # 反过来的话,等的那个线程已经把连接攥在手里了。
            with NODE_CONNECTIONS, SessionLocal() as node_db:  # 每节点独立 session(非线程安全)
                if is_cancelled(node_db):
                    raise WorkflowDomainError("wfErr_cancelled")
                # 工作流本身就是节点的运行作用域(RunScope:工作区、id、名字),直接给它。
                wf = node_db.get(Workflow, wf_id)
                if ntype in NESTED_BODY_TYPES:
                    #: **容器节点跑体的时候不占连接,也不占预算。** 它的活儿全在体里,体里的节点从同一份
                    #: 预算里自己拿;容器攥着不放,嵌套几层、并行几项就把预算吃光,体里的叶子永远拿不到
                    #: —— 死锁,取消也叫不醒(叶子卡在拿预算上)。和节点里的「等」同一个做法。
                    with connection_handed_back(node_db), node_scope(nid):
                        outputs = handler(node_db, wf, config)
                else:
                    with node_scope(nid):
                        outputs = handler(node_db, wf, config)
                # **节点跑完就是它的事务边界。** 只在成功时提交:失败节点半途 flush 的东西不该留下。
                # 账不在此列 —— 付过费的调用在调用方回滚之后由记账那一层补写(见 domain/billing/usage
                # 的 _settle_usage),这里不用为它破例。
                node_db.commit()
                return outputs
        finally:
            stop_listening_for_progress(listening)
            if token is not None:
                reset_parent_job(token)

    def progress_listener(nid: str) -> Any:
        """一个节点的进度上报 → `workflow.node.progress` 事件。

        在节点的线程里被调,所以**自己开一个短会话**写事件:引擎的会话不是线程安全的,而节点的会话
        只在节点成功时提交(见上面的事务边界),不能为了一条进度提前提交它。
        """

        def listen(fraction: float, message: str) -> None:
            with unit_of_work() as progress_db:
                emit_job_event(progress_db, job.id, "workflow.node.progress", {
                    "node_id": nid, "name": node_label(nid), "name_key": node_label_key(nid),
                    "progress": round(fraction, 4), "message": message,
                })

        return listen

    processed = 0
    scheduled: set[str] = set()
    error: Exception | None = None
    failed_node = ""
    cancelled = False

    # 「停」信号先于线程池压上:节点提交时带走的上下文里要有它(见 workflows.run_scope)。
    with halt_scope() as halt, ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_NODES, total)) as pool:
        futures: dict[Any, str] = {}

        def stopping() -> bool:
            """这一轮该不该再往下调度:外层工作流落了终态,或者**哪一层图立了停的信号**。

            后者此前只有节点里的「等」看(common.wait_until):循环体、子图的这一层调度只看外层任务的
            状态,于是兄弟节点失败、整条工作流已经失败之后,循环照样一项一项跑完 —— 每一项都在花钱。
            """
            return halted() or is_cancelled()

        def schedule_ready() -> None:
            nonlocal processed, cancelled
            if stopping():
                # 每个节点都已落定的图不算被叫停:它已经跑完了。并发遍历里别的项失败的那一刻,
                # 恰好跑完最后一个节点的这一项是完整的,不该被记成「没跑完」。
                if len(done) < len(order_ids):
                    cancelled = True
                return
            for nid in order_ids:
                if nid in scheduled:
                    continue
                if not waits_for[nid] <= done:
                    continue
                scheduled.add(nid)
                if not is_entry(nid) and not incoming_active(nid):
                    with lock:
                        done.add(nid)
                    node_event("workflow.node.skipped", nid)
                    processed += 1
                    if has_job:
                        job.progress = processed / total
                        db.commit()
                    continue
                node_event("workflow.node.started", nid, node_type=node_types[nid])
                futures[pool.submit(contextvars.copy_context().run, run_node, nid)] = nid

        schedule_ready()
        while futures and error is None and not cancelled:
            if stopping():
                cancelled = True
                break
            completed, _ = wait(list(futures.keys()), timeout=0.5, return_when=FIRST_COMPLETED)
            for future in completed:
                nid = futures.pop(future)
                try:
                    outputs = future.result()
                except Exception as exc:  # noqa: BLE001 —— 任一节点失败即整流失败
                    if is_cancelled():
                        # 取消在前、失败在后:这一步是**被取消的**。运行名下的东西随取消被收走(浏览器会话关掉、
                        # 子任务取消),等着它们的节点随即失败,报的是被收走那一方的话(「会话已关闭」)——
                        # 写进执行历史就像是会话自己出了问题。
                        cancelled = True
                        node_event("workflow.node.failed", nid,
                                   error=t("jobErr_cancelled", DEFAULT_LOCALE), error_key="jobErr_cancelled")
                        break
                    error, failed_node = exc, nid
                    node_event("workflow.node.failed", nid, **_failure_payload(exc))
                    # **失败让这一轮停下。** 还在跑的兄弟节点做完了也没人要:它们正在等的子任务
                    # 由等的那一方取消掉(见 executors.common.wait_until),而不是陪它们跑完。
                    halt.set()
                    break
                with lock:
                    context[nid] = outputs
                    executed.add(nid)
                    done.add(nid)
                processed += 1
                node_finished(nid, outputs)
                if has_job:
                    job.progress = processed / total
                    db.commit()
            if error is None and not cancelled:
                schedule_ready()
        if cancelled:
            halt.set()
            event("workflow.cancelled", {"pending": len(futures)})
            for pending_nid in futures.values():
                node_event("workflow.node.failed", pending_nid,
                           error=t("jobErr_cancelled", DEFAULT_LOCALE), error_key="jobErr_cancelled")
        elif error is not None:
            # 失败之后还在飞的兄弟节点:等它们停下,各自落一个终态事件 —— 只有 started 的话,
            # 执行历史会把它们永远画成「运行中」。
            wait(list(futures.keys()))
            for future, pending_nid in futures.items():
                failure = future.exception()
                if failure is not None:
                    node_event("workflow.node.failed", pending_nid, **_failure_payload(failure))
                else:
                    node_finished(pending_nid, future.result())

    cancelled = cancelled or is_cancelled()
    if cancelled:
        return GraphRun(context, True)
    return GraphRun(context, False, error, failed_node if error is not None else "")


def run_workflow(
    db: Session,
    workflow: Workflow,
    revision: WorkflowRevision,
    job: Job,
    params: dict[str, Any],
) -> dict[str, Any]:
    """执行固定修订；编辑当前工作流不会改变已排队任务的图。"""
    graph = revision.graph
    node_types = {str(node["id"]): str(node.get("type")) for node in (graph.get("nodes") or [])}
    if not finish_job(db, job, status="running"):
        db.commit()
        return {}
    say(job, "jobMsg_workflowRunning", name=workflow.name)
    db.commit()

    run = run_graph(graph, wf_id=workflow.id, params=params, job=job, db=db)
    context = run.context
    if run.cancelled:
        return context
    if run.error is not None:
        # 失败的任务结果里照样留下**已经跑完的那些节点**的产物(出好的图、建好的项目)—— 失败原因由外层兜底
        # 补进同一份结果(见 _run_workflow_thread)。此前只剩一句原因，付过钱的产物只能去执行历史里一条条翻。
        job.result = {
            "workflow_revision_id": revision.id,
            "workflow_revision": revision.revision,
            "workflow_graph_hash": revision.graph_hash,
            "context": {nid: snapshot(out)[0] for nid, out in context.items()},
            #: 失败了,已经花掉的钱照样汇总(见 billing.usage.run_costs)。
            "costs": run_costs(db, job.id),
        }
        raise run.error

    # 「输出」节点声明的具名输出:被 call_workflow 调用时,调用方拿的就是这个契约(见 executors/subworkflow)。
    #: **图里有输出节点,结果里才有 `output` 这一格。** 此前总写一个空字典,于是调用一张没有输出节点
    #: 的工作流静默拿到 `{}`,call_workflow 那句「加一个输出节点」永远说不出口。有输出节点、这次恰好
    #: 没走到(条件分支)的,仍是一份空的具名输出 —— 契约成立,只是这次什么都没给。
    declares_output = "output" in node_types.values()
    output_values: dict[str, Any] = {}
    for nid, out in context.items():
        if node_types.get(nid) == "output" and isinstance(out, dict):
            output_values.update(out.get("output") or {})

    if not finish_job(db, job, status="succeeded"):
        db.commit()
        return context
    job.progress = 1.0
    say(job, "jobMsg_workflowDone", name=workflow.name)
    job.result = {
        "workflow_revision_id": revision.id,
        "workflow_revision": revision.revision,
        "workflow_graph_hash": revision.graph_hash,
        "context": {nid: snapshot(out)[0] for nid, out in context.items()},
        **({"output": output_values} if declares_output else {}),
        #: 这次运行花了多少钱:大模型的调用挂在运行上,生成、配音挂在子任务上,一起算(见 billing.usage.run_costs)。
        "costs": run_costs(db, job.id),
    }
    emit_job_event(
        db,
        job.id,
        "workflow.finished",
        {"nodes": len(node_types), "executed": len(context), "workflow_revision": revision.revision},
    )
    db.commit()
    return context
