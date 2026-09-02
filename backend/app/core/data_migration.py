from __future__ import annotations

import logging
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

LEGACY_DIRECTORY_NAMES = (".open-studio", ".openstudio")
LEGACY_DATABASE_NAMES = ("open-studio.db", "openstudio.db")
TARGET_DIRECTORY_NAME = ".mosael"
TARGET_DATABASE_NAME = "mosael.db"

# Rows in these tables represent work the user made. A newly bootstrapped Mosael
# database may already contain a user, workspace, auth session, deployment defaults,
# and provider settings; those rows must not make the old studio disappear forever.
USER_CONTENT_TABLES = (
    "agent_messages",
    "assets",
    "boards",
    "browser_actions",
    "clips",
    "generated_assets",
    "generation_jobs",
    "generation_sessions",
    "plugin_instances",
    "projects",
    "publish_accounts",
    "publish_tasks",
    "scheduled_tasks",
    "sequence_operations",
    "sequences",
    "transcripts",
    "workflows",
)
USER_CONTENT_DIRECTORIES = ("avatars", "exports", "media", "plugins", "recordings")


@dataclass(frozen=True)
class DatabaseState:
    readable: bool
    has_workspace: bool = False
    has_user_content: bool = False


@dataclass(frozen=True)
class DataMigrationResult:
    target: Path
    status: str
    source: Path | None = None
    backup: Path | None = None
    source_preserved: bool = False

    @property
    def changed(self) -> bool:
        return self.status in {"migrated", "copied"}


def _database_state(path: Path) -> DatabaseState:
    if not path.is_file() or path.stat().st_size == 0:
        return DatabaseState(readable=False)
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1)
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            has_workspace = False
            if "workspaces" in tables:
                has_workspace = bool(
                    connection.execute("SELECT 1 FROM workspaces LIMIT 1").fetchone()
                )
            has_user_content = any(
                connection.execute(f'SELECT 1 FROM "{table}" LIMIT 1').fetchone()
                for table in USER_CONTENT_TABLES
                if table in tables
            )
            return DatabaseState(
                readable=True,
                has_workspace=has_workspace,
                has_user_content=has_user_content,
            )
        finally:
            connection.close()
    except (OSError, sqlite3.Error) as error:
        logger.warning("Could not inspect local data database %s: %s", path, error)
        return DatabaseState(readable=False)


def _directory_has_payload_files(directory: Path) -> bool:
    for name in USER_CONTENT_DIRECTORIES:
        candidate = directory / name
        if candidate.is_file():
            return True
        if candidate.is_dir() and any(path.is_file() for path in candidate.rglob("*")):
            return True
    return False


def _legacy_database(directory: Path) -> Path | None:
    candidates: list[tuple[Path, DatabaseState]] = []
    for name in LEGACY_DATABASE_NAMES:
        path = directory / name
        state = _database_state(path)
        if state.readable and (state.has_workspace or state.has_user_content):
            candidates.append((path, state))
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (item[1].has_user_content, item[1].has_workspace, item[0].stat().st_size),
        reverse=True,
    )
    return candidates[0][0]


def _next_backup_path(target: Path) -> Path:
    base = target.with_name(f"{target.name}.bak-before-open-studio-migration")
    if not base.exists():
        return base
    suffix = 2
    while True:
        candidate = base.with_name(f"{base.name}-{suffix}")
        if not candidate.exists():
            return candidate
        suffix += 1


def _move_directory(source: Path, target: Path) -> bool:
    """Return True when copy fallback preserved the original source."""
    try:
        source.replace(target)
        return False
    except OSError:
        shutil.copytree(source, target)
        return True


def _rename_database(directory: Path, legacy_name: str) -> None:
    old_database = directory / legacy_name
    new_database = directory / TARGET_DATABASE_NAME
    if old_database == new_database:
        return
    if new_database.exists():
        new_database.replace(directory / f"{TARGET_DATABASE_NAME}.bak-before-open-studio-migration")
    old_database.replace(new_database)
    for suffix in ("-wal", "-shm"):
        old_sidecar = directory / f"{legacy_name}{suffix}"
        if not old_sidecar.exists():
            continue
        new_sidecar = directory / f"{TARGET_DATABASE_NAME}{suffix}"
        if new_sidecar.exists():
            new_sidecar.replace(
                directory / f"{TARGET_DATABASE_NAME}{suffix}.bak-before-open-studio-migration"
            )
        old_sidecar.replace(new_sidecar)


def migrate_default_data_dir(home: Path | None = None) -> DataMigrationResult:
    """Adopt pre-Mosael local data before the database engine is created.

    The operation is idempotent and deliberately conservative: an established
    Mosael library is never overwritten. A bootstrap-only target is backed up and
    replaced because first launch creates that target before older releases can be
    discovered.
    """
    home = home or Path.home()
    target = home / TARGET_DIRECTORY_NAME

    source: Path | None = None
    source_database: Path | None = None
    for directory_name in LEGACY_DIRECTORY_NAMES:
        candidate = home / directory_name
        if not candidate.is_dir():
            continue
        database = _legacy_database(candidate)
        if database is not None:
            source = candidate
            source_database = database
            break
    if source is None or source_database is None:
        return DataMigrationResult(target=target, status="no-legacy-data")

    if target.exists():
        target_database = target / TARGET_DATABASE_NAME
        target_state = _database_state(target_database)
        if target_database.exists() and not target_state.readable:
            return DataMigrationResult(
                target=target,
                status="target-unreadable",
                source=source,
            )
        if target_state.has_user_content or _directory_has_payload_files(target):
            return DataMigrationResult(
                target=target,
                status="target-has-user-data",
                source=source,
            )

    backup: Path | None = None
    if target.exists():
        backup = _next_backup_path(target)
        target.replace(backup)

    try:
        source_preserved = _move_directory(source, target)
        _rename_database(target, source_database.name)
    except Exception:
        if target.exists() and backup is not None:
            failed = target.with_name(f"{target.name}.failed-open-studio-migration")
            if not failed.exists():
                target.replace(failed)
            backup.replace(target)
        raise

    return DataMigrationResult(
        target=target,
        status="copied" if source_preserved else "migrated",
        source=source,
        backup=backup,
        source_preserved=source_preserved,
    )
