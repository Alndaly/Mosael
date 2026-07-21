"""节点执行器注册表。

NODE_TYPES(workflows/__init__.py)是节点的**元数据**接缝——驱动校验、画布 UI 和
智能体提示;这里是节点的**行为**接缝:每种节点类型注册一个执行器适配器,统一签名

    handler(db: Session, workflow: Workflow, config: dict) -> dict

引擎(engine.py)只认这个注册表,对具体领域零 import——新增节点 = 新增一个执行器
模块并 @register,引擎与调度语义不动。tests/test_workflows.py 的覆盖测试强制
NODE_TYPES 与本注册表一一对应,防止两个接缝漂移。
"""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.orm import Session

from app.db.models import Workflow

Handler = Callable[[Session, Workflow, dict[str, Any]], dict[str, Any]]

_REGISTRY: dict[str, Handler] = {}


def register(node_type: str) -> Callable[[Handler], Handler]:
    """把执行器登记到注册表;重复登记同一类型视为编程错误,立刻报。"""

    def _decorator(handler: Handler) -> Handler:
        if node_type in _REGISTRY:
            raise RuntimeError(f"节点类型 {node_type} 的执行器重复注册")
        _REGISTRY[node_type] = handler
        return handler

    return _decorator


def get_executor(node_type: str) -> Handler | None:
    return _REGISTRY.get(node_type)


def registered_types() -> frozenset[str]:
    return frozenset(_REGISTRY)


# 导入即注册:注册表函数定义完成后再挂载各执行器模块(顺序无关,但保持稳定)。
from app.domain.workflows.executors import ai, basic, content, loops, subjobs  # noqa: E402,F401
