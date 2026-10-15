"""执行器共用的「拿输入 id,并确认它属于这次运行所在的工作区」。

住在一个单独的小模块里而不是 subjobs:不少执行器要用这两个帮手,而 subjobs 在
engine ⇄ executors 的既有循环里(test_import_layering 的 LAZY_CYCLE_MODULES)——
新执行器 import 它就一起进了环。这里只认 registry 的 RunScope,是片叶子。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Asset, Sequence
from app.domain.workflows.errors import WorkflowDomainError
from app.domain.workflows.executors.registry import RunScope


def _asset_in(db: Session, scope: RunScope, asset_id: str) -> Asset:
    """取这份素材,并确认它属于这次运行所在的工作区。和 _sequence_in 成对。

    asset_id 同样常常来自上游节点。少了这一条,A 工作区的工作流能转写 B 工作区的素材
    ——而转写结果是**要返回到工作流输出里**的,那是把别人的内容读出来。
    """
    if not asset_id:
        raise WorkflowDomainError("wfErr_assetIdMissing")
    asset = db.get(Asset, asset_id)
    if asset is None or asset.workspace_id != scope.workspace_id:
        raise WorkflowDomainError("wfErr_assetNotInWorkspace")
    return asset


def _sequence_in(db: Session, scope: RunScope, sequence_id: str) -> Sequence:
    """取这条序列,并确认它属于这次运行所在的工作区。

    sequence_id 常常来自上游节点,而上游可能拿到任何地方的 id —— 这一条挡的是
    「用 A 工作区的工作流去改 B 工作区的时间线」。
    """
    if not sequence_id:
        raise WorkflowDomainError("wfErr_sequenceIdMissing")
    sequence = db.get(Sequence, sequence_id)
    if sequence is None or sequence.workspace_id != scope.workspace_id:
        raise WorkflowDomainError("wfErr_sequenceNotInWorkspace")
    return sequence
