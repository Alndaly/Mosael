from __future__ import annotations

from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.db.models import DeploymentConfig

"""部署级开关 —— **这台后端**怎么对外。

只有一处读、一处写。此前它是环境变量,于是"改它"意味着能碰到部署机并重启进程;而这是部署
管理员在界面上就该能做的决定(和发邀请码、授予管理员同一类)。

**库是唯一真相**;环境变量只在首次迁移时播一次种(见 core/db._migrate_deployment_config)。
"""


class DeploymentError(LocalizedError, ValueError):
    """部署级设置写不进去(格式不对)。带文案 key,按请求方的语言翻。"""


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


def community_url(db: Session) -> str:
    """社区服务的站点(ADR 0026)。空 = 这台部署不连社区。"""
    return (_row(db).community_url or "").strip().rstrip("/")


def set_community_url(db: Session, value: str) -> str:
    """设社区地址。只收 http(s) 的站点**根**(不带路径):接口前缀由 domain/community 拼,管理员填的是
    浏览器里打开官网的那个地址。空串 = 不连社区。"""
    url = (value or "").strip().rstrip("/")
    if url:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc or parts.path or parts.query or parts.fragment:
            raise DeploymentError("deployErr_communityUrlInvalid")
    _row(db).community_url = url
    return url
