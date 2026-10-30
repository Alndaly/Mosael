"""管理操作审计:只记白名单字段,不落密码、设备令牌或上游 Key。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from cloud.models import CloudAdminAudit, CloudUser, now


def record(
    db: Session,
    *,
    actor: CloudUser,
    action: str,
    target_type: str,
    target_id: str,
    detail: dict[str, object] | None = None,
) -> None:
    db.add(
        CloudAdminAudit(
            actor_user_id=actor.id,
            actor_email=actor.email or actor.phone or actor.id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail or {},
            created_at=now(),
        )
    )
