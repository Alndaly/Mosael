"""工作流开跑前的只读检查:图能不能跑、要谁担保花费。

从 `engine.py` 拆出来:引擎只该是拓扑/并行/条件/取消的调度器,而这里要问生成目录、插件连接、
模板前置条件和子工作流,是**编排层**的读用例。scheduler、triggers、智能体确认卡都直接用它;
`engine.start_workflow_job` 也在建任务前调它。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.i18n import fragment, tr
from app.db.models import Workflow
from app.domain.authority import Authority, Voucher
from app.domain.generation.operations import GenerationDomainError, check_text_inputs
from app.domain.plugins import nodes as plugins_nodes
from app.domain.plugins.nodes import why_unusable
from app.domain.workflows.authority import revision_voucher
from app.domain.workflows.errors import WorkflowDomainError
from app.domain.workflows.executors.registry import run_preflights
from app.domain.workflows.graph_rules import (
    NESTED_BODY_TYPES,
    closure_subgraph,
    spending_nodes_in_graph,
    target_dependency_closure,
    validate_graph,
    with_run_params,
)
from app.domain.workflows.node_types import node_title
from app.db.models import WorkflowRevision
from app.domain.workflows.revisions import WorkflowRevisionError, current_workflow_revision
from app.domain.workflows.templates.catalog import requirement_problem

#: 子工作流最多往下查几层 —— 和执行时 call_workflow 的嵌套上限同一个数(见 executors.subworkflow)。
_MAX_CALL_DEPTH = 8

def unvouched_spend(
    db: Session, workflow: Workflow, actor: str | None, *, above: Authority | None = None
) -> Voucher | None:
    """这一次运行要不要花跑的人(`actor`)的连接,而被执行的某一版他没担保:要的话交回第一版等他认可的,不要就 None。

    连接只归一个人、只有主人用得了(providers.credentials.resolve_connection),所以花的就是跑的人的钱。哪几版要他担保,
    和执行时那道闸(domain/authority.ensure_vouched_to_spend)在用到连接的那一刻看到的一样:那一刻所在的这一版,加上
    调用它的每一层(`above`:这次运行挂在哪条运行底下)。于是一版要担保,当且仅当它自己、或它字面量调用的子流程
    (顺下去)里有会花钱的节点(节点声明 `"spends"`,见 graph_rules.SPENDING_NODE_TYPES)—— 只调了一张不花钱的子流程,
    那张子流程是谁改的不在这里问。子流程名字写成引用、由数据边供的,运行前不知道是哪一张,到它开跑时同一条再判一次。

    定时任务卡上的「待你确认」问的也是这里(scheduler.approvals)。
    """
    if not actor:
        return None
    try:
        revision = current_workflow_revision(db, workflow)
    except WorkflowRevisionError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    needed = _spend_vouchers(db, revision, workflow.workspace_id, seen=frozenset({workflow.id}))
    if not needed:
        return None
    for voucher in (*(above.vouchers if above is not None else ()), *needed):
        if actor not in voucher.users:
            return voucher
    return None


def _spend_vouchers(db: Session, revision: WorkflowRevision, workspace_id: str, *, seen: frozenset[str]) -> list[Voucher]:
    """这一版(连同它字面量调用的子流程)要花跑的人的钱时,哪几版得有他担保;不花就是空。"""
    needed: list[Voucher] = []
    if len(seen) <= _MAX_CALL_DEPTH:
        for child in _literal_callees(db, revision.graph, workspace_id):
            if child.id in seen:
                continue
            try:
                child_revision = current_workflow_revision(db, child)
            except WorkflowRevisionError:
                continue  # 子流程那一版说不清 —— check_runnable 已经替它报过
            needed += _spend_vouchers(db, child_revision, workspace_id, seen=seen | {child.id})
    if needed or spending_nodes_in_graph(revision.graph):
        return [revision_voucher(db, revision), *needed]
    return []


def _literal_callees(db: Session, graph: dict[str, Any], workspace_id: str) -> list[Workflow]:
    """图里 `call_workflow` 节点**字面量**点名的子工作流(循环体、子图里的也算)。名字是引用、由数据边供的,
    运行前不知道是哪一张,不在这里;不在这个工作区的、删了的也不在 —— 那是 check_runnable 报的事。"""
    found: list[Workflow] = []
    for layer, node, _title in _nodes(graph):
        if node.get("type") != "call_workflow":
            continue
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        target_id = config.get("workflow_id")
        if not isinstance(target_id, str) or not target_id.strip() or _templated(target_id):
            continue
        if (str(node.get("id") or ""), "workflow_id") in _bound(layer):
            continue
        child = db.get(Workflow, target_id.strip())
        if child is not None and child.workspace_id == workspace_id and child not in found:
            found.append(child)
    return found


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


def node_in_nested_body(graph: dict[str, Any], node_id: str) -> bool:
    """这个节点 id 是不是出现在循环体/子图体里(任意深度)。单跑一个节点第一版只支持最外层:
    目标在体里要给一句清晰的「在循环体/子图里」,而不是笼统的「找不到」。"""
    for layer, node, _title in _nodes(graph):
        if layer is not graph and str(node.get("id") or "") == node_id:
            return True
    return False


def _check_target_runnable(
    db: Session,
    workflow: Workflow,
    graph: dict[str, Any],
    target_node: str,
    params: dict[str, Any] | None,
    actor: str | None,
) -> dict[str, Any]:
    """单跑一个节点的预检:只查目标及其上游闭包内的节点(同 engine.run_graph 的闭包口径)。

    目标必须在这一层(根作用域):在循环体/子图体里第一版不支持,说清楚而不是跑空。闭包外的节点
    缺配置、缺连接、有未接进流程的引用,都不拦住这一次 —— 它们根本不在本次运行里。返回闭包诱导
    子图(调用方据此判断这次运行花不花跑的人的钱,见 start_workflow_job)。
    """
    root_ids = {str(node.get("id")) for node in graph.get("nodes") or [] if isinstance(node, dict)}
    if target_node not in root_ids:
        if node_in_nested_body(graph, target_node):
            raise WorkflowDomainError("wfErr_targetNotInScope", params={"node": target_node})
        raise WorkflowDomainError("wfErr_targetMissing", params={"node": target_node})
    sub = closure_subgraph(graph, target_dependency_closure(graph, target_node))
    #: 闭包不一定含 start:允许存在、不强制(require_start=False 是循环体语义,会反过来禁 start)。
    _check_graph_runnable(
        db, sub, workflow.workspace_id, params, actor,
        seen=frozenset({workflow.id}), require_start=False, allow_start=True,
    )
    return sub


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
    require_start: bool = True,
    allow_start: bool = False,
) -> None:

    extra_types = plugins_nodes.plugin_node_types(db, actor)
    errors = validate_graph(
        with_run_params(graph, params),
        require_start=require_start,
        allow_start=allow_start,
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
