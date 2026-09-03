"""工作流修订的唯一写入边界。

这个 Module 把三条不变量藏在一个小而深的 Interface 后面：修订不可变、内容相同不增版、
当前投影与最新修订一致。调用方不直接构造 ``WorkflowRevision``，也不自行递增版本号。
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.model_base import now
from app.db.models import Workflow, WorkflowRevision


class WorkflowRevisionError(RuntimeError):
    pass


def graph_digest(graph: dict) -> str:
    """对语义等价的 JSON 产生稳定摘要；键顺序和空白不会制造新修订。"""

    canonical = json.dumps(graph, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_initial_revision(
    db: Session,
    workflow: Workflow,
    *,
    source: str,
    created_by: str | None = None,
    note: str = "",
) -> WorkflowRevision:
    """为刚创建且尚未提交的工作流建立 revision 1。"""

    digest = graph_digest(workflow.graph)
    workflow.revision = 1
    workflow.graph_hash = digest
    db.flush()  # revision 的外键必须先拿到 workflow.id
    revision = WorkflowRevision(
        workflow_id=workflow.id,
        revision=1,
        graph=deepcopy(workflow.graph),
        graph_hash=digest,
        source=source,
        note=note,
        created_by=created_by,
    )
    db.add(revision)
    return revision


def commit_graph_revision(
    db: Session,
    workflow: Workflow,
    graph: dict,
    *,
    source: str,
    created_by: str | None = None,
    note: str = "",
) -> WorkflowRevision | None:
    """原子更新当前投影并追加修订；内容未变化时返回 ``None``。

    修订号在 UPDATE 内递增，而不是在 Python 里用 ``workflow.revision + 1``。这样两个重叠的
    自动保存会由数据库串行取得不同版本，不会同时尝试写同一个唯一键。
    """

    digest = graph_digest(graph)
    db.flush()
    revision_number = db.execute(
        update(Workflow)
        .where(Workflow.id == workflow.id, Workflow.graph_hash != digest)
        .values(
            graph=deepcopy(graph),
            graph_hash=digest,
            revision=Workflow.revision + 1,
            updated_at=now(),
        )
        .returning(Workflow.revision)
    ).scalar_one_or_none()
    if revision_number is None:
        db.refresh(workflow)
        return None

    revision = WorkflowRevision(
        workflow_id=workflow.id,
        revision=revision_number,
        graph=deepcopy(graph),
        graph_hash=digest,
        source=source,
        note=note,
        created_by=created_by,
    )
    db.add(revision)
    db.flush()
    db.refresh(workflow)
    return revision


def list_workflow_revisions(db: Session, workflow_id: str) -> list[WorkflowRevision]:
    return list(
        db.scalars(
            select(WorkflowRevision)
            .where(WorkflowRevision.workflow_id == workflow_id)
            .order_by(WorkflowRevision.revision.desc())
        )
    )


def get_workflow_revision(db: Session, workflow_id: str, revision: int) -> WorkflowRevision | None:
    return db.scalar(
        select(WorkflowRevision).where(
            WorkflowRevision.workflow_id == workflow_id,
            WorkflowRevision.revision == revision,
        )
    )


def current_workflow_revision(db: Session, workflow: Workflow) -> WorkflowRevision:
    revision = get_workflow_revision(db, workflow.id, workflow.revision)
    if revision is None:
        raise WorkflowRevisionError(f"工作流 v{workflow.revision} 的修订快照不存在")
    if (
        revision.graph_hash != workflow.graph_hash
        or graph_digest(revision.graph) != workflow.graph_hash
        or graph_digest(workflow.graph) != workflow.graph_hash
    ):
        raise WorkflowRevisionError(f"工作流 v{workflow.revision} 的当前投影与修订快照不一致")
    return revision


def restore_workflow_revision(
    db: Session,
    workflow: Workflow,
    target_revision: int,
    *,
    created_by: str | None = None,
) -> WorkflowRevision | None:
    target = get_workflow_revision(db, workflow.id, target_revision)
    if target is None:
        raise WorkflowRevisionError(f"工作流修订 v{target_revision} 不存在")
    restored = commit_graph_revision(
        db,
        workflow,
        target.graph,
        source="restore",
        created_by=created_by,
        note=f"v{target_revision}",
    )
    db.commit()
    db.refresh(workflow)
    return restored
