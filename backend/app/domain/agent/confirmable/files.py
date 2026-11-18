"""本机文件删除:撤不回来,必须过确认卡。

文件工具本身按信任目录放行;删除是唯一一个即使路径在信任目录内也要人点头的动作。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from pathlib import Path

from app.domain import host_command, host_files
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


def _command_cwd(db: Session, payload: dict[str, Any], actor: str | None) -> Path:
    try:
        host_files.ensure_whole_machine(db, actor=actor)
    except host_files.HostFileNotAllowed as exc:
        raise ConfirmationError(exc.key, **exc.params) from exc
    raw = str(payload.get("cwd") or "").strip()
    if raw:
        try:
            return host_files.ensure_trusted_path(db, raw, actor=actor, must_exist=True, directory=True).path
        except host_files.HostFileError as exc:
            raise ConfirmationError(exc.key, **exc.params) from exc
        except host_files.HostFileNotAllowed as exc:
            raise ConfirmationError(exc.key, **exc.params) from exc
    folders = host_files.trusted_folders(db, actor=actor)
    for folder in folders:
        candidate = Path(folder)
        if candidate.is_dir():
            return candidate
    if folders:
        candidate = Path(folders[0])
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    raise ConfirmationError("hostCmdErr_noCwd")


def _validate_command(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    _command_cwd(db, payload, actor)
    try:
        payload["args"] = host_command.validate(
            str(payload.get("command") or ""),
            payload.get("args") or [],
            float(payload.get("timeout_seconds") or 60),
        )
    except host_command.HostCommandError as exc:
        raise ConfirmationError(exc.key, **exc.params) from exc


def _summarize_command(db: Session, payload: dict[str, Any]) -> Summary:
    return "confirm_runHostCommand", {
        "command": " ".join([str(payload.get("command") or ""), *[str(one) for one in payload.get("args") or []]]),
        "cwd": str(payload.get("cwd") or ""),
    }


def _execute_command(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload or {}
    cwd = _command_cwd(db, payload, actor)
    try:
        return host_command.run(
            str(payload.get("command") or ""),
            payload.get("args") or [],
            cwd=cwd,
            timeout=float(payload.get("timeout_seconds") or 60),
        )
    except host_command.HostCommandError as exc:
        raise ConfirmationError(exc.key, **exc.params) from exc


confirmable_tool(ConfirmableTool(
    name="host_run_command",
    permission="external",
    cost="none",
    writes=(),
    validate=_validate_command,
    summarize=_summarize_command,
    execute=_execute_command,
))


confirmable_tool(ConfirmableTool(
    name="host_delete_file",
    permission="destroy",
    cost="none",
    writes=(),
    validate=_validate,
    summarize=_summarize,
    execute=_execute,
))
