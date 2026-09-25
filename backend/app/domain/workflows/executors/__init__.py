"""节点执行器注册表。

NODE_TYPES(workflows/__init__.py)是节点的**元数据**接缝——驱动校验、画布 UI 和
智能体提示;这里是节点的**行为**接缝:每种节点类型注册一个执行器适配器,统一签名

    handler(db: Session, scope: RunScope, config: dict) -> dict

引擎(engine.py)只认这个注册表,对具体领域零 import——新增节点 = 新增一个执行器
模块并 @register,引擎与调度语义不动。tests/test_workflows.py 的覆盖测试强制
NODE_TYPES 与本注册表一一对应,防止两个接缝漂移。
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


# 导入即注册:注册表函数定义完成后再挂载各执行器模块(顺序无关,但保持稳定)。
from app.domain.workflows.executors import ai, basic, browser, content, knowledge, loops, scenes, subjobs, subworkflow  # noqa: E402,F401
