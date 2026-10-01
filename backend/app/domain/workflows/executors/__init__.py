"""节点执行器注册表。

NODE_TYPES(workflows/__init__.py)是节点的**元数据**接缝——驱动校验、画布 UI 和
智能体提示;这里是节点的**行为**接缝:每种节点类型注册一个执行器适配器,统一签名

    handler(db: Session, scope: RunScope, config: dict) -> dict

引擎(engine.py)只认这个注册表,对具体领域零 import——新增节点 = 新增一个执行器
模块并 @register,引擎与调度语义不动。tests/test_workflows.py 的覆盖测试强制
NODE_TYPES 与本注册表一一对应,防止两个接缝漂移。
"""

from __future__ import annotations

from app.domain.workflows.executors.registry import (  # noqa: F401 —— 包的公开面不变
    Handler,
    PreflightNode,
    PrefixFactory,
    RunScope,
    _PREFIX_REGISTRY,
    _REGISTRY,
    get_executor,
    register,
    register_prefix,
    registered_types,
    register_preflight,
    register_prefix_preflight,
    run_preflights,
)

# 导入即注册:各模块只认 registry,不回头 import 这个包 —— 包和它的子模块之间就没有环了。
from app.domain.workflows.executors import ai, basic, browser, content, dub_lipsync, entities, knowledge, loops, scenes, social, subjobs, subworkflow, talking  # noqa: F401
