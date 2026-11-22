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

from app.core.db import SessionLocal
from app.core.i18n import get_current_locale, speaking, t
from mosael_formats.i18n import DEFAULT_LOCALE
from app.core.unit_of_work import after_commit, unit_of_work
from app.db.models import Job, Workflow, WorkflowRevision
from app.domain.jobs import (
    blame,
    create_job,
    current_parent_job_id,
    dispatch_job,
    failure_payload,
    emit_job_event,
    finish_job,
    listening_for_progress,
    reopen_job,
    reset_parent_job,
    say,
    set_parent_job,
    stop_listening_for_progress,
)
from app.domain.workflows.graph_rules import (
    BRANCHING_NODE_TYPES,
    NESTED_BODY_TYPES,
    reference_dependencies,
    target_dependency_closure,
    topo_order,
    run_params,
    spending_nodes_in_graph,
)
from app.domain.workflows import readiness, settlement
from app.domain.workflows.errors import AwaitingApproval, WorkflowDomainError
from app.domain.workflows.node_types import available_node_types, node_title
from app.domain.workflows.authority import run_authority
from app.domain.workflows.binding import (
    apply_data_edges,
    check_number_fields,
    interpolate_node_config,
    one_asset_fields,
    with_referenced_assets,
)
from app.domain.workflows.executors.registry import get_executor
from app.domain.workflows.executors.common import connection_handed_back
from app.domain.workflows import node_budget, approvals
from app.domain.workflows.graph_run import GraphResume, GraphRun, RedoRound
from app.domain.workflows.revisions import WorkflowRevisionError, current_workflow_revision
from app.domain.workflows.run_outputs import keep_full_texts, snapshot
from app.domain.workflows import run_steps
from app.domain.workflows.run_scope import continuing_run, halt_scope, halted, is_continuing, node_scope, step_frame, step_scope

logger = logging.getLogger(__name__)

MAX_PARALLEL_NODES = 8



