"""工作流修订的唯一写入边界。

这个 Module 把三条不变量藏在一个小而深的 Interface 后面：修订不可变、执行语义相同不增版、
当前投影与最新修订在执行语义上一致。调用方不直接构造 ``WorkflowRevision``，也不自行递增版本号。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from copy import deepcopy

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.db.model_base import now
from app.db.models import Workflow, WorkflowRevision


#: 版本历史是给人恢复工作流用的浏览窗口，不是运行快照的生命周期。
#:
#: 可执行内容的编辑会持续追加不可变修订；不限制列表会让一个长期编辑的工作流一次返回成千上万行和
#: 对应 JSON 图。这里只限制历史面板/API 的读取窗口，底层修订仍然保留——已经排队的任务通过
#: ``workflow_revision_id`` 固定到其中一行，贸然删除会让一次合法运行在启动后找不到自己的图。
WORKFLOW_REVISION_HISTORY_LIMIT = 100


class WorkflowRevisionError(LocalizedError, RuntimeError):
    """修订快照对不上或者不存在。带文案 key(`wfErr_revision*`),按请求方的语言翻。"""


def graph_digest(graph: dict) -> str:
    """完整图摘要，用于校验当前投影和不可变快照各自没有损坏。"""

    canonical = json.dumps(graph, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _revision_projection(value):
    """只从图里剥离纯布局(节点坐标、标记)，并递归处理循环/子流程里的嵌套图。

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
        # 标记(位置书签,见 domain/markers)和节点坐标一样是纯布局:不执行、不连线、不产出。
        # 算进版本身份的话,拖一下书签就增一版,真正改了执行内容的那几版被挤出历史窗口。
        if graph_like and key == "markers":
            continue
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
    db.flush()
    from app.domain.collaboration import record_activity

    record_activity(
        db,
        workspace_id=workflow.workspace_id,
        actor_id=created_by,
        action="workflow.revision_created",
        subject_type="workflow",
        subject_id=workflow.id,
        summary="创建了工作流版本",
        payload={"revision": 1, "source": source},
        source_type="workflow_revision",
        source_id=revision.id,
    )
    return revision


#: 一次整图写入:拿**库里当前那份图**,给出要存的那份。
#:
#: 写入分两种,冲突时的处理也就两种(和画板 update_board / _merge_into_latest 同一条):
#: - 客户端存回来的**整份快照**(自动保存、智能体整图替换):它不知道别人刚改了什么,底子对不上
#:   就该挡回去让它重载 —— 见 `replace_graph`;
#: - **只改自己那一处**的合并(按算子改图、恢复到某一版):从最新那份出发重做一遍就不会盖掉任何人,
#:   撞了就重读再合。
GraphChange = Callable[[dict], dict]


class WorkflowGraphConflict(WorkflowRevisionError):
    """拿着旧底子存整图:库里那份在这期间被别处改过。"""

    def __init__(self, base_graph_hash: str, current_graph_hash: str):
        self.base_graph_hash = base_graph_hash
        self.current_graph_hash = current_graph_hash
        super().__init__("wfErr_graphConflict")


def replace_graph(graph: dict, *, base_graph_hash: str) -> GraphChange:
    """整份快照:只在库里仍是它读到的那份(`base_graph_hash`)时才落库。

    底子用整图摘要而不是 revision:revision 只在执行语义变了才增,纯布局(挪节点、改标记)
    不成版 —— 拿它当底子,别人刚挪好的位置照样会被旧快照盖回去。存的恰好就是库里那份时
    不算冲突:两边写的是同一个东西,谁也没丢。
    """

    wanted = graph_digest(graph)

    def change(current: dict) -> dict:
        current_hash = graph_digest(current)
        if current_hash not in (base_graph_hash, wanted):
            raise WorkflowGraphConflict(base_graph_hash, current_hash)
        return graph

    return change


def commit_graph_revision(
    db: Session,
    workflow: Workflow,
    change: GraphChange,
    *,
    source: str,
    created_by: str | None = None,
    note: str = "",
) -> WorkflowRevision | None:
    """把 `change` 落到**库里最新那份图**上;只有执行语义变化时才原子追加修订。

    每一轮都重读当前图、重新调用 `change`,UPDATE 以「读到的那份」(graph_hash + revision)为条件。
    条件没中说明读写空档里有人写入:整份快照在下一轮的 `change` 里撞 `WorkflowGraphConflict`,
    合并型写入在新图上重做 —— 不存在「重试时拿旧图盖掉新内容」这条路。修订号在 UPDATE 内递增,
    两个重叠的写入由数据库串行取得不同版本,不会同时写同一个唯一键。
    """

    db.flush()
    for _attempt in range(8):
        db.refresh(workflow)
        current = current_workflow_revision(db, workflow)
        expected_hash = workflow.graph_hash
        expected_revision = workflow.revision
        graph = change(deepcopy(workflow.graph))
        digest = graph_digest(graph)
        if digest == expected_hash:
            return None
        unchanged_since_read = update(Workflow).where(
            Workflow.id == workflow.id,
            Workflow.revision == expected_revision,
            Workflow.graph_hash == expected_hash,
        )

        if revision_digest(current.graph) == revision_digest(graph):
            written = db.execute(
                unchanged_since_read.values(graph=deepcopy(graph), graph_hash=digest, updated_at=now())
                .execution_options(synchronize_session=False)
            ).rowcount
            db.flush()
            db.refresh(workflow)
            if int(written or 0) == 1:
                return None
            continue

        revision_number = db.execute(
            unchanged_since_read.values(
                graph=deepcopy(graph),
                graph_hash=digest,
                revision=Workflow.revision + 1,
                updated_at=now(),
            )
            .returning(Workflow.revision)
            .execution_options(synchronize_session=False)
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
        from app.domain.collaboration import record_activity

        record_activity(
            db,
            workspace_id=workflow.workspace_id,
            actor_id=created_by,
            action="workflow.revision_created",
            subject_type="workflow",
            subject_id=workflow.id,
            summary="恢复了工作流版本" if source == "restore" else "保存了工作流版本",
            payload={"revision": revision_number, "source": source},
            source_type="workflow_revision",
            source_id=revision.id,
        )
        db.refresh(workflow)
        return revision

    raise WorkflowRevisionError("wfErr_revisionConcurrent")


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
        raise WorkflowRevisionError("wfErr_revisionSnapshotMissing", revision=workflow.revision)
    if graph_digest(revision.graph) != revision.graph_hash or graph_digest(workflow.graph) != workflow.graph_hash:
        raise WorkflowRevisionError("wfErr_revisionDigestMismatch", revision=workflow.revision)
    if revision_digest(revision.graph) != revision_digest(workflow.graph):
        raise WorkflowRevisionError("wfErr_revisionProjectionMismatch", revision=workflow.revision)
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
        raise WorkflowRevisionError("wfErr_revisionNotFound", revision=target_revision)
    #: 恢复是「回到那一版」这个明确的意图,不是拿着旧底子的快照:落到最新那份上就是替换它。
    snapshot = deepcopy(target.graph)
    restored = commit_graph_revision(
        db,
        workflow,
        lambda _current: snapshot,
        source="restore",
        created_by=created_by,
        note=f"v{target_revision}",
    )
    db.commit()
    db.refresh(workflow)
    return restored
