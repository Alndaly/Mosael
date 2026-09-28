"""谁能驱动飞书机器人:一个飞书用户(open_id)绑定到一个 Mosael 成员,机器人就以**那个成员**的身份和
权限行事。绑定靠成员在 Mosael 里自己生成的一次性绑定码(10 分钟有效),发给机器人即完成。
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import FeishuBindCode, FeishuBinding, User, WorkspaceMember, now


def _is_member(db: Session, workspace_id: str, user_id: str) -> bool:
    return db.get(WorkspaceMember, {"workspace_id": workspace_id, "user_id": user_id}) is not None


def resolve_sender(db: Session, workspace_id: str, open_id: str) -> User | None:
    """The Mosael account bound to this Feishu sender — only if still a workspace member."""
    binding = db.get(FeishuBinding, {"workspace_id": workspace_id, "open_id": open_id})
    if binding is None or not _is_member(db, workspace_id, binding.user_id):
        return None
    return db.get(User, binding.user_id)


def redeem_bind_code(db: Session, workspace_id: str, open_id: str, text: str) -> User | None:
    """If `text` is a live bind code for this workspace, bind open_id → its issuer and consume it."""
    code = (text or "").strip().upper()
    if not (4 <= len(code) <= 16):
        return None
    row = db.get(FeishuBindCode, {"workspace_id": workspace_id, "code": code})
    if row is None or row.expires_at < now() or not _is_member(db, workspace_id, row.user_id):
        return None
    db.merge(FeishuBinding(workspace_id=workspace_id, open_id=open_id, user_id=row.user_id))
    db.delete(row)
    db.commit()
    return db.get(User, row.user_id)


def issue_bind_code(db: Session, workspace_id: str, user_id: str) -> tuple[str, datetime]:
    """Member self-issues a one-time code (10-min TTL) to redeem from Feishu."""
    code = secrets.token_hex(3).upper()  # 6 hex chars
    expires = now() + timedelta(minutes=10)
    db.merge(FeishuBindCode(workspace_id=workspace_id, code=code, user_id=user_id, expires_at=expires))
    db.commit()
    return code, expires


def list_bindings(db: Session, workspace_id: str) -> list[tuple[str, User]]:
    rows = db.execute(
        select(FeishuBinding.open_id, User)
        .join(User, User.id == FeishuBinding.user_id)
        .where(FeishuBinding.workspace_id == workspace_id)
    ).all()
    return [(open_id, user) for open_id, user in rows]


def remove_binding(db: Session, workspace_id: str, open_id: str) -> None:
    binding = db.get(FeishuBinding, {"workspace_id": workspace_id, "open_id": open_id})
    if binding is not None:
        db.delete(binding)
        db.commit()
