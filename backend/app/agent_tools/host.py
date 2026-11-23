"""这台电脑上的文件与命令、HTTP 请求、跑代码。闸在 domain/host_files 与确认卡里。

从仓库根的 mcp_server.py 按工具族拆出来(架构体检第 8 条)。登记、调用身份、领域用例的调用方式见 ./registry。
"""

from __future__ import annotations

from typing import Any

from app.agent_tools.registry import confirmation_reply, default_workspace_id, open_card, REQUESTED_BY, tool, use_case
from app.api.schemas import AssetOut
from app.core.config import settings
from app.domain import host_files
from app.domain.assets import use_cases as assets_use_cases

# ---------- 本机文件:只在信任目录内自动操作 ----------
#
# 文件工具按**路径**判信任,而不是把 run_host_code 的整机器风险按目录放行。信任目录见
# domain/host_files:桌面管理员是两个 Mosael 工作目录,成员只有管理员共享的目录。


@tool(effect="reads")
def host_trusted_dirs() -> dict[str, Any]:
    """Read-only: list the local folders where file tools may operate without a confirmation card.

    These are the deployment admin's Mosael folders (Documents/Mosael, Downloads/Mosael) plus
    folders shared with members. Paths outside them are refused; arbitrary code still needs its
    own confirmation card.
    """

    return use_case(lambda db, user: {"folders": host_files.trusted_folders(db, actor=user.id)})


@tool(effect="reads")
def host_list_dir(path: str) -> dict[str, Any]:
    """Read-only: list one local folder inside a trusted folder.

    `path` must be absolute and inside a folder returned by host_trusted_dirs. Entries are
    bounded; symlinks are shown but file tools still resolve their real path before reading.
    """

    def run(db, user) -> dict[str, Any]:
        root = host_files.ensure_trusted_path(db, path, actor=user.id, must_exist=True, directory=True)
        entries: list[dict[str, Any]] = []
        truncated = False
        for child in sorted(root.path.iterdir(), key=lambda one: (not one.is_dir(), one.name.lower())):
            if len(entries) >= 500:
                truncated = True
                break
            try:
                stat = child.stat()
                kind = "dir" if child.is_dir() else "file"
                size = None if kind == "dir" else stat.st_size
            except OSError:
                kind, size = "other", None
            entries.append({"name": child.name, "path": str(child), "kind": kind, "size": size})
        return {"path": str(root.path), "entries": entries, "truncated": truncated}

    return use_case(run)


@tool(effect="reads")
def host_read_file(path: str, offset: int = 0, length: int = 20000) -> dict[str, Any]:
    """Read-only: read a text file inside a trusted folder.

    At most 20000 characters per call; use the returned `next_offset` to continue. Binary files
    return metadata only. The path is resolved with realpath before the trust check.
    """

    def run(db, user) -> dict[str, Any]:
        target = host_files.ensure_trusted_path(db, path, actor=user.id, must_exist=True)
        size = target.path.stat().st_size
        if size > 8 * 1024 * 1024:
            raise ValueError("file is larger than 8 MiB; use a narrower file")
        data = target.path.read_bytes()
        if b"\0" in data[:4096]:
            return {"path": str(target.path), "binary": True, "size": size}
        text = data.decode("utf-8", errors="replace")
        start = max(0, offset)
        chunk = text[start:start + max(1, min(length, 20000))]
        end = start + len(chunk)
        return {"path": str(target.path), "text": chunk, "next_offset": None if end >= len(text) else end, "size": size}

    return use_case(run)


@tool(effect="writes")
def host_write_file(path: str, content: str, overwrite: bool = False) -> dict[str, Any]:
    """Write a UTF-8 file inside a trusted folder, creating parent folders as needed.

    Existing files are not replaced unless `overwrite=true`. This tool never leaves a trusted
    folder; arbitrary code is a different tool and still requires confirmation.
    """

    if len(content.encode("utf-8")) > 1024 * 1024:
        raise ValueError("content is larger than 1 MiB")

    def run(db, user) -> dict[str, Any]:
        target = host_files.ensure_trusted_path(db, path, actor=user.id)
        if target.path.exists() and not overwrite:
            raise ValueError("file exists; pass overwrite=true to replace it")
        target.path.parent.mkdir(parents=True, exist_ok=True)
        target.path.write_text(content, encoding="utf-8")
        return {"path": str(target.path), "bytes": target.path.stat().st_size}

    return use_case(run)


@tool(effect="reads")
def host_search_files(path: str, pattern: str = "", max_results: int = 100) -> dict[str, Any]:
    """Read-only: find files under one trusted folder by a case-insensitive name substring.

    Walks recursively, skips symlinks, and returns at most 500 entries. Use it before moving or
    importing files when the exact name is not known.
    """

    def run(db, user) -> dict[str, Any]:
        root = host_files.ensure_trusted_path(db, path, actor=user.id, must_exist=True, directory=True)
        limit = max(1, min(max_results, 500))
        needle = pattern.strip().lower()
        entries: list[dict[str, Any]] = []
        truncated = False
        for child in root.path.rglob("*"):
            if child.is_symlink():
                continue
            if needle and needle not in child.name.lower():
                continue
            if len(entries) >= limit:
                truncated = True
                break
            try:
                stat = child.stat()
                entries.append({
                    "name": child.name,
                    "path": str(child),
                    "relative_path": str(child.relative_to(root.path)),
                    "kind": "dir" if child.is_dir() else "file",
                    "size": None if child.is_dir() else stat.st_size,
                })
            except OSError:
                continue
        return {"path": str(root.path), "entries": entries, "truncated": truncated}

    return use_case(run)


