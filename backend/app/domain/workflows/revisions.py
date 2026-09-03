"""工作流修订的唯一写入边界。

这个 Module 把三条不变量藏在一个小而深的 Interface 后面：修订不可变、执行语义相同不增版、
当前投影与最新修订在执行语义上一致。调用方不直接构造 ``WorkflowRevision``，也不自行递增版本号。
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.model_base import now
from app.db.models import Workflow, WorkflowRevision


#: 版本历史是给人恢复工作流用的浏览窗口，不是运行快照的生命周期。
#:
#: 可执行内容的编辑会持续追加不可变修订；不限制列表会让一个长期编辑的工作流一次返回成千上万行和
#: 对应 JSON 图。这里只限制历史面板/API 的读取窗口，底层修订仍然保留——已经排队的任务通过
#: ``workflow_revision_id`` 固定到其中一行，贸然删除会让一次合法运行在启动后找不到自己的图。
WORKFLOW_REVISION_HISTORY_LIMIT = 100


class WorkflowRevisionError(RuntimeError):
    pass


def graph_digest(graph: dict) -> str:
    """完整图摘要，用于校验当前投影和不可变快照各自没有损坏。"""

    canonical = json.dumps(graph, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _revision_projection(value):
    """只从图节点剥离画布坐标，并递归处理循环/子流程里的嵌套图。

    这里按「graph-like 对象里的 nodes」识别节点，不能粗暴删除所有名为 ``position`` 的键：
    节点配置可能真的有一个会影响执行的 position 参数，那种值必须参与版本判定。
    """

    if isinstance(value, list):
        return [_revision_projection(item) for item in value]
    if not isinstance(value, dict):
        return value
    graph_like = isinstance(value.get("nodes"), list) and isinstance(value.get("edges"), list)
    projected = {}
    for key, child in value.items():
        if graph_like and key == "nodes":
            projected[key] = [
                {
                    node_key: _revision_projection(node_value)
                    for node_key, node_value in node.items()
                    if node_key != "position"
                }
                if isinstance(node, dict)
                else _revision_projection(node)
                for node in child
            ]
        else:
            projected[key] = _revision_projection(child)
    return projected


def revision_digest(graph: dict) -> str:
    """版本身份摘要：画布布局可保存，但不应制造新的可执行版本。"""

    return graph_digest(_revision_projection(graph))


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
    """保存完整画布；只有执行语义变化时才原子追加修订。

    修订号在 UPDATE 内递增，而不是在 Python 里用 ``workflow.revision + 1``。这样两个重叠的
    自动保存会由数据库串行取得不同版本，不会同时尝试写同一个唯一键。布局保存也带当前修订
    条件，不能在并发语义编辑落库后拿旧画布覆盖新内容。
    """

    digest = graph_digest(graph)
    semantic_digest = revision_digest(graph)
    db.flush()

    # SQLite 会串行写事务；revision 条件再负责发现「读取当前快照后、真正 UPDATE 前」发生的
    # 并发提交。重读后重新分类为布局保存或语义修订即可，不需要让调用方理解冲突重试。
    for _attempt in range(8):
        db.refresh(workflow)
        current = current_workflow_revision(db, workflow)
        expected_revision = workflow.revision

        if revision_digest(current.graph) == semantic_digest:
            db.execute(
                update(Workflow)
                .where(
                    Workflow.id == workflow.id,
                    Workflow.revision == expected_revision,
                    Workflow.graph_hash != digest,
                )
                .values(graph=deepcopy(graph), graph_hash=digest, updated_at=now())
            )
            db.flush()
            db.refresh(workflow)
            if workflow.revision == expected_revision:
                return None
            continue

        revision_number = db.execute(
            update(Workflow)
            .where(
                Workflow.id == workflow.id,
                Workflow.revision == expected_revision,
                Workflow.graph_hash != digest,
            )
            .values(
                graph=deepcopy(graph),
                graph_hash=digest,
                revision=Workflow.revision + 1,
                updated_at=now(),
            )
            .returning(Workflow.revision)
        ).scalar_one_or_none()
        if revision_number is None:
            continue

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

    raise WorkflowRevisionError("工作流在保存期间被连续修改，请重试")


def list_workflow_revisions(
    db: Session,
    workflow_id: str,
    *,
    limit: int = WORKFLOW_REVISION_HISTORY_LIMIT,
) -> list[WorkflowRevision]:
    """按新到旧返回有限的可恢复历史。

    调用方可以为内部用途收紧窗口，但不能越过产品级上限，避免重新引入无界读取。
    """

    bounded = max(1, min(limit, WORKFLOW_REVISION_HISTORY_LIMIT))
    return list(
        db.scalars(
            select(WorkflowRevision)
            .where(WorkflowRevision.workflow_id == workflow_id)
            .order_by(WorkflowRevision.revision.desc())
            .limit(bounded)
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
    if graph_digest(revision.graph) != revision.graph_hash or graph_digest(workflow.graph) != workflow.graph_hash:
        raise WorkflowRevisionError(f"工作流 v{workflow.revision} 的图摘要校验失败")
    if revision_digest(revision.graph) != revision_digest(workflow.graph):
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
