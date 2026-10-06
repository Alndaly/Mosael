"""让 Mosael 装(ADR 0041 §4)的两条加列迁移:`_migrate_local_services_remember_their_python`(本机服务那一行补
`python_minor`)、`_migrate_install_sources_get_pytorch_and_github`(「管理 → 下载源」补 PyTorch 源、GitHub 镜像前缀)。

老库里已有的行要留着、新列落成「空」—— 已有的本机服务都是「用我自己装的」(第一步只有那一种),不看这一列;下载源空就是
官方 / 直连,和升级前一样。再跑一次什么都不做。
"""

from __future__ import annotations

from sqlalchemy import text

from app.core.db import engine
from tests.util import fresh_client


def _columns(table: str) -> set[str]:
    with engine.connect() as conn:
        return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}


def test_老库的本机服务补上_python_minor_已有的行留着_空着() -> None:
    from app.db.migrations import _migrate_local_services_remember_their_python

    fresh_client()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE local_services"))
        # 第一步建的那张表(没有 python_minor),和一行「用我自己装的」
        conn.execute(text(
            "CREATE TABLE local_services (instance_id VARCHAR PRIMARY KEY, service VARCHAR(40) NOT NULL, "
            "mode VARCHAR(16) NOT NULL, directory TEXT NOT NULL, python TEXT NOT NULL, port INTEGER NOT NULL UNIQUE, "
            "listen_lan BOOLEAN NOT NULL, keep_running BOOLEAN NOT NULL, extra_args JSON NOT NULL, "
            "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"))
        conn.execute(text(
            "INSERT INTO local_services VALUES ('i1', 'comfyui', 'directory', '/Users/me/ComfyUI', '', 8189, 0, 0, '[]', "
            "'2026-10-06 00:00:00', '2026-10-06 00:00:00')"))
    assert "python_minor" not in _columns("local_services")
    _migrate_local_services_remember_their_python()
    assert "python_minor" in _columns("local_services")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT mode, directory, python_minor FROM local_services")).one() == \
            ("directory", "/Users/me/ComfyUI", "")
    _migrate_local_services_remember_their_python()  # 再跑一次不报 duplicate column


def test_没有本机服务那张表的老库_什么都不做() -> None:
    from app.db.migrations import _migrate_local_services_remember_their_python

    fresh_client()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE local_services"))
    _migrate_local_services_remember_their_python()
    assert _columns("local_services") == set(), "表由 SCHEMA 建,这里不建半张"


def test_老库的下载源补上_PyTorch_源和_GitHub_镜像前缀_原来的设置不动() -> None:
    from app.db.migrations import _migrate_install_sources_get_pytorch_and_github

    fresh_client()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM tts_config"))
        conn.execute(text("ALTER TABLE tts_config DROP COLUMN pytorch_index"))
        conn.execute(text("ALTER TABLE tts_config DROP COLUMN github_mirror"))
        conn.execute(text(
            "INSERT INTO tts_config (id, engine, python_path, source, pip_index, npm_registry, fish_repo_dir, "
            "fish_model_dir, updated_at) VALUES ('default', 'f5-tts', '', 'hf-mirror', 'tsinghua', '', '', '', "
            "'2026-10-06 00:00:00')"))
    assert not {"pytorch_index", "github_mirror"} & _columns("tts_config")
    _migrate_install_sources_get_pytorch_and_github()
    assert {"pytorch_index", "github_mirror"} <= _columns("tts_config")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT pip_index, pytorch_index, github_mirror FROM tts_config")).one() == \
            ("tsinghua", "", ""), "空 = 官方 PyTorch 源、直连 GitHub,和升级前一样"
    _migrate_install_sources_get_pytorch_and_github()
