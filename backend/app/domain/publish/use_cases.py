"""发布的闸:发布账号与发布任务都归工作区,取对象顺带过闸(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

看(账号、任务列表)只要是成员;动账号、发东西、生成文案都要 `publish`。账号还有一层归属:别人的私有账号
能不能借、能不能管,由 domain/sharing 在各自的操作里判。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PublishAccount, PublishTask, User
from app.domain import sharing
from app.domain.permissions import NotVisible, ensure_workspace_access, ensure_workspace_perm


def list_accounts(db: Session, user: User, workspace_id: str) -> list[PublishAccount]:
    """他看得见的账号(别人没共享出来的私有账号不列)。"""
    ensure_workspace_access(db, user, workspace_id)
    return list(
        db.scalars(
            select(PublishAccount)
            .where(PublishAccount.workspace_id == workspace_id, sharing.visible_filter("publish_account", user, workspace_id))
            .order_by(PublishAccount.created_at)
        )
    )


def manageable_account(db: Session, user: User, account_id: str) -> PublishAccount:
    """他能改 / 复检 / 删的账号所在的工作区要 `publish`(是不是主人由各操作按 sharing 再判)。"""
    account = db.get(PublishAccount, account_id)
    if account is None:
        raise NotVisible("Account not found")
    ensure_workspace_perm(db, user, account.workspace_id, "publish")
    return account


def deletable_task(db: Session, user: User, task_id: str) -> PublishTask:
    task = db.get(PublishTask, task_id)
    if task is None:
        raise NotVisible("Publish task not found")
    ensure_workspace_perm(db, user, task.workspace_id, "publish")
    return task


def ensure_can_browse(db: Session, user: User, workspace_id: str) -> None:
    ensure_workspace_access(db, user, workspace_id)


def ensure_can_publish(db: Session, user: User, workspace_id: str) -> None:
    """在这个工作区里接账号、发东西、生成发布文案。"""
    ensure_workspace_perm(db, user, workspace_id, "publish")
