"""Versioned, verifiable backups of user-owned Mosael data.

The database is copied through SQLite's online backup API, never by copying the live
database/WAL files. Media and user-installed plugins are primary data; logs, exports,
downloaded model runtimes and caches are reproducible or diagnostic data and stay out.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from collections.abc import Iterable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from app.core.config import app_version, settings
from app.db.safety import DATABASE_SCHEMA_VERSION, database_version

BACKUP_FORMAT = "mosael-backup"
BACKUP_FORMAT_VERSION = 1
BACKUP_DIRECTORIES = ("media", "plugins", "avatars")
BACKUP_FILES = ("secret.key",)
RESTORE_MARKER = ".mosael-restore.json"
MAX_ARCHIVE_ENTRIES = 100_000
MAX_MANIFEST_BYTES = 5 * 1024 * 1024
_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")


class RestoreValidationError(ValueError):
    """The uploaded file is not a safe, intact Mosael backup."""


def _semver_key(value: str) -> tuple | None:
    match = _SEMVER.match(value.strip())
    if match is None:
        return None
    core = tuple(int(part) for part in match.groups()[:3])
    prerelease = match.group(4)
    if prerelease is None:
        return (*core, 1, ())
    identifiers = tuple(
        (0, int(part)) if part.isdigit() else (1, part.lower())
        for part in prerelease.split(".")
    )
    return (*core, 0, identifiers)


def _created_by_newer_app(source: str, current: str) -> bool:
    source_key = _semver_key(source)
    current_key = _semver_key(current)
    return source_key is not None and current_key is not None and source_key > current_key


def _snapshot_database(destination: Path) -> None:
    source = sqlite3.connect(settings.db_path)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def _owned_files(root: Path) -> Iterable[tuple[Path, str]]:
    for name in BACKUP_FILES:
        source = root / name
        if source.is_file() and not source.is_symlink():
            yield source, f"data/{name}"
    for name in BACKUP_DIRECTORIES:
        directory = root / name
        if not directory.is_dir() or directory.is_symlink():
            continue
        for source in sorted(directory.rglob("*")):
            if source.is_file() and not source.is_symlink():
                yield source, f"data/{source.relative_to(root).as_posix()}"


def _write_file(archive: zipfile.ZipFile, source: Path, entry: str) -> dict[str, int | str]:
    digest = hashlib.sha256()
    size = 0
    info = zipfile.ZipInfo(entry, date_time=datetime.now().timetuple()[:6])
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = 0o600 << 16
    with source.open("rb") as incoming, archive.open(info, "w", force_zip64=True) as outgoing:
        while chunk := incoming.read(1024 * 1024):
            outgoing.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return {"size": size, "sha256": digest.hexdigest()}


def create_backup_archive() -> Path:
    """Create one self-describing archive and return its temporary path."""
    maintenance = settings.data_dir / ".maintenance"
    maintenance.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(prefix="backup-", suffix=".mosael-backup", dir=maintenance)
    os.close(fd)
    archive_path = Path(raw_path)
    snapshot_path = maintenance / f"{archive_path.stem}.db"
    try:
        _snapshot_database(snapshot_path)
        files: dict[str, dict[str, int | str]] = {}
        with zipfile.ZipFile(archive_path, "w", allowZip64=True) as archive:
            files["data/mosael.db"] = _write_file(archive, snapshot_path, "data/mosael.db")
            for source, entry in _owned_files(settings.data_dir):
                files[entry] = _write_file(archive, source, entry)
            manifest = {
                "format": BACKUP_FORMAT,
                "version": BACKUP_FORMAT_VERSION,
                "created_at": datetime.now(UTC).isoformat(),
                "app_version": app_version(),
                "schema_version": database_version(snapshot_path),
                "files": files,
            }
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        return archive_path
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise
    finally:
        snapshot_path.unlink(missing_ok=True)


def _validated_entry_path(name: str) -> Path:
    if "\\" in name or "\x00" in name:
        raise RestoreValidationError(f"unsafe backup path: {name}")
    pure = PurePosixPath(name)
    if pure.is_absolute() or ".." in pure.parts or not name.startswith("data/"):
        raise RestoreValidationError(f"unsafe backup path: {name}")
    relative = pure.relative_to("data")
    if not relative.parts:
        raise RestoreValidationError(f"invalid backup path: {name}")
    first = relative.parts[0]
    if first not in {*BACKUP_DIRECTORIES, *BACKUP_FILES, "mosael.db"}:
        raise RestoreValidationError(f"unsupported backup path: {name}")
    if first in BACKUP_DIRECTORIES and len(relative.parts) < 2:
        raise RestoreValidationError(f"invalid backup path: {name}")
    if first in {*BACKUP_FILES, "mosael.db"} and len(relative.parts) != 1:
        raise RestoreValidationError(f"invalid backup path: {name}")
    return Path(*relative.parts)


def _read_manifest(archive: zipfile.ZipFile) -> dict:
    try:
        info = archive.getinfo("manifest.json")
    except KeyError as exc:
        raise RestoreValidationError("backup manifest is missing") from exc
    if info.file_size > MAX_MANIFEST_BYTES:
        raise RestoreValidationError("backup manifest is too large")
    try:
        manifest = json.loads(archive.read(info))
    except (UnicodeDecodeError, json.JSONDecodeError, RuntimeError) as exc:
        raise RestoreValidationError("backup manifest is invalid") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != BACKUP_FORMAT:
        raise RestoreValidationError("unsupported backup format")
    if manifest.get("version") != BACKUP_FORMAT_VERSION:
        raise RestoreValidationError("unsupported backup version")
    source_app_version = manifest.get("app_version")
    if not isinstance(source_app_version, str) or not source_app_version.strip():
        raise RestoreValidationError("backup app version is missing")
    if _created_by_newer_app(source_app_version, app_version()):
        raise RestoreValidationError("backup was created by a newer version of Mosael")
    schema_version = manifest.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool) or schema_version < 0:
        raise RestoreValidationError("backup database schema version is missing or invalid")
    if schema_version > DATABASE_SCHEMA_VERSION:
        raise RestoreValidationError("backup database schema is newer than this version of Mosael")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files or len(files) > MAX_ARCHIVE_ENTRIES:
        raise RestoreValidationError("backup file list is invalid")
    return manifest


def _validate_database(path: Path) -> None:
    try:
        # closing():`with sqlite3.connect(...)` 只结束事务,不关连接。这里泄漏的是**待还原
        # 备份库**的句柄,而 stage_restore_archive 的说明正指望「Windows 看不到开着的 SQLite」
        # —— 换目录那一步会撞 WinError 32。
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as database:
            rows = database.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.DatabaseError as exc:
        raise RestoreValidationError("backup database is invalid") from exc
    if rows != [("ok",)]:
        raise RestoreValidationError("backup database integrity check failed")


def stage_restore_archive(file: BinaryIO) -> tuple[str, dict]:
    """Validate and extract a backup beside the live data directory.

    Staging never mutates live data. Electron owns the subsequent stopped-process,
    atomic directory swap so Windows cannot observe an open SQLite database.
    """
    stage_id = uuid.uuid4().hex
    stage = settings.data_dir.parent / f".{settings.data_dir.name}.restore-{stage_id}"
    stage.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        file.seek(0)
        with zipfile.ZipFile(file) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(infos) > MAX_ARCHIVE_ENTRIES + 1 or len(names) != len(set(names)):
                raise RestoreValidationError("backup contains too many or duplicate entries")
            manifest = _read_manifest(archive)
            described = manifest["files"]
            if set(names) != {"manifest.json", *described.keys()}:
                raise RestoreValidationError("backup contents do not match its manifest")
            for name, claim in described.items():
                if not isinstance(name, str) or not isinstance(claim, dict):
                    raise RestoreValidationError("backup file metadata is invalid")
                relative = _validated_entry_path(name)
                info = archive.getinfo(name)
                mode = (info.external_attr >> 16) & 0o170000
                if info.is_dir() or mode == 0o120000 or info.flag_bits & 0x1:
                    raise RestoreValidationError(f"unsupported backup entry: {name}")
                if info.compress_type != zipfile.ZIP_STORED:
                    raise RestoreValidationError(f"compressed backup entry is not supported: {name}")
                size = claim.get("size")
                expected = claim.get("sha256")
                if (
                    not isinstance(size, int)
                    or isinstance(size, bool)
                    or size < 0
                    or size != info.file_size
                    or not isinstance(expected, str)
                    or len(expected) != 64
                ):
                    raise RestoreValidationError(f"invalid size or checksum metadata: {name}")
                destination = stage / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                actual_size = 0
                with archive.open(info) as incoming, destination.open("xb") as outgoing:
                    while chunk := incoming.read(1024 * 1024):
                        outgoing.write(chunk)
                        digest.update(chunk)
                        actual_size += len(chunk)
                if actual_size != size or digest.hexdigest() != expected.lower():
                    raise RestoreValidationError(f"backup checksum mismatch: {name}")
                destination.chmod(0o600)
        database_path = stage / "mosael.db"
        if not database_path.is_file():
            raise RestoreValidationError("backup database is missing")
        _validate_database(database_path)
        actual_schema_version = database_version(database_path)
        if actual_schema_version != manifest["schema_version"]:
            raise RestoreValidationError(
                "backup database schema version does not match its manifest"
            )
        (stage / RESTORE_MARKER).write_text(
            json.dumps(
                {
                    "format": BACKUP_FORMAT,
                    "version": BACKUP_FORMAT_VERSION,
                    "stage_id": stage_id,
                    "source_app_version": manifest.get("app_version"),
                    "schema_version": manifest["schema_version"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return stage_id, manifest
    except (RestoreValidationError, zipfile.BadZipFile, OSError) as exc:
        shutil.rmtree(stage, ignore_errors=True)
        if isinstance(exc, RestoreValidationError):
            raise
        raise RestoreValidationError("backup archive could not be read") from exc


__all__ = [
    "BACKUP_DIRECTORIES",
    "BACKUP_FILES",
    "BACKUP_FORMAT",
    "BACKUP_FORMAT_VERSION",
    "RESTORE_MARKER",
    "RestoreValidationError",
    "create_backup_archive",
    "stage_restore_archive",
]
