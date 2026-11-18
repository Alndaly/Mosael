"""本机文件删除:撤不回来,必须过确认卡。

文件工具本身按信任目录放行;删除是唯一一个即使路径在信任目录内也要人点头的动作。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.domain import host_files
from app.domain.agent.confirmable.registry import ConfirmableTool, Summary, confirmable_tool
from app.domain.agent.errors import ConfirmationError


def _target(db: Session, payload: dict[str, Any], actor: str | None):
    try:
        return host_files.ensure_trusted_path(db, str(payload.get("path") or ""), actor=actor, must_exist=True)
    except host_files.HostFileError as exc:
        raise ConfirmationError(exc.key, **exc.params) from exc
    except host_files.HostFileNotAllowed as exc:
        raise ConfirmationError(exc.key, **exc.params) from exc


def _validate(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    target = _target(db, payload, actor)
    if target.path.is_dir():
        raise ConfirmationError("confirmErr_hostDirectoryDelete")
    payload["_name"] = target.path.name


def _summarize(db: Session, payload: dict[str, Any]) -> Summary:
    return "confirm_deleteHostFile", {"path": payload.get("path") or ""}


def _execute(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    target = _target(db, confirmation.payload or {}, actor)
    target.path.unlink(missing_ok=True)
    return {"path": str(target.path), "deleted": True}


confirmable_tool(ConfirmableTool(
    name="host_delete_file",
    permission="destroy",
    cost="none",
    writes=(),
    validate=_validate,
    summarize=_summarize,
    execute=_execute,
))
