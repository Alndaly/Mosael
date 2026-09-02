from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.core import config
from app.core.data_migration import migrate_default_data_dir, migrate_legacy_database_in_data_dir


def _create_database(path: Path, *, projects: int) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE workspaces (id TEXT PRIMARY KEY);
            CREATE TABLE users (id TEXT PRIMARY KEY);
            CREATE TABLE projects (id TEXT PRIMARY KEY);
            CREATE TABLE assets (id TEXT PRIMARY KEY);
            INSERT INTO workspaces VALUES ('workspace');
            INSERT INTO users VALUES ('user');
            """
        )
        for index in range(projects):
            connection.execute("INSERT INTO projects VALUES (?)", (f"project-{index}",))
            connection.execute("INSERT INTO assets VALUES (?)", (f"asset-{index}",))
        connection.commit()
    finally:
        connection.close()


def test_existing_bootstrap_directory_does_not_block_legacy_data_migration(tmp_path: Path, monkeypatch) -> None:
    legacy = tmp_path / ".open-studio"
    target = tmp_path / ".mosael"
    legacy.mkdir()
    target.mkdir()
    _create_database(legacy / "open-studio.db", projects=2)
    _create_database(target / "mosael.db", projects=0)
    (legacy / "media").mkdir()
    (legacy / "media" / "kept.txt").write_text("legacy asset", encoding="utf-8")
    (legacy / "open-studio.db-wal").write_bytes(b"wal")
    (legacy / "open-studio.db-shm").write_bytes(b"shm")
    (target / "new-install.txt").write_text("preserve in backup", encoding="utf-8")

    monkeypatch.delenv("MOSAEL_DATA_DIR", raising=False)
    monkeypatch.delenv("OPEN_STUDIO_DATA_DIR", raising=False)
    monkeypatch.setattr(config.Path, "home", classmethod(lambda cls: tmp_path))

    assert config._prepare_data_dir() == target

    assert not legacy.exists()
    assert (target / "media" / "kept.txt").read_text(encoding="utf-8") == "legacy asset"
    assert (target / "mosael.db").is_file()
    assert (target / "mosael.db-wal").read_bytes() == b"wal"
    assert (target / "mosael.db-shm").is_file()
    backup = next(tmp_path.glob(".mosael.bak-before-open-studio-migration*"))
    assert (backup / "new-install.txt").read_text(encoding="utf-8") == "preserve in backup"

    # The automatic startup hook is intentionally safe to run more than once.
    assert config._prepare_data_dir() == target
    assert list(tmp_path.glob(".mosael.bak-before-open-studio-migration*")) == [backup]


def test_established_mosael_library_is_never_replaced(tmp_path: Path) -> None:
    legacy = tmp_path / ".open-studio"
    target = tmp_path / ".mosael"
    legacy.mkdir()
    target.mkdir()
    _create_database(legacy / "open-studio.db", projects=2)
    _create_database(target / "mosael.db", projects=1)

    result = migrate_default_data_dir(tmp_path)

    assert result.status == "target-has-user-data"
    assert legacy.is_dir()
    with sqlite3.connect(target / "mosael.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone() == (1,)
    assert not list(tmp_path.glob(".mosael.bak-before-open-studio-migration*"))


def test_database_name_without_hyphen_is_also_adopted(tmp_path: Path) -> None:
    legacy = tmp_path / ".openstudio"
    legacy.mkdir()
    _create_database(legacy / "openstudio.db", projects=1)

    result = migrate_default_data_dir(tmp_path)

    assert result.status == "migrated"
    assert (tmp_path / ".mosael" / "mosael.db").is_file()
    assert not legacy.exists()


def test_legacy_database_inside_custom_data_dir_is_adopted(tmp_path: Path, monkeypatch) -> None:
    custom = tmp_path / "custom-library"
    custom.mkdir()
    _create_database(custom / "open-studio.db", projects=2)
    (custom / "open-studio.db-wal").write_bytes(b"wal")
    (custom / "open-studio.db-shm").write_bytes(b"shm")
    monkeypatch.delenv("MOSAEL_DATA_DIR", raising=False)
    monkeypatch.setenv("OPEN_STUDIO_DATA_DIR", str(custom))

    assert config._prepare_data_dir() == custom.resolve()

    assert not (custom / "open-studio.db").exists()
    assert (custom / "mosael.db").is_file()
    assert (custom / "mosael.db-wal").read_bytes() == b"wal"
    assert (custom / "mosael.db-shm").is_file()


def test_custom_data_dir_never_replaces_established_mosael_data(tmp_path: Path) -> None:
    _create_database(tmp_path / "open-studio.db", projects=2)
    _create_database(tmp_path / "mosael.db", projects=1)

    result = migrate_legacy_database_in_data_dir(tmp_path)

    assert result.status == "target-has-user-data"
    assert (tmp_path / "open-studio.db").is_file()
    with sqlite3.connect(tmp_path / "mosael.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone() == (1,)


def test_custom_data_dir_replaces_only_bootstrap_database_with_backup(tmp_path: Path) -> None:
    _create_database(tmp_path / "open-studio.db", projects=2)
    _create_database(tmp_path / "mosael.db", projects=0)

    result = migrate_legacy_database_in_data_dir(tmp_path)

    assert result.status == "migrated"
    assert result.backup is not None and result.backup.is_file()
    with sqlite3.connect(tmp_path / "mosael.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone() == (2,)
    with sqlite3.connect(result.backup) as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone() == (0,)


def test_database_file_set_rolls_back_when_a_sidecar_move_fails(tmp_path: Path, monkeypatch) -> None:
    _create_database(tmp_path / "open-studio.db", projects=2)
    (tmp_path / "open-studio.db-wal").write_bytes(b"legacy wal")
    _create_database(tmp_path / "mosael.db", projects=0)
    (tmp_path / "mosael.db-wal").write_bytes(b"current wal")
    original_replace = Path.replace

    def fail_legacy_wal(source: Path, target: Path) -> Path:
        if source.name == "open-studio.db-wal" and target.name == "mosael.db-wal":
            raise OSError("simulated sidecar failure")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_legacy_wal)

    with pytest.raises(OSError, match="simulated"):
        migrate_legacy_database_in_data_dir(tmp_path)

    with sqlite3.connect(tmp_path / "open-studio.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone() == (2,)
    with sqlite3.connect(tmp_path / "mosael.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone() == (0,)
    assert (tmp_path / "open-studio.db-wal").read_bytes() == b"legacy wal"
    assert (tmp_path / "mosael.db-wal").read_bytes() == b"current wal"


def test_configured_migration_failure_stops_startup(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MOSAEL_DATA_DIR", str(tmp_path))

    def fail(_directory: Path):
        raise OSError("migration failed")

    monkeypatch.setattr(config, "migrate_legacy_database_in_data_dir", fail)

    with pytest.raises(OSError, match="migration failed"):
        config._prepare_data_dir()
