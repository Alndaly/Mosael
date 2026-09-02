from __future__ import annotations

import sqlite3
from pathlib import Path

from app.core import config
from app.core.data_migration import migrate_default_data_dir


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


def test_existing_bootstrap_directory_does_not_block_legacy_data_migration(
    tmp_path: Path, monkeypatch
) -> None:
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

    assert config._migrate_default_data_dir() == target

    assert not legacy.exists()
    assert (target / "media" / "kept.txt").read_text(encoding="utf-8") == "legacy asset"
    assert (target / "mosael.db").is_file()
    assert (target / "mosael.db-wal").read_bytes() == b"wal"
    assert (target / "mosael.db-shm").is_file()
    backup = next(tmp_path.glob(".mosael.bak-before-open-studio-migration*"))
    assert (backup / "new-install.txt").read_text(encoding="utf-8") == "preserve in backup"

    # The automatic startup hook is intentionally safe to run more than once.
    assert config._migrate_default_data_dir() == target
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
