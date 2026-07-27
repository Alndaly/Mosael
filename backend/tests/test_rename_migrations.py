"""更名(Mibu → Open Studio)迁移的回归:数据不能因改名而丢。

这些迁移只在"老装机第一次跑新版本"时发生一次,肉眼很难复验,却是丢库/丢登录的唯一风险点,
所以在这里钉死行为。
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text

from app.core.db import PARTITION_PREFIX, engine, init_db, _migrate_partition_rename


def test_legacy_db_file_is_renamed_with_wal_sidecars(tmp_path: Path) -> None:
    """~/.open-studio/mibu.db → open-studio.db,-wal/-shm 一并搬。

    子进程里跑:迁移写在 app.core.config 的模块级,必须在 Settings 构造时才触发一次。
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    legacy = data_dir / "mibu.db"
    sqlite3.connect(legacy).execute("CREATE TABLE marker (id INTEGER)")
    for suffix in ("-wal", "-shm"):
        legacy.with_name(legacy.name + suffix).write_bytes(b"x")

    code = (
        "from app.core.config import settings;"
        "print(settings.db_path.name, settings.db_path.is_file())"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "OPEN_STUDIO_DATA_DIR": str(data_dir), "HOME": str(tmp_path)},
        cwd=Path(__file__).resolve().parents[1],
    )
    assert proc.returncode == 0, proc.stderr
    assert "open-studio.db True" in proc.stdout
    assert not legacy.exists()  # 老库已搬走,不是复制
    # marker 表随文件一起过来 → 搬的是同一个库,不是新建的空库
    assert sqlite3.connect(data_dir / "open-studio.db").execute(
        "SELECT name FROM sqlite_master WHERE name='marker'"
    ).fetchone() is not None
    for suffix in ("-wal", "-shm"):
        assert (data_dir / f"open-studio.db{suffix}").is_file()


def test_partition_rename_is_exact_and_idempotent() -> None:
    """persist:mibu-<id> → persist:<prefix>-<id>:id 原样保留,pool- 不误伤,重跑不再变。

    分区名是登录态的地址,错一个字符就是"全部平台掉登录"。
    """
    init_db()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM browser_profiles"))
        conn.execute(
            text(
                "INSERT INTO workspaces (id,name,created_at,updated_at) "
                "VALUES ('ws-rename','W',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        for pid, part in [
            ("p-legacy", "persist:mibu-ACC1"),
            ("p-pool", "persist:pool-XYZ"),
            ("p-new", f"persist:{PARTITION_PREFIX}-ACC2"),
        ]:
            conn.execute(
                text(
                    'INSERT INTO browser_profiles (id,workspace_id,name,"partition",proxy,enabled,'
                    "created_at,updated_at) VALUES (:i,'ws-rename',:i,:p,NULL,1,"
                    "CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                ),
                {"i": pid, "p": part},
            )

    _migrate_partition_rename()
    _migrate_partition_rename()  # 幂等

    with engine.begin() as conn:
        got = dict(conn.execute(text('SELECT id,"partition" FROM browser_profiles')).fetchall())
    assert got["p-legacy"] == f"persist:{PARTITION_PREFIX}-ACC1"  # id 部分逐字保留
    assert got["p-pool"] == "persist:pool-XYZ"  # 通用档案不受影响
    assert got["p-new"] == f"persist:{PARTITION_PREFIX}-ACC2"  # 已是新名,不重复加前缀


def test_legacy_mibu_env_still_configures_the_app(tmp_path: Path) -> None:
    """老部署的 MIBU_* 环境变量(和 .env)必须继续生效,否则更名 = 配置静默失效。"""
    code = "from app.core.config import settings; print('PORT', settings.backend_port)"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "MIBU_DATA_DIR": str(tmp_path / "d"),
            "MIBU_BACKEND_PORT": "9911",
        },
        cwd=Path(__file__).resolve().parents[1],
    )
    assert proc.returncode == 0, proc.stderr
    assert "PORT 9911" in proc.stdout
