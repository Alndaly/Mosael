"""节点执行器的注册表本体。各执行器模块从这里 import `register` / `RunScope`,包的 `__init__` 负责把它们全部挂上。

此前注册表写在包的 `__init__` 里,执行器模块又回头 `from app.domain.workflows.executors import register` ——
包和它的十几个子模块彼此在顶层互相 import。能跑是因为 `__init__` 恰好先定义完注册表、最后才 import 子模块;
这种依赖 import 顺序的环,正是分层测试要挡的形状(它此前看不见:`from 包 import 子模块` 被记成了对包的依赖)。
"""

from __future__ import annotations

from typing import Any, Callable, Protocol

from sqlalchemy.orm import Session


class RunScope(Protocol):
    """执行器跑在**谁名下** —— 只有这三样,不是整个工作流。

    执行器此前拿的是 Workflow 这个 ORM 对象,实际只读了三个属性:归哪个工作区(素材、用量、
    通知的归属)、一个稳定 id(防递归、通知里指回去、子图的归属)、一个名字(新建东西时的默认名)。
    把签名收窄到这三样,节点就不再只能在工作流里跑 —— 创意画板跑一个节点时给的是它自己的
    作用域,而不是伪造一个工作流。**执行者是谁不在这里**:那是 `current_actor(db)`,跟着任务走。

    Workflow 本身就满足这个协议,引擎直接传它。棘轮
    tests/test_executors_only_read_run_scope.py 钉住执行器只碰这三个属性。
    """

    @property
    def workspace_id(self) -> str: ...

    @property
    def id(self) -> str: ...

    @property
    def name(self) -> str: ...


Handler = Callable[[Session, RunScope, dict[str, Any]], dict[str, Any]]

_REGISTRY: dict[str, Handler] = {}


def register(node_type: str) -> Callable[[Handler], Handler]:
    """把执行器登记到注册表;重复登记同一类型视为编程错误,立刻报。"""

    def _decorator(handler: Handler) -> Handler:
        if node_type in _REGISTRY:
            raise RuntimeError(f"executor for node type {node_type!r} registered twice")
        _REGISTRY[node_type] = handler
        return handler

    return _decorator


#: 前缀执行器:一族**动态**节点类型共用一套行为。目前只有插件节点(`plugin.` 开头)——
#: 它们的类型 id 随用户装了什么插件而变,不可能逐个 @register。
#:
#: 注册的是**工厂**而不是执行器:工厂拿到具体的 node_type,返回一个绑好它的执行器。这样
#: Handler 的签名不用为了多传一个 node_type 而全体改一遍,也不用把类型偷偷塞进 config
#: (那等于给每个节点的入参凭空加一个保留字,而 config 的键是用户和插件说了算的)。
PrefixFactory = Callable[[str], Handler]

_PREFIX_REGISTRY: dict[str, PrefixFactory] = {}


def register_prefix(prefix: str) -> Callable[[PrefixFactory], PrefixFactory]:
    def _decorator(factory: PrefixFactory) -> PrefixFactory:
        if prefix in _PREFIX_REGISTRY:
            raise RuntimeError(f"executor for node prefix {prefix!r} registered twice")
        _PREFIX_REGISTRY[prefix] = factory
        return factory

    return _decorator


def get_executor(node_type: str) -> Handler | None:
    handler = _REGISTRY.get(node_type)
    if handler is not None:
        return handler
    for prefix, factory in _PREFIX_REGISTRY.items():
        if node_type.startswith(prefix):
            return factory(node_type)
    return None


def registered_types() -> frozenset[str]:
    return frozenset(_REGISTRY)



#: **运行前检查**:不花钱、不写东西,在建工作流任务之前问一遍。有的节点「跑到它才发现做不了」,而排在它前面的节点
#: 已经花了钱 —— 译配选了「只去掉人声」却没有分离能力,要等转写、付费翻译、逐句配音全做完才被问到。登记一个
#: preflight,引擎在任何节点跑之前对图里每个这种节点(循环体、子图里的也算)用它的**字面量**配置问一遍:
#: 引用(`{{…}}`)和数据边供的值要到运行时才知道,不在这里判,执行时照样会判。
#: 签名:preflight(db, 字面量配置, 跑的人)。说不通就抛 WorkflowDomainError。
Preflight = Callable[[Session, dict[str, Any], "str | None"], None]

_PREFLIGHTS: dict[str, Preflight] = {}


def register_preflight(node_type: str) -> Callable[[Preflight], Preflight]:
    def _decorator(check: Preflight) -> Preflight:
        if node_type in _PREFLIGHTS:
            raise RuntimeError(f"preflight for node type {node_type!r} registered twice")
        _PREFLIGHTS[node_type] = check
        return check

    return _decorator


def run_preflights(db: Session, graph: Any, actor: str | None) -> None:
    """对图里每个登记了 preflight 的节点问一遍(见 register_preflight)。"""
    if not isinstance(graph, dict):
        return
    edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
    bound = {
        (str(edge.get("target")), str(edge.get("target_input")))
        for edge in edges
        if isinstance(edge, dict) and edge.get("kind") == "data" and edge.get("target_input")
    }
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        for value in config.values():
            if isinstance(value, dict) and isinstance(value.get("nodes"), list):
                run_preflights(db, value, actor)
        check = _PREFLIGHTS.get(str(node.get("type") or ""))
        if check is None:
            continue
        node_id = str(node.get("id") or "")
        literal = {key: value for key, value in config.items()
                   if (node_id, key) not in bound and not (isinstance(value, str) and "{{" in value)}
        check(db, literal, actor)
