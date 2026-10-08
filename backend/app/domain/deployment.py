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


def shared_host_folders(db: Session) -> list[str]:
    """管理员共享给成员的本机文件夹。校验与判定在 domain/host_files,这里只管存取。"""
    return [str(item) for item in (_row(db).shared_host_folders or [])]


def set_shared_host_folders(db: Session, folders: list[str]) -> None:
    _row(db).shared_host_folders = list(folders)


def plugin_registry_url(db: Session) -> str:
    """部署管理员配的插件市场索引地址;没配是空串(用哪一份默认由 plugins.registry 决定)。"""
    return (_row(db).plugin_registry_url or "").strip()


def web_url(db: Session) -> str:
    """成员用浏览器打开 Mosael 的地址(ADR 0054);空串 = 没有网页版(桌面单机)。"""
    return (_row(db).web_url or "").strip()


def set_web_url(db: Session, value: str) -> None:
    _row(db).web_url = value.strip()


def outbound_allowlist(db: Session) -> list[str]:
    """用户给的地址可以去的内网地址。解析与判定在 core/outbound_guard,推进进程在 domain/outbound_allowlist。"""
    return [str(item) for item in (_row(db).outbound_allowlist or [])]


def set_outbound_allowlist(db: Session, entries: list[str]) -> None:
    _row(db).outbound_allowlist = list(entries)
