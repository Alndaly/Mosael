"""计价规则的用例:谁能看哪一份(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import ProviderPricingRule, User
from app.domain.permissions import ensure_deployment_admin, ensure_workspace_access


def list_pricing_rules(db: Session, user: User, workspace_id: str | None = None) -> list[ProviderPricingRule]:
    """这个工作区的计价规则。不给 workspace_id 就是看全库 —— 这台机器的运维视图,只给部署管理员。"""
    if workspace_id:
        ensure_workspace_access(db, user, workspace_id)
    else:
        ensure_deployment_admin(db, user)
    stmt = select(ProviderPricingRule).order_by(
        ProviderPricingRule.capability.asc(),
        ProviderPricingRule.provider.asc(),
        ProviderPricingRule.model.asc(),
        ProviderPricingRule.created_at.asc(),
    )
    if workspace_id:
        # 不属于任何工作区的规则(预填出来的都是这种,挂在连接上)对**每个**工作区都生效
        # (见 usage._best_price_rules),所以它们也得出现在这个工作区的列表里。此前这里只取
        # `workspace_id == 当前工作区`,于是预填报了「新建 12 条」,列表里却一条都看不见。
        stmt = stmt.where(
            or_(ProviderPricingRule.workspace_id == workspace_id, ProviderPricingRule.workspace_id.is_(None))
        )
    return list(db.scalars(stmt))
