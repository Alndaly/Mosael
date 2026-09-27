"""资产详情页上的「补全多角度」「生成表情」(ADR 0027 阶段 4)。

**不自己实现。** 跑的是工作流那两个节点的执行器(workflows/executors/entities 的 `entity_angles` /
`entity_expressions`)—— 和画板上资产格的能力是同一个,画哪几张、用哪个模型、挂成什么角度只在那里决定。
这里只多做两件详情页自己的事:

· **点「开始」时先把话说清楚**:资产有没有图、模型收不收参考图、角度是不是都齐了(`plan_drawing`,不花钱),
  说不通的当场回 422,不起一个注定失败的任务;
· **起一个任务**(`entity_draw`)跑那个执行器,作用域是这个资产自己(`entity:<id>`)—— 不伪造一个工作流或画板。
  每一张生成是它的子任务,取消它就一并停;做完资产库和素材库的缓存照任务目录作废(job_catalog)。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Entity, Job
from app.domain.jobs import create_job, dispatch_job

logger = logging.getLogger(__name__)

#: 详情页上的两个按钮 → 跑哪个节点。
DRAW_NODES: dict[str, str] = {"angles": "entity_angles", "expressions": "entity_expressions", "speak": "entity_speak"}
#: 任务上的那两句话(排队中、正在画),按按钮分。
_QUEUED = {"angles": "jobMsg_entityAnglesQueued", "expressions": "jobMsg_entityExpressionsQueued",
           "speak": "jobMsg_entitySpeakQueued"}
_RUNNING = {"angles": "jobMsg_entityAnglesRunning", "expressions": "jobMsg_entityExpressionsRunning",
            "speak": "jobMsg_entitySpeakRunning"}
_DONE = {"angles": "jobMsg_entityDrawDone", "expressions": "jobMsg_entityDrawDone", "speak": "jobMsg_entitySpeakDone"}


@dataclass(frozen=True)
class EntityScope:
    """节点跑在谁名下(workflows.executors.RunScope 那三样):这个资产所在的工作区,`id` 带前缀免得和工作流撞。"""

    workspace_id: str
    id: str
    name: str


def start_drawing(db: Session, entity: Entity, ability: str, config: dict[str, Any], *, actor_id: str) -> Job:
    """检查说得通就起任务,返回任务;说不通抛 WorkflowDomainError(调用方翻成 422)。"""
    from app.domain.workflows.executors.entities import plan_drawing
    from app.domain.workflows.executors.talking import check_entity_speak

    node_type = DRAW_NODES[ability]
    settings = {**config, "entity_id": entity.id}
    #: 起任务之前的检查和节点跑的时候是同一份(不花钱):补画查图和模型,说话还要查授权声明和音色。
    if ability == "speak":
        check_entity_speak(db, entity.workspace_id, settings, actor_id)
    else:
        plan_drawing(db, entity.workspace_id, node_type, settings, actor_id)
    job = create_job(
        db,
        workspace_id=entity.workspace_id,
        kind="entity_draw",
        created_by=actor_id,
        payload={"entity_id": entity.id, "ability": ability, "subject": entity.name},
        message=_QUEUED[ability],
        message_params={"name": entity.name},
    )
    db.commit()
    scope = EntityScope(workspace_id=entity.workspace_id, id=f"entity:{entity.id}", name=entity.name)
    job_id = job.id
    dispatch_job(db, job, lambda: _run(job_id, node_type, scope, settings, ability))
    return job


def _run(job_id: str, node_type: str, scope: EntityScope, config: dict[str, Any], ability: str) -> None:
    """任务线程里跑节点。和画板跑一项能力同一个形状(boards.tools._run_in_job):先拿连接预算再开会话 ——
    节点里等生成时会把预算交还再拿回来。"""
    from app.core.db import SessionLocal
    from app.domain.jobs import run_job_inline
    from app.domain.workflows.engine import NODE_CONNECTIONS
    from app.domain.workflows.executors import get_executor

    def body() -> dict[str, Any]:
        handler = get_executor(node_type)
        assert handler is not None, node_type
        with NODE_CONNECTIONS, SessionLocal() as node_db:
            output = handler(node_db, scope, dict(config))
            node_db.commit()
        return output

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        try:
            run_job_inline(db, job, body, running=_RUNNING[ability],
                           done=_DONE[ability], params={"name": scope.name})
        except Exception:  # noqa: BLE001 — 失败已经由 run_job_inline 落到任务上
            logger.info("entity_draw %s (%s) failed", job_id, node_type, exc_info=True)


__all__ = ["DRAW_NODES", "start_drawing"]
