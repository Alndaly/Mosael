"""工作流触发器这一族的拥有方:**什么消息叫起哪条工作流**(ADR 0065)。

三个面:

- `matching`:纯的 —— 筛选、`{{trigger.*}}` 白名单、入参渲染。不查库。
- `dispatch`:入站那一步 —— 认领、去重、限流、起运行、落事件。用 `start_workflow_job`
  这个既有用例起运行,不自己拼一套。
- `use_cases`:配置的增删改查与过闸。

飞书那一侧(收消息、下附件、发回执)在 `integrations/feishu/inbound.py` —— 那一层调这里,
这里不认识它。
"""

from app.domain.triggers.dispatch import MAX_CLAIMS_PER_MESSAGE, MAX_RUNS_PER_MINUTE, Outcome, claimable, fire
from app.domain.triggers.matching import TRIGGER_FIELDS, TRIGGER_MESSAGE_TYPES, IncomingMessage
from app.domain.triggers.use_cases import (
    EVENT_LIST_LIMIT,
    TriggerDomainError,
    create,
    delete,
    list_events,
    list_triggers,
    readable,
    stop_triggers_bound_to_workflow,
    update,
)

__all__ = [
    "EVENT_LIST_LIMIT",
    "MAX_CLAIMS_PER_MESSAGE",
    "MAX_RUNS_PER_MINUTE",
    "TRIGGER_FIELDS",
    "TRIGGER_MESSAGE_TYPES",
    "IncomingMessage",
    "Outcome",
    "TriggerDomainError",
    "claimable",
    "create",
    "delete",
    "fire",
    "list_events",
    "list_triggers",
    "readable",
    "stop_triggers_bound_to_workflow",
    "update",
]
