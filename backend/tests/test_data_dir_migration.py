"""更名后的数据目录/库文件迁移。

失败模式是最重的那一类:迁移没发生 → 应用开在空库上 → 用户看到"所有项目都没了"。
早先的判据是"新目录不存在才迁移",而任何进程只要导入了 app.core.db(模块层就 mkdir)
就会先把空目录建出来,此后迁移永远不触发。这里把那个场景钉死。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.core import config as config_module


def _make_db(path: Path, *, rows: int) -> None:
    """建一个带 workspaces 表的 SQLite 文件;rows=0 即"有表结构但没有数据"的空壳。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE workspaces (id TEXT PRIMARY KEY)")
        for index in range(rows):
            connection.execute("INSERT INTO workspaces (id) VALUES (?)", (f"w{index}",))
        connection.commit()
    finally:
        connection.close()


@pytest.fixture
def dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """把默认目录/老目录/settings.data_dir 都指到 tmp_path 下。"""
    target = tmp_path / ".open-studio"
    legacy = tmp_path / ".mibu-cut"
    monkeypatch.setattr(config_module, "_DEFAULT_DATA_DIR", target)
    monkeypatch.setattr(config_module, "_LEGACY_DATA_DIRS", (legacy,))
    monkeypatch.setattr(config_module.settings, "data_dir", target)
    return target, legacy


def test_migrates_when_target_missing(dirs) -> None:
    target, legacy = dirs
    _make_db(legacy / "mibu.db", rows=2)

    config_module._migrate_data_dir()

    assert not legacy.exists()
    assert config_module._db_has_rows(target / "mibu.db")


def test_migrates_even_when_an_empty_target_already_exists(dirs) -> None:
    """回归:空壳目录(含已建表但无数据的库)不得阻断迁移 —— 否则用户数据"消失"。"""
    target, legacy = dirs
    _make_db(legacy / "mibu.db", rows=2)
    _make_db(target / "open-studio.db", rows=0)  # 占位空壳

    config_module._migrate_data_dir()

    assert not legacy.exists()
    assert config_module._db_has_rows(target / "mibu.db")  # 真数据搬过来了
    # 空壳没被删,挪去 .stale 备份
    assert (target.with_name(target.name + ".stale") / "open-studio.db").is_file()


def test_leaves_everything_alone_when_target_already_has_data(dirs) -> None:
    """新目录已经有真实数据 → 绝不能被老目录覆盖。"""
    target, legacy = dirs
    _make_db(legacy / "mibu.db", rows=2)
    _make_db(target / "open-studio.db", rows=5)

    config_module._migrate_data_dir()

    assert legacy.is_dir()  # 老目录原地不动
    with sqlite3.connect(target / "open-studio.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] == 5


def test_db_filename_migration_adopts_real_db_over_empty_placeholder(dirs, monkeypatch) -> None:
    """mibu.db → open-studio.db:目标是"已建表但空"的占位库时,也要让真库顶上。"""
    target, _legacy = dirs
    _make_db(target / "mibu.db", rows=3)
    _make_db(target / "open-studio.db", rows=0)
    monkeypatch.setattr(type(config_module.settings), "db_path", property(lambda self: target / "open-studio.db"))

    config_module._migrate_db_filename()

    assert config_module._db_has_rows(target / "open-studio.db")
    assert (target / "open-studio.db.stale").is_file()  # 占位库保留


def test_db_filename_migration_is_noop_without_legacy(dirs, monkeypatch) -> None:
    target, _legacy = dirs
    _make_db(target / "open-studio.db", rows=1)
    monkeypatch.setattr(type(config_module.settings), "db_path", property(lambda self: target / "open-studio.db"))

    config_module._migrate_db_filename()  # 不应抛,也不应动任何东西

    assert config_module._db_has_rows(target / "open-studio.db")
    assert not (target / "open-studio.db.stale").exists()