def start_workflow_job(
    db: Session, workflow: Workflow, *, created_by: str | None, params: dict[str, Any] | None = None, job: Job | None = None,
    target_node: str | None = None,
) -> Job:
    """创建(或复用)workflow job，并把它固定到启动瞬间的不可变修订。

    `target_node` 给定时是「单跑一个节点」:只执行目标及其上游闭包(见 run_graph),预检也只查
    闭包内节点(见 _check_target_runnable);闭包外缺配置、缺连接不拦住这一次。
    """
    try:
        revision = current_workflow_revision(db, workflow)
    except WorkflowRevisionError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    #: 开跑前的那一套检查(结构、必填、插件按跑的人、生成节点的文字、节点的运行前检查、字面量指定的
    #: 子工作流)只在 check_runnable 一处 —— 智能体开卡、定时任务启用与触发问的是同一个函数。
    actor = job.created_by if job is not None else created_by
    target_sub: dict[str, Any] | None = None
    if target_node is not None:
        target_sub = readiness._check_target_runnable(db, workflow, revision.graph, target_node, params, actor)
    else:
        readiness.check_runnable(db, workflow, params, actor)
    #: 这一次要花跑的人的连接(钥匙、额度),而被执行的某一版他没担保:不开跑、一分钱不花,失败现场带着要认可的
    #: 那一版(ADR 0047)。不放进 check_runnable:那是「图本身跑不跑得起来」,定时任务启用、到点触发前都问它,
    #: 不过就停用任务 —— 而这一条是「这一版等主人认可」,任务该照常到点、每次记一条带「认可这一版」的失败。
    #: 挂在哪条运行底下:定时任务复用的包装任务还没钉修订,从它的上一层问起;子流程在调用它的那一层里。
    above = run_authority(db, job.parent_job_id if job is not None else current_parent_job_id())
    #: 单跑一个节点:只有闭包内(连同体里)有会花钱的节点,这次运行才花跑的人的钱 —— 闭包外一个 LLM
    #: 不该让一次纯模板节点的单跑等认可。
    if target_node is None or target_sub is None or spending_nodes_in_graph(target_sub):
        waiting = readiness.unvouched_spend(db, workflow, actor, above=above)
    else:
        waiting = None
    if waiting is not None:
        raise WorkflowDomainError(
            "wfErr_spendNotVouched",
            params={"workflow": waiting.workflow_name, "revision": waiting.revision},
            details=waiting.attest_details(),
        )
    pinned_payload = {
        "workflow_id": workflow.id,
        "workflow_revision_id": revision.id,
        "workflow_revision": revision.revision,
        "workflow_graph_hash": revision.graph_hash,
        "params": params or {},
        "subject": workflow.name,
        #: 单跑一个节点:运行历史据此标注「部分运行(目标:节点名)」(不改正文 schema,载荷里多两格)。
        **({"target_node_id": target_node, "target_node_name": node_title(
            next(node for node in revision.graph.get("nodes") or [] if str(node.get("id")) == target_node),
        )} if target_node is not None else {}),
        #: 发起运行的人的语言:运行时生成的那几句(用的是哪把嗓子、哪一项没做成……)照它说(见 i18n.speaking)。
        #: 定时任务这类没有请求的,是缺省语言。
        "locale": get_current_locale(),
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
    locale = pinned_payload["locale"]
    dispatch_job(db, job, lambda: _run_workflow_thread(workflow_id, revision_id, job_id, run_params, locale=locale, target_node=target_node))
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
# 这些检查住在 workflows/readiness:它们要用执行器登记的运行前检查、生成目录与插件连接,
# 不是 DAG 调度本身。引擎只在建任务前调它。


#: 子工作流最多往下查几层 —— 和执行时 call_workflow 的嵌套上限同一个数(见 executors.subworkflow)。
_MAX_CALL_DEPTH = 8


def _run_workflow_thread(
    workflow_id: str, revision_id: str, job_id: str, params: dict[str, Any], *, locale: str | None = None,
    target_node: str | None = None, resume: GraphResume | None = None, continuing: bool = False,
) -> None:
    # 线程就是入口:正常走完提交(失败也记在任务上、正常走完),真抛出去才回滚。
    with speaking(locale), unit_of_work() as db:
        job = db.get(Job, job_id)
        workflow = db.get(Workflow, workflow_id)
        revision = db.get(WorkflowRevision, revision_id)
        if job is None or workflow is None:
            return
        try:
            if revision is None or revision.workflow_id != workflow.id:
                raise WorkflowDomainError("wfErr_revisionMissing")
            logger.info("workflow job %s: running '%s'", job_id, workflow.name)
            run_workflow(db, workflow, revision, job, params, target_node=target_node, resume=resume, continuing=continuing)
            db.refresh(job)
            #: 停在「等人确认」上也是正常收场(见 _park_at_approval):这一句说"finished"只是日志,
            #: 任务那时仍是 running。别在这一句上读终态。
            logger.info("workflow job %s: '%s' finished (%s)", job_id, workflow.name, job.status)
        except Exception as exc:  # noqa: BLE001 — 线程内兜底,失败必须落到 job 上
            logger.exception("workflow job %s ('%s') crashed", job_id, workflow.name)
            failure = failure_payload(exc)
            #: 失败原因连同它的 key 一起落库 —— 接口按读的人的语言翻(见 jobs.blame)。
            if not finish_job(db, job, status="failed", **blame(exc)):
                return
            # JobOut 也保留一份终态现场。事件流是完整时间线；result.failure 让只读取 job 的
            # 消费方同样能展示诊断，而不是只能看到一句“失败”。
            job.result = {**(job.result or {}), "failure": failure}
            say(job, "jobMsg_workflowFailed", name=workflow.name)
            emit_job_event(db, job.id, "workflow.failed", failure)
            settlement.notify_failure(db, workflow, job.id, exc)


def execute_graph(
    graph: dict[str, Any],
    *,
    wf_id: str,
    initial_context: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    job: Job | None = None,
    db: Session | None = None,
    entry_is_root: bool = False,
    target_node: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """跑一张图，有节点失败就把那个原因抛出来。返回 (最终上下文, 是否被取消)。

    要在失败时拿到已经落定的那些产物的，用 run_graph。
    """
    run = run_graph(
        graph, wf_id=wf_id, initial_context=initial_context, params=params, job=job, db=db, entry_is_root=entry_is_root,
        target_node=target_node,
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
    target_node: str | None = None,
    resume: GraphResume | None = None,
) -> GraphRun:
    """依赖驱动的并行执行内核(顶层工作流与循环体/子图共用):前驱全完成才可运行,彼此独立的
    分支**同时**跑(线程池)。条件分支按 source_handle 匹配才算活跃;未被活跃入边触达的节点整段
    跳过(Dify 语义)。节点失败不抛出，连同失败那一刻已经落定的上下文一起交回(见 GraphRun)。

    - 顶层:传 job + db,发事件/进度、支持取消;只有 start 类型是入口。
    - 子图(循环体等):不传 job;`entry_is_root=True` 让无入边节点也作为入口;用 initial_context
      播种(如 {loop:{item,index}})。子图捕获外层 parent job，并在每层线程池节点里恢复归属和取消边界。
    - 单跑一个节点(`target_node`):只执行目标及其 waits_for 传递闭包(见 target_dependency_closure)
      ——目标跑完即收(闭包里全是它的上游,它完成时闭包已落定),闭包外节点「不在本次运行」:
      不执行、不计入进度 total、不算失败。闭包内无闭包依赖的节点作入口(等价 entry_is_root)。
    - **从暂停接着跑(`resume`)**:`done` 里的节点**直接跳过、绝不执行**,上下文从那份现场播种
      (见 GraphResume)。「等人确认」把一轮图拆成两半,这是后半截的入口。
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
    if target_node is not None:
        if target_node not in nodes_by_id:
            raise WorkflowDomainError(
                "wfErr_targetNotInScope" if readiness.node_in_nested_body(graph, target_node) else "wfErr_targetMissing",
                params={"node": target_node},
            )
        #: 单跑:闭包外整段「不在本次运行」。闭包的入边/引用来源全在闭包内(见 target_dependency_closure),
        #: 所以 restrict 之后 waits_for/incoming/条件分支逻辑原样成立;无闭包内依赖的节点作入口。
        closure = target_dependency_closure(graph, target_node)
        order_ids = [nid for nid in order_ids if nid in closure]
        entry_is_root = True
    total = max(len(order_ids), 1)
    wf_job_id = job.id if job is not None else current_parent_job_id()
    has_job = job is not None and db is not None
    #: 内嵌子图(循环体 / subgraph)自己不带 job,但体里的节点也该让子画布看见运行态:
    #: 事件记到外层 job 上,`scope` 说明是哪一层(见 step_scope)。
    event_scope = step_scope()
    inner_events = not has_job and bool(wf_job_id and event_scope)

    context: dict[str, Any] = dict(initial_context or {})
    executed: set[str] = set()
    done: set[str] = set()  # executed ∪ skipped
    #: **从暂停接着跑**:把现场播种进来。`done` 里的节点在调度那一步被直接跳过(见 schedule_ready),
    #: 于是它们**一个都不会被执行第二次** —— 前面烧过钱的节点不会重生一次。
    if resume is not None:
        context.update(resume.context)
        executed |= set(resume.executed)
        done |= set(resume.done)
    #: 这一层图在哪(见 run_steps):落定的节点按它记,从失败处继续时按它读回来。
    scope_key = step_scope()
    #: **从失败处继续**:这一层已经落定的节点读回来,同样跳过。被条件分支跳过的不用记,调度时照原来的产物算出同一个结果。
    #: 循环的每一轮、子图都走到这里:跑完的轮次里节点全部落定,这一轮瞬间走完,交出的还是当时那份。
    if is_continuing() and wf_job_id is not None:
        with SessionLocal() as steps_db:
            settled = run_steps.recorded(steps_db, wf_job_id, scope_key)
        context.update(settled)
        executed |= set(settled)
        done |= set(settled)
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

    def inner_label(nid: str) -> tuple[str, str]:
        """体内节点没有目录可查:用节点自己的名字;没起名字就用类型。前端有完整目录。"""
        node = nodes_by_id[nid]
        return str(node.get("name") or node_types[nid]), ""

    def node_event(kind: str, nid: str, **fields: Any) -> None:
        """节点事件。顶层记在外层 job 上;体内节点带 scope 记到外层 job,子画布据此点亮节点。"""
        if has_job:
            event(kind, {"node_id": nid, "name": node_label(nid), "name_key": node_label_key(nid), **fields})
        elif inner_events:
            name, name_key = inner_label(nid)
            with unit_of_work() as inner_db:
                emit_job_event(inner_db, wf_job_id, kind, {
                    "node_id": nid, "name": name, "name_key": name_key,
                    "scope": event_scope, **fields,
                })

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

    def routed_control(edge: dict[str, Any]) -> bool:
        """带路由语义的控制边:条件的真 / 假出口(写了 handle),或来源是会分支的节点(没写 handle 也是「真」)。"""
        return bool(edge.get("source_handle")) or node_types.get(str(edge.get("source"))) in BRANCHING_NODE_TYPES

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
            if any(routed_control(edge) for edge in control):
                # **有带路由语义的控制边时,由它定「该不该跑」。** 条件节点的「真 / 假」出口说的是"什么时候跑",
                # 而同格上那些**已经有一条同向数据线**的普通控制边只说"谁在谁前面"(数据线本身就在排先后,
                # 那条实线是画出来给人看的),不激活这一格。规范化此前正是替作者把这些边折掉来达到这个判法的 ——
                # 维护者 2026-10-16 不再折(见 ADR 0063),同一条规矩在这里明说,折与不折「谁该跑」完全一样。
                #
                # **没有同向数据线的那几条普通控制边照旧激活。** 它们不是"只排先后":同格上没有别的东西能排它,
                # 作者画它就是要这一格跑起来。两条官方模板靠这个:`reference_video_shots` 的 `describe`
                # (want_speech 的两个出口 + transcript_section→describe,整段是"要不要先转写再逐镜描述"),
                # `highlight_shorts` 的 `cut_clips`(has_clips 的真出口 + clips_project→cut_clips)。
                # 一并当成"只排先后"的话,这两格该跑的时候不跑了。
                paired = {
                    (str(edge.get("source", "")), str(edge.get("target", "")))
                    for edge in node_edges
                    if str(edge.get("kind", "")) == "data"
                }
                node_edges = [
                    edge for edge in control
                    if routed_control(edge) or (str(edge.get("source", "")), str(edge.get("target", ""))) not in paired
                ]
            else:
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
        #: config 的**原文**留着:引用在插值之后就成了一串十六进制,和手打进去的 id 分不开,而
        #: 「引用即发送」认的是引用(见 binding.with_referenced_assets)。
        written = dict(node.get("config") or {})
        config = interpolate_node_config(ntype, dict(written), snapshot)
        config = one_asset_fields(ntype, check_number_fields(ntype, apply_data_edges(nid, config, edges, snapshot)))
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
            # **先拿预算,再开会话** —— 顺序就是这条规矩的全部(见 node_budget)。
            # 反过来的话,等的那个线程已经把连接攥在手里了。
            with node_budget.NODE_CONNECTIONS, SessionLocal() as node_db:  # 每节点独立 session(非线程安全)
                if is_cancelled(node_db):
                    raise WorkflowDomainError("wfErr_cancelled")
                # 工作流本身就是节点的运行作用域(RunScope:工作区、id、名字),直接给它。
                wf = node_db.get(Workflow, wf_id)
                #: 提示词里引用到的素材并进声明了 `ref_assets_from` 的那一格(「引用即发送」)——
                #: 在手边有会话、有工作区、也有上游刚落定的值时做,是这一条语义唯一的实现处。
                config = with_referenced_assets(
                    node_db, wf.workspace_id, ntype, written, config, snapshot, node_types
                )
                if ntype in NESTED_BODY_TYPES:
                    #: **容器节点跑体的时候不占连接,也不占预算。** 它的活儿全在体里,体里的节点从同一份
                    #: 预算里自己拿;容器攥着不放,嵌套几层、并行几项就把预算吃光,体里的叶子永远拿不到
                    #: —— 死锁,取消也叫不醒(叶子卡在拿预算上)。和节点里的「等」同一个做法。
                    with connection_handed_back(node_db), node_scope(nid), step_frame(nid):
                        outputs = handler(node_db, wf, config)
                else:
                    with node_scope(nid):
                        outputs = handler(node_db, wf, config)
                # **节点跑完就是它的事务边界。** 只在成功时提交:失败节点半途 flush 的东西不该留下。
                # 账不在此列 —— 付过费的调用在调用方回滚之后由记账那一层补写(见 domain/billing/usage
                # 的 _settle_usage),这里不用为它破例。
                #: 「这个节点落定了」跟着同一次提交:产物和这一行要么都在、要么都不在(见 run_steps)。
                if wf_job_id is not None:
                    run_steps.record(node_db, wf_job_id, scope_key, nid, outputs)
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

    #: 已经落定的那些计入进度:从暂停接着跑时进度不该从头开始(前面那几步是跑过的)。
    processed = sum(1 for nid in order_ids if nid in done)
    scheduled: set[str] = set(done & set(order_ids))
    error: Exception | None = None
    failed_node = ""
    cancelled = False
    #: 停在哪一步等人确认(见 AwaitingApproval)。它不是失败:收场时走的是 GraphRun.paused 那条。
    paused: AwaitingApproval | None = None

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
            if paused is not None:
                # 有人在等确认:这一轮到此为止,**后面还没派出去的节点一律先不派** —— 它们属于
                # 恢复之后的那半截(见 GraphResume)。刻意不立停的信号:那不是失败,兄弟节点做完就做完。
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
        while futures and error is None and not cancelled and paused is None:
            if stopping():
                cancelled = True
                break
            completed, _ = wait(list(futures.keys()), timeout=0.5, return_when=FIRST_COMPLETED)
            for future in completed:
                nid = futures.pop(future)
                try:
                    outputs = future.result()
                except AwaitingApproval as waiting:
                    # **「等人确认」不是失败。** 这一轮停在暂停点上:不立停的信号(兄弟节点该做完的
                    # 做完、该提交的提交),不记失败事件,后面没派出去的节点留给恢复之后那一半。
                    paused = waiting
                    node_event("workflow.node.awaiting_approval", nid, approval_id=waiting.approval_id)
                    break
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
                    node_event("workflow.node.failed", nid, **failure_payload(exc))
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
            if error is None and not cancelled and paused is None:
                schedule_ready()
        if cancelled:
            halt.set()
            event("workflow.cancelled", {"pending": len(futures)})
            for pending_nid in futures.values():
                node_event("workflow.node.failed", pending_nid,
                           error=t("jobErr_cancelled", DEFAULT_LOCALE), error_key="jobErr_cancelled")
        elif paused is not None:
            # **等还在飞的兄弟节点各自落定,一件都不留给恢复之后重跑。** 它们在暂停点上已经开始了,
            # 半途丢下的话恢复时就只能从头再来一遍(那正是要避免的:这一步可能正在烧钱)。它们做完的
            # 产物一并进现场。
            wait(list(futures.keys()))
            for future, pending_nid in futures.items():
                failure = future.exception()
                if failure is not None:
                    # 兄弟节点失败:这一轮还是**失败**(不是暂停)—— 一次运行里既有失败又有等待时,
                    # 失败优先,像以前一样。暂停那半截的信息跟着丢掉,反正没人会往下跑。
                    error, failed_node = failure, pending_nid
                    node_event("workflow.node.failed", pending_nid, **failure_payload(failure))
                    continue
                outputs = future.result()
                with lock:
                    context[pending_nid] = outputs
                    executed.add(pending_nid)
                    done.add(pending_nid)
                processed += 1
                node_finished(pending_nid, outputs)
                if has_job:
                    #: 进度照写,**不在这里提交** —— 这一轮马上就收场了,提交由外层那一次事务做
                    #: (领域层不提交,见 tests/test_use_case_boundaries_ratchet.py)。
                    job.progress = processed / total
            if error is not None:
                paused = None
        elif error is not None:
            # 失败之后还在飞的兄弟节点:等它们停下,各自落一个终态事件 —— 只有 started 的话,
            # 执行历史会把它们永远画成「运行中」。
            wait(list(futures.keys()))
            for future, pending_nid in futures.items():
                failure = future.exception()
                if failure is not None:
                    node_event("workflow.node.failed", pending_nid, **failure_payload(failure))
                else:
                    node_finished(pending_nid, future.result())

    cancelled = cancelled or is_cancelled()
    if cancelled:
        return GraphRun(context, True)
    if paused is not None:
        #: **子图里不许暂停。** 体的执行内核(has_job=False)没有地方落检查点,层级也套不回去;
        #: 校验和运行前检查都会先拦下它,这里是不该走到的一道兜底。
        if not has_job:
            raise WorkflowDomainError("wfErr_awaitApprovalNested")
        return GraphRun(
            context, False,
            awaiting=paused.node_id, approval=paused.approval_id,
            executed=frozenset(executed), done=frozenset(done),
        )
    return GraphRun(context, False, error, failed_node if error is not None else "")


def _park_at_approval(db: Session, job: Job, run: GraphRun) -> None:
    """把暂停那一刻的现场写进那张待批单,并让任务卡说出「在等人确认」。

    **不收尾、不落终态**:这次运行是活的,只是在等。取消它走的是普通任务那条路
    (jobs.cancel_job → 挂在 kind 上的取消监听把待批单一起撤了),重启接回来走的是 resumer 那条
    (见 domain/workflows/approvals.register_seams)。进度按已经落定的节点算,不回头。
    """

    approval = approvals.find(db, job.id, run.awaiting)
    if approval is None:
        #: 单不在了(被取消撤掉、被清理):这一轮恢复不了,老实说一句,别让它停在 running 上没人管。
        raise WorkflowDomainError("wfErr_awaitNotResumable")
    approvals.record_checkpoint(
        db, approval,
        GraphResume(context=run.context, executed=run.executed, done=run.done).checkpoint(),
    )
    say(job, "jobMsg_awaitingApproval", title=approval.title)
    emit_job_event(db, job.id, "workflow.awaiting_approval", {
        "node_id": run.awaiting, "approval_id": approval.id, "title": approval.title,
    })
    #: **flush,不 commit。** 那两句必须现在就进这次事务:`_run_workflow_thread` 收尾时会
    #: `db.refresh(job)` 记一句日志,而 refresh **不会**先把待写的东西刷下去 —— 它直接拿库里的行
    #: 覆盖内存里的对象,于是暂停那一刻写的话(「等待确认:…」)和那条事件会被无声地擦掉,
    #: 任务卡上显示的还是「工作流运行中」。
    db.flush()
    #: 站内通知 + 飞书卡片。通知是兜底(没有飞书绑定也照样等),卡片失败一律降级。
    #:
    #: **排在提交之后**(`after_commit`,不在这里 commit —— 领域层不提交,见
    #: tests/test_use_case_boundaries_ratchet.py)。这一条不是洁癖:说出去的东西**必须已经落库** ——
    #: 先发卡、检查点还在这个事务里的话,手快的人在提交之前点了确认,那次运行会卡在一个
    #: 永远唤醒不了的等待上(见 approvals.announce 的说明)。
    approval_id = approval.id
    #: **写完现场再看一眼:这道门是不是已经被决定了。** 单是执行器自己一个事务先提交的(见
    #: executors/approval),而现场要等还在飞的兄弟节点都落定才写得进来 —— 这两步之间那段窗口里,
    #: 决定可能已经落了库(飞书那张旧卡、应用内那一格、后台那一拍超时)。那时这一次唤醒找不到现场
    #: (`approvals.dispatch_resume` 认的是检查点),运行就永远停在 running 上:决定赢了、醒不过来。
    #: 复查一次,是的话**在这里再排一次恢复** —— 同一个事务里排的,天然盖住那段窗口。
    #:
    #: `refresh` 安全:现场上面那一次 `flush` 已经把它写进这次事务了,读回来就是它。
    db.refresh(approval)
    if approval.status != approvals.PENDING:
        #: 已经决定了就**别再喊人来等**:那张卡会是一张"已经批过"的卡,通知也会让人白跑一趟。
        logger.info(
            "approval %s was decided (%s) before its resume point landed; resuming instead of announcing",
            approval_id, approval.status,
        )
        after_commit(db, lambda: approvals.dispatch_resume(job.id, approval_id=approval_id))
    else:
        #: 站内通知 + 飞书卡片。通知是兜底(没有飞书绑定也照样等),卡片失败一律降级。
        #:
        #: **排在提交之后**(`after_commit`,不在这里 commit —— 领域层不提交,见
        #: tests/test_use_case_boundaries_ratchet.py)。这一条不是洁癖:说出去的东西**必须已经落库** ——
        #: 先发卡、检查点还在这个事务里的话,手快的人在提交之前点了确认,那次运行会卡在一个
        #: 永远唤醒不了的等待上(见 approvals.announce 的说明)。
        after_commit(db, lambda: approvals.announce_parked(approval_id))
    logger.info("workflow job %s parked at node %s awaiting approval %s", job.id, run.awaiting, approval.id)


def continue_workflow_job(db: Session, job: Job, checkpoint: dict[str, Any]) -> None:
    """**把一个停在「等人确认」上的运行从暂停的那个节点接着跑。** 决定下来时(飞书 / 应用内 / 超时)
    和重启收尾都走这里。

    不改任务状态(它一直是 running)、不重新校验(那一版开跑前已经查过)、也不新建任务 ——
    派发走的是和开跑同一处(jobs.dispatch_job),线程拿的是**当时钉住的那一版修订**。
    """
    resume = GraphResume.from_checkpoint(checkpoint)
    if resume is None:
        raise WorkflowDomainError("wfErr_awaitNotResumable")
    payload = job.payload or {}
    workflow_id = str(payload.get("workflow_id") or "")
    revision_id = str(payload.get("workflow_revision_id") or "")
    params = dict(payload.get("params") or {})
    locale = payload.get("locale")
    target_node = str(payload.get("target_node_id") or "") or None
    #: **只捏普通值** —— 线程起来时调用方的会话可能正在回滚,在线程里读 `job.id` 会拿那个会话回库加载
    #: (见 jobs.dispatch_job 的说明,tests/test_jobs_are_dispatched_by_the_bus.py 守着这条)。
    job_id = job.id

    def run_resumed() -> None:
        """接回来的那一轮,外头再套一层:收尾时告诉 approvals 这次恢复不在飞了。

        任务落终态之后才真正放下「恢复中」的标记(见 approvals.resume_finished);那之前同一个
        等待不会被第二条唤醒路再派一遍,而下一道门有自己那张单的 id,不靠清标记才派得出去。
        """

        try:
            _run_workflow_thread(
                workflow_id, revision_id, job_id, params, locale=locale, target_node=target_node, resume=resume,
            )
        finally:
            approvals.resume_finished(job_id)

    dispatch_job(db, job, run_resumed)


#: 能从第几轮重做的节点。
LOOP_NODE_TYPES = ("loop_foreach", "loop_while")


def _downstream(graph: dict[str, Any], node_id: str) -> set[str]:
    """顶层这张图里排在 `node_id` 后面的节点:连线和引用都算。"""
    followers: dict[str, set[str]] = {}
    for edge in graph.get("edges") or []:
        followers.setdefault(str(edge.get("source")), set()).add(str(edge.get("target")))
    for target, sources in reference_dependencies(graph).items():
        for source in sources:
            followers.setdefault(source, set()).add(target)
    found: set[str] = set()
    frontier = [node_id]
    while frontier:
        for one in followers.get(frontier.pop(), ()):
            if one not in found:
                found.add(one)
                frontier.append(one)
    return found


def continue_run(
    db: Session, workflow: Workflow, job: Job, *, params: dict[str, Any] | None = None, redo: RedoRound | None = None,
    called: bool = False,
) -> Job:
    """**把一个运行从中断处接着跑**(ADR 0092)。

    和开跑同一个任务、同一版钉住的修订:已经落定的节点不再执行(见 run_steps),花掉的钱、执行历史都接在这一条上。
    失败的那个节点重跑一遍 —— 这正是要做的事;它当时交出去的生成任务还在的话接回来,不再下单。

    - `params`:改开始参数(调高花费上限、换尾巴长度)。**只影响还没落定的节点。**
    - `redo`:从顶层某个循环的第几轮重做,成功的运行也可以;`item` 换掉那一轮的内容。之前的几轮留着。
    - `called`:外层接着跑时重新接上它调起的子运行。别的时候子运行不单独继续。
    """
    payload = dict(job.payload or {})
    if job.kind != "workflow" or (job.parent_job_id and not called) or payload.get("workflow_id") != workflow.id:
        raise WorkflowDomainError("wfErr_runNotContinuable")
    revision_id = str(payload.get("workflow_revision_id") or "")
    revision = db.get(WorkflowRevision, revision_id) if revision_id else None
    if revision is None or revision.workflow_id != workflow.id:
        raise WorkflowDomainError("wfErr_revisionMissing")
    if redo is not None and not any(
        str(node.get("id")) == redo.node_id and node.get("type") in LOOP_NODE_TYPES for node in revision.graph.get("nodes") or []
    ):
        raise WorkflowDomainError("wfErr_redoNeedsLoop")
    if not reopen_job(db, job, finished_too=redo is not None):
        raise WorkflowDomainError("wfErr_runNotContinuable")
    if params:
        payload["params"] = {**(payload.get("params") or {}), **params}
    if redo is not None:
        run_steps.forget_from(db, job.id, redo.node_id, redo.index, _downstream(revision.graph, redo.node_id))
        if redo.item is not None:
            payload["round_items"] = {
                **(payload.get("round_items") or {}),
                redo.node_id: {**((payload.get("round_items") or {}).get(redo.node_id) or {}), str(redo.index): redo.item},
            }
    job.payload = payload
    say(job, "jobMsg_workflowContinuing", name=workflow.name)
    emit_job_event(db, job.id, "workflow.continued", {"redo": redo.node_id if redo else None})
    workflow_id, job_id, run_params = workflow.id, job.id, dict(payload.get("params") or {})
    locale = payload.get("locale")
    target_node = str(payload.get("target_node_id") or "") or None
    dispatch_job(db, job, lambda: _run_workflow_thread(
        workflow_id, revision_id, job_id, run_params, locale=locale, target_node=target_node, continuing=True,
    ))
    return job


def continue_called_run(db: Session, workflow: Workflow, job: Job) -> Job:
    """外层接着跑时,把它调起的那条失败的子运行也接着跑。"""
    return continue_run(db, workflow, job, called=True)


def run_workflow(
    db: Session,
    workflow: Workflow,
    revision: WorkflowRevision,
    job: Job,
    params: dict[str, Any],
    *,
    target_node: str | None = None,
    resume: GraphResume | None = None,
    continuing: bool = False,
) -> dict[str, Any]:
    """执行固定修订；编辑当前工作流不会改变已排队任务的图。`target_node` 给定时单跑这一个节点
    (只执行它及其上游闭包,见 run_graph)。

    `resume` 给定时是**从「等人确认」的暂停点接着跑**:前面已经落定的节点直接跳过(见 GraphResume)。
    `continuing` 时是**从失败处接着跑**(见 continue_run):每一层图读回自己落定的节点(见 run_steps)。
    """
    graph = revision.graph
    node_types = {str(node["id"]): str(node.get("type")) for node in (graph.get("nodes") or [])}
    if not finish_job(db, job, status="running"):
        db.commit()
        return {}
    if resume is None and not continuing:
        say(job, "jobMsg_workflowRunning", name=workflow.name)
        db.commit()
    if resume is not None:
        #: 「等人确认」那个节点是决定下来时落定的,没走过节点的那一步:这里补上。之后再失败、接着跑,它不会再问一遍人。
        for nid in resume.executed:
            run_steps.record(db, job.id, "", nid, resume.context.get(nid))

    with continuing_run(continuing):
        run = run_graph(graph, wf_id=workflow.id, params=params, job=job, db=db, target_node=target_node, resume=resume)
    context = run.context
    if run.cancelled:
        return context
    if run.paused:
        _park_at_approval(db, job, run)
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
            "costs": settlement.costs_for_job(db, job.id),
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
        "costs": settlement.costs_for_job(db, job.id),
    }
    emit_job_event(
        db,
        job.id,
        "workflow.finished",
        {"nodes": len(node_types), "executed": len(context), "workflow_revision": revision.revision},
    )
    db.commit()
    return context


#: **「把暂停在等人确认上的运行接着跑」这件事只有引擎会做,所以由引擎自己登记。**
#: 方向是有讲究的:领域(approvals)不许 import 引擎 —— 那就又给"引擎 ⇄ 执行器"那一族添一个
#: 新环(见 tests/test_import_layering);反过来,引擎认识工作流的领域。
#: 放在模块末尾:登记的是一个**已经定义好**的函数。
from app.domain.workflows import approvals as _approvals  # noqa: E402

_approvals.use_resume_dispatcher(continue_workflow_job)

#: 容器类执行器(循环体、子图、调用另一个工作流)回头跑图也经同一个方向的登记(见 graph_runner)。
from app.domain.workflows import graph_runner as _graph_runner  # noqa: E402

_graph_runner.use(run_graph=run_graph, start_workflow_job=start_workflow_job, continue_called_run=continue_called_run)
