"""清除元数据的节点(ADR 0062):素材进,干净素材 + 对账文本出。

领域逻辑全在 `domain/media/scrub`:`scrub_asset` 同步做完(重封装 → 原地改码流 → 门禁 → 登记),
这里只做适配 —— 把节点的连接解析成素材、把 `provenance` 开关解析成布尔、把结果交成节点输出。

**为什么可以同步做、不必开子任务**:重封装是 `ffmpeg -c copy`(几分钟的片子秒级),真正花时间的是
按样本改写和收尾的门禁(要整份读一遍比对),几分钟的片子在秒级到十几秒。工作流节点本来就在跑,
再套一层子任务只会多一份等待。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.domain.jobs import current_actor
from app.domain.assets.scrub.task import removed_counts, scrub_asset
from app.domain.assets.scrub.engine import ScrubError
from app.domain.workflows.errors import WorkflowDomainError
from app.domain.workflows.executors.inputs import _asset_in
from app.domain.workflows.executors.registry import RunScope, register


@register("scrub_metadata")
def scrub_metadata(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """去掉容器标签、GPS、设备/软件、账号、封面、数据轨,以及 `ffprobe` 看不见的三层。

    `provenance`(默认 `no`)是**单独一个开关**:打开连 AI 生成标记(C2PA)一起清,后果见下。
    产出登记成一份派生素材,原素材一个字节不动。
    """
    #: 收进本工作区:`_asset_in` 是这条路上唯一的入口 —— 少了它,A 工作区的工作流能拿 B 工作区的
    #: 素材 id 清出一份新素材(棘轮 tests/test_workflow_nodes_stay_in_their_workspace 盯着)。
    asset = _asset_in(db, scope, str(config.get("asset_id", "")).strip())
    if asset.kind != "video":
        raise WorkflowDomainError("wfErr_scrubNotVideo", params={"name": asset.name})
    provenance = str(config.get("provenance") or "no").strip().lower() == "yes"
    try:
        result = scrub_asset(db, asset, provenance=provenance, created_by=current_actor(db))
    except ScrubError as exc:
        raise WorkflowDomainError(exc.key, params=exc.params) from exc
    outcome = result.outcome
    #: **只返回声明的输出**(棘轮 tests/test_node_outputs_match_the_executor 盯着):
    #: provenance 的后果已经写在节点文案、确认卡和对账文本第一屏里,不再单开一个接点。
    return {
        "asset_id": result.asset.id if result.asset else "",
        "source_asset_id": asset.id,
        "report": result.report,
        "removed": removed_counts(outcome),
        "gates": result.gates,
        "gates_ok": not [gate for gate in result.gates if not gate["ok"]],
        "warnings": outcome.warnings,
    }