@tool(effect="writes")
def host_move_file(source: str, destination: str, overwrite: bool = False) -> dict[str, Any]:
    """Move or rename one file/directory between trusted folders.

    Both paths are trusted-path checked. Existing destinations are not replaced unless
    `overwrite=true`. Cross-filesystem moves fall back to copy+remove; the source is removed only
    after the destination is complete.
    """
    import shutil

    def run(db, user) -> dict[str, Any]:
        src = host_files.ensure_trusted_path(db, source, actor=user.id, must_exist=True)
        dst = host_files.ensure_trusted_path(db, destination, actor=user.id)
        if dst.path.exists() and not overwrite:
            raise ValueError("destination exists; pass overwrite=true to replace it")
        dst.path.parent.mkdir(parents=True, exist_ok=True)
        if dst.path.exists() and overwrite:
            if dst.path.is_dir():
                raise ValueError("destination is a directory")
            dst.path.unlink()
        shutil.move(str(src.path), str(dst.path))
        return {"source": str(src.path), "destination": str(dst.path)}

    return use_case(run)


@tool(effect="confirms")
def host_delete_file(path: str, workspace_id: str = "") -> dict[str, Any]:
    """Confirmation required: permanently delete one file inside a trusted folder.

    Directories are refused; this tool never deletes recursively. Get the exact path from
    host_search_files / host_list_dir first.
    """
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "host_delete_file",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"path": path},
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="writes")
def host_import_asset(path: str, workspace_id: str = "", project_id: str = "") -> dict[str, Any]:
    """Import one local media file from a trusted folder into the Mosael asset library.

    The file is registered (not copied twice); supported media suffixes are the same as the
    desktop import action. Requires the desktop backend.
    """

    if not settings.local_desktop:
        raise ValueError("local asset import is only available on the desktop backend")
    suffixes = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mp3", ".wav", ".m4a", ".aac", ".flac",
                ".png", ".jpg", ".jpeg", ".webp", ".gif"}

    def run(db, user) -> Any:
        target = host_files.ensure_trusted_path(db, path, actor=user.id, must_exist=True)
        if target.path.suffix.lower() not in suffixes:
            raise ValueError(f"unsupported media suffix: {target.path.suffix}")
        ws = workspace_id or default_workspace_id()
        return assets_use_cases.import_local(
            db, user, ws, project_id=(project_id or None), path=target.path,
        )

    return use_case(run, out=AssetOut)


@tool(effect="confirms")
def host_run_command(
    command: str,
    args: list[str] | None = None,
    cwd: str = "",
    timeout_seconds: int = 60,
    workspace_id: str = "",
) -> dict[str, Any]:
    """Confirmation required: run one allowlisted local developer command with structured argv.

    No shell is involved: pass the executable name in `command` and every argument in `args`.
    The working directory must be inside a trusted folder; omitted uses the first trusted folder.
    Only git, Python/Node/pnpm/npm, ffmpeg/ffprobe, rg, ls/pwd/cat/head/tail/wc and mkdir are
    allowed. Still requires a deployment admin and a confirmation card.
    """
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "host_run_command",
            "requested_by": REQUESTED_BY.get(),
            "payload": {
                "command": command,
                "args": args or [],
                "cwd": cwd,
                "timeout_seconds": timeout_seconds,
            },
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="confirms")
def http_request(
    url: str, method: str = "POST", headers: dict[str, Any] | None = None, body: str = ""
) -> dict[str, Any]:
    """Confirmation required: call an external HTTP API (POST/PUT/PATCH/DELETE).

    Use for APIs the built-in tools do not cover. **To READ a page or a JSON endpoint use
    fetch_url instead** — it needs no approval. This one always asks, because it changes
    something on a server we do not control. Returns {status, text, json}.
    """
    verb = (method or "POST").upper()
    payload = {"url": url, "method": verb, "headers": headers or {}, "body": body}
    confirmation = open_card(
        {
            "workspace_id": default_workspace_id(),
            "tool": "http_request",
            "requested_by": REQUESTED_BY.get(),
            "payload": payload,
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="confirms")
def run_code(code: str, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Confirmation required: run a short Python snippet in an ISOLATED sandbox and return `output`.

    Use for computation the other tools cannot express (parsing, math, reshaping data).
    The snippet reads `inputs` (a dict) and must assign its result to `output`.
    The sandbox has no network and cannot see the user's files (standard library only). To act
    on the user's own computer — their files, local programs — use run_host_code instead.
    """
    confirmation = open_card(
        {
            "workspace_id": default_workspace_id(),
            "tool": "run_code",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"code": code, "inputs": inputs or {}},
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="confirms")
def run_host_code(code: str, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Confirmation required: run Python directly on the user's computer, NOT isolated.

    For work whose whole point is the local machine: reading or organising the user's files,
    calling locally installed programs, touching paths they gave you. It runs as the user, in
    their home directory, with full file access (credential-like env vars are removed) — so use
    run_code for pure computation, and state plainly in your reply what this one changed.
    The snippet reads `inputs` and assigns its result to `output`; print() output is returned
    as `printed`. Only available on the local desktop app. Time limit 120 s.
    """
    confirmation = open_card(
        {
            "workspace_id": default_workspace_id(),
            "tool": "run_host_code",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"code": code, "inputs": inputs or {}},
        },
    )
    return confirmation_reply(confirmation)
