"""看图 / 看视频、拆镜头的用例:**谁能做**和**做什么**写在一起(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

对象是一份素材,闸也是素材的闸(`require_asset`,`ai` 那一档 —— 要花钱调视觉模型)。**用例住在分析域,不在素材域**:
素材是最底下的一层,分析、转写都读它;入口写在素材域里的话,素材就得回头认识分析,两个包成了环
(见 tests/test_import_layering)。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Job, User
from app.domain.analysis.service import analyze_asset
from app.domain.analysis.shots_task import start_breakdown
from app.domain.permissions import require_asset


def analyze(
    db: Session,
    user: User,
    asset_id: str,
    question: str,
    *,
    session_target: Any = None,
    profile_id: str | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    """看图 / 看视频。分析记的那一笔用量跟调用方的事务走。

    `session_target`:智能体发起时,这次对话定下的连接、模型和视频分析方式(agent/analysis_target 解析,
    **由调用方**解析好传进来 —— 分析域不认识智能体会话,认识了就把 agent、画板、Blender 一起卷进包级的环)。
    给了它,调用方传的 mode 不作数:用户在会话里选定的方式不能被工具参数覆盖。
    """
    asset = require_asset(db, user, asset_id, perm="ai")
    if session_target is not None:
        return analyze_asset(
            db, asset, question, user_id=user.id, mode=session_target.mode,
            resolved_connection=session_target.connection, model=session_target.model, surface="automation",
        )
    return analyze_asset(db, asset, question, user_id=user.id, profile_id=profile_id, mode=mode)


def start_shots(db: Session, user: User, asset_id: str, *, session_target: Any = None) -> Job:
    """排一条「拆镜头」后台任务:量刀口取帧,有视觉模型就逐镜判画面(见 domain/analysis/shots_task)。

    `session_target`:智能体发起时按**这次对话**的连接和模型判画面(和 `analyze` 同一个来源,ADR 0061 待拍板 3
    的默认挑法因此不参与);人点的(素材详情页那个按钮)不给,走「分析」那条默认挑法 —— Kimi → MiniMax → OpenAI → 兼容,
    一个都没有时机器那一半照样交。

    拆镜头会往这份素材的目录里写帧和联系表、并覆盖它的镜头表,所以是 `ai` 那一档写闸。
    """
    asset = require_asset(db, user, asset_id, perm="ai")
    profile_id, model, surface = None, "", "direct"
    if session_target is not None:
        profile_id, model, surface = session_target.connection.id, session_target.model, "automation"
    return start_breakdown(db, asset, created_by=user.id, profile_id=profile_id, model=model, surface=surface)
