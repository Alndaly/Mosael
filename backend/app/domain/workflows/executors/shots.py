"""拆镜头三节点(ADR 0061 §4):detect_shots(不花钱)、describe_shots(花钱)、shot_report(不花钱)。

领域逻辑全在 domain/shots(breakdowns.py):这里只做适配 —— 收进工作区的素材、把节点的连接解析成
`ask`、把镜头表交成节点输出。analyze_asset 那条路也读同一份表,两种入口看到的一样。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Asset
from app.domain.analysis.shots_task import vision_ask
from app.domain.assets.importer import register_file_asset
from app.domain.assets.lineage import FRAME, derived
from app.domain.jobs import current_actor
from app.domain.providers import models as provider_models
from app.domain.providers.chat_connection import require_connection, runner_choice
from app.domain.shots import breakdowns, detect, report
from app.domain.workflows.errors import WorkflowDomainError
from app.domain.workflows.executors.registry import RunScope, register
from app.domain.workflows.executors.inputs import _asset_in


def _video_in(db: Session, scope: RunScope, config: dict[str, Any]) -> Asset:
    asset = _asset_in(db, scope, str(config.get("asset_id", "")).strip())
    if asset.kind != "video":
        raise WorkflowDomainError("wfErr_shotsNotVideo", params={"name": asset.name})
    return asset


@register("detect_shots")
def detect_shots(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """刀口 / 动静 / 逐镜两帧 / 联系表,存成这份视频的镜头表(重拆覆盖,见 ADR 待拍板 2)。"""
    asset = _video_in(db, scope, config)
    raw = config.get("threshold")
    threshold = detect.DEFAULT_THRESHOLD if raw in (None, "") else float(raw)
    try:
        row = breakdowns.measure_into(
            db, asset, created_by=current_actor(db), lang=breakdowns.lang_now(), threshold=threshold,
        )
    except breakdowns.ShotBreakdownError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    sheet_assets: list[str] = []
    if str(config.get("save_sheets") or "").strip().lower() == "yes":
        #: 联系表存成素材(派生关系 frame):默认它们是镜头表的插图不进库;点名要才登记。
        folder = breakdowns.shots_dir(asset) / "sheets"
        for sheet in row.sheets:
            for point in ("a", "b"):
                path = folder / sheet[point]
                if not path.is_file():
                    continue
                made = register_file_asset(
                    db,
                    workspace_id=asset.workspace_id,
                    project_id=asset.project_id,
                    source_path=path,
                    name=f"{asset.name} · 联系表 {sheet['index']}{point.upper()}",
                    source="generated",
                    derived_from=derived(FRAME, asset.id),
                )
                sheet_assets.append(made.id)
    return {"shot_count": len(row.shots), "sheets": row.sheets, "asset_ids": sheet_assets}


@register("describe_shots")
def describe_shots(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """逐镜看画面:视觉模型判景别 / 运镜 / 画面 / 分镜提示词,代码对账。花钱(每批一次视觉调用)。"""
    asset = _video_in(db, scope, config)
    row = breakdowns.breakdown_for(db, asset.id)
    if row is None or not row.shots:
        raise WorkflowDomainError("wfErr_shotsNotBrokenDown")
    actor = current_actor(db)
    profile_id, model, pinned_by_other = runner_choice(
        db, config.get("profile_id"), str(config.get("model") or ""), user_id=actor)
    connection = require_connection(db, profile_id, user_id=actor, error=WorkflowDomainError,
                                    surface="automation", pinned_by_other=pinned_by_other)
    model = model or provider_models.model_id_for(db, connection, "chat")
    counter = iter(range(1, 10_000))
    ask = vision_ask(
        db, connection, model=model, surface="automation", user_id=actor, asset=asset,
        key_for=lambda: f"describe_shots:{scope.id}:{asset.id}:{next(counter)}",
    )
    breakdowns.judge(db, row, asset, ask, provider=connection.vendor or "", model=model)
    return {
        "judged": int(row.describe.get("judged_batches") or 0),
        "batches": int(row.describe.get("batches") or 0),
        "hints": row.hints,
        "shots": row.shots,
    }


@register("shot_report")
def shot_report(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """镜头表 Markdown + 分镜提示词 + 统计,全代码算,给下游写总结 / 存笔记。不花钱。"""
    asset = _video_in(db, scope, config)
    row = breakdowns.breakdown_for(db, asset.id)
    if row is None or not row.shots:
        raise WorkflowDomainError("wfErr_shotsNotBrokenDown")
    duration = float((row.meta or {}).get("duration") or 0)
    return {
        "report_markdown": report.report_markdown(asset.name, row.shots, duration, lang=row.lang),
        "storyboard_markdown": report.storyboard_markdown(row.shots, lang=row.lang),
        "stats": report.stats(row.shots, duration),
        "shot_count": len(row.shots),
    }
