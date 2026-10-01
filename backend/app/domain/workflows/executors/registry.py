"""节点执行器的注册表本体。各执行器模块从这里 import `register` / `RunScope`,包的 `__init__` 负责把它们全部挂上。

此前注册表写在包的 `__init__` 里,执行器模块又回头 `from app.domain.workflows.executors import register` ——
包和它的十几个子模块彼此在顶层互相 import。能跑是因为 `__init__` 恰好先定义完注册表、最后才 import 子模块;
这种依赖 import 顺序的环,正是分层测试要挡的形状(它此前看不见:`from 包 import 子模块` 被记成了对包的依赖)。
"""

from __future__ import annotations

from dataclasses import dataclass
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
#: 签名:preflight(db, 字面量配置, 跑的人, 节点所在处)。说不通就抛 WorkflowDomainError。
@dataclass(frozen=True)
class PreflightNode:
    """运行前检查看得到的、字面量配置之外的东西:这个节点在哪个工作区、哪一层图里。

    有的检查只看自己那几格不够:改口型交给模型的配音是**上游**配音节点配的,那把嗓子有没有授权声明要顺着图往上找;
    授权确认那一格是引用时(运行时才知道),和「压根没填」在字面量配置里看起来一样,得回到原始配置分清。
    """

    workspace_id: str
    #: 节点所在的那一层图(子图、循环体里的节点就是那一层)。
    graph: dict[str, Any]
    node: dict[str, Any]

    def deferred(self, key: str) -> bool:
        """这一格的值运行时才知道:接了数据边,或者写的是引用。"""
        node_id = str(self.node.get("id") or "")
        edges = self.graph.get("edges") if isinstance(self.graph.get("edges"), list) else []
        if any(isinstance(edge, dict) and edge.get("kind") == "data" and str(edge.get("target")) == node_id
               and str(edge.get("target_input")) == key for edge in edges):
            return True
        value = (self.node.get("config") or {}).get(key)
        return isinstance(value, str) and "{{" in value

    def upstream(self, node_type: str) -> list[dict[str, Any]]:
        """同一层图里沿着边往上游能走到的、这种类型的节点(不分控制边和数据边)。"""
        nodes = {str(one.get("id")): one for one in self.graph.get("nodes") or [] if isinstance(one, dict)}
        edges = [edge for edge in self.graph.get("edges") or [] if isinstance(edge, dict)]
        seen: set[str] = set()
        frontier = [str(self.node.get("id") or "")]
        while frontier:
            target = frontier.pop()
            for edge in edges:
                source = str(edge.get("source"))
                if str(edge.get("target")) == target and source not in seen:
                    seen.add(source)
                    frontier.append(source)
        return [nodes[one] for one in sorted(seen) if one in nodes and nodes[one].get("type") == node_type]


Preflight = Callable[[Session, dict[str, Any], "str | None", PreflightNode], None]

_PREFLIGHTS: dict[str, Preflight] = {}


def register_preflight(node_type: str) -> Callable[[Preflight], Preflight]:
    def _decorator(check: Preflight) -> Preflight:
        if node_type in _PREFLIGHTS:
            raise RuntimeError(f"preflight for node type {node_type!r} registered twice")
        _PREFLIGHTS[node_type] = check
        return check

    return _decorator


#: 前缀 preflight:一族动态节点类型(插件节点)共用的运行前检查,和前缀执行器同一个道理 —— 登记的是**工厂**,
#: 拿到具体的 node_type 返回一个绑好它的 preflight。
PrefixPreflight = Callable[[str], Preflight]

_PREFIX_PREFLIGHTS: dict[str, PrefixPreflight] = {}


def register_prefix_preflight(prefix: str) -> Callable[[PrefixPreflight], PrefixPreflight]:
    def _decorator(factory: PrefixPreflight) -> PrefixPreflight:
        if prefix in _PREFIX_PREFLIGHTS:
            raise RuntimeError(f"preflight for node prefix {prefix!r} registered twice")
        _PREFIX_PREFLIGHTS[prefix] = factory
        return factory

    return _decorator


def _preflight_for(node_type: str) -> Preflight | None:
    check = _PREFLIGHTS.get(node_type)
    if check is not None:
        return check
    for prefix, factory in _PREFIX_PREFLIGHTS.items():
        if node_type.startswith(prefix):
            return factory(node_type)
    return None


def literal_config(node: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    """节点配置里**字面量**的那几格:去掉引用和接了数据边的。"""
    place = PreflightNode(workspace_id="", graph=graph, node=node)
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    return {key: value for key, value in config.items() if not place.deferred(key)}


def run_preflights(db: Session, graph: Any, actor: str | None, *, workspace_id: str) -> None:
    """对图里每个登记了 preflight 的节点问一遍(按类型登记的,和按前缀登记的一族动态类型,见 register_preflight /
    register_prefix_preflight)。`workspace_id`:这张图在哪个工作区跑。"""
    if not isinstance(graph, dict):
        return
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        for value in config.values():
            if isinstance(value, dict) and isinstance(value.get("nodes"), list):
                run_preflights(db, value, actor, workspace_id=workspace_id)
        check = _preflight_for(str(node.get("type") or ""))
        if check is None:
            continue
        check(db, literal_config(node, graph), actor, PreflightNode(workspace_id=workspace_id, graph=graph, node=node))
