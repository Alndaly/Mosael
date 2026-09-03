"""Crash-safe insurance snapshots around destructive database upgrades."""

from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

# Bump this exactly when startup migrations change the persistent database shape.
# SQLite stores it in the database header, making a real upgrade distinguishable
# from an ordinary restart before any migration code touches user data.
DATABASE_SCHEMA_VERSION = 1


class DatabaseVersionTooNew(RuntimeError):
    """The database was already migrated by a newer Mosael build."""


def _state(path: Path) -> tuple[int, bool]:
    if not path.is_file():
        return 0, False
    with sqlite3.connect(path) as database:
        version = int(database.execute("PRAGMA user_version").fetchone()[0])
        has_schema = database.execute(
            "select 1 from sqlite_master where type = 'table' and name not like 'sqlite_%' limit 1"
        ).fetchone() is not None
    return version, has_schema


def database_version(path: Path) -> int:
    return _state(path)[0]


def create_upgrade_snapshot(path: Path, *, from_version: int, to_version: int) -> Path:
    directory = path.parent / ".maintenance" / "database-snapshots"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    destination = directory / f"mosael-v{from_version}-to-v{to_version}-{stamp}-{uuid.uuid4().hex}.sqlite"
    temporary = destination.with_suffix(".partial")
    try:
        source = sqlite3.connect(path)
        try:
            target = sqlite3.connect(temporary)
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()
        with sqlite3.connect(temporary) as snapshot:
            if snapshot.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise sqlite3.DatabaseError("upgrade snapshot failed its integrity check")
        temporary.chmod(0o600)
        os.replace(temporary, destination)
        return destination
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def snapshot_before_upgrade(path: Path, *, target_version: int) -> Path | None:
    current_version, has_schema = _state(path)
    if current_version > target_version:
        raise DatabaseVersionTooNew(
            f"database schema v{current_version} is newer than supported v{target_version}"
        )
    if current_version == target_version or not has_schema:
        return None
    return create_upgrade_snapshot(path, from_version=current_version, to_version=target_version)


def mark_database_version(path: Path, version: int) -> None:
    with sqlite3.connect(path) as database:
        database.execute(f"PRAGMA user_version = {int(version)}")
        database.commit()


__all__ = [
    "DATABASE_SCHEMA_VERSION",
    "DatabaseVersionTooNew",
    "create_upgrade_snapshot",
    "database_version",
    "mark_database_version",
    "snapshot_before_upgrade",
]
