from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import DeploymentConfig

"""部署级开关 —— **这台后端**怎么对外。

只有一处读、一处写。此前它是环境变量,于是"改它"意味着能碰到部署机并重启进程;而这是部署
管理员在界面上就该能做的决定(和发邀请码、授予管理员同一类)。

**库是唯一真相**;环境变量只在首次迁移时播一次种(见 core/db._migrate_deployment_config)。
"""


def _row(db: Session) -> DeploymentConfig:
    row = db.get(DeploymentConfig, "default")
    if row is None:
        row = DeploymentConfig(id="default")
        db.add(row)
        db.flush()
    return row


def open_registration(db: Session) -> bool:
    """陌生人能不能自己建账号。"""
    return bool(_row(db).open_registration)


def set_open_registration(db: Session, value: bool) -> None:
    _row(db).open_registration = bool(value)
