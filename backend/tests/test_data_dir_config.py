from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _configured_data_dir(env: dict[str, str]) -> Path:
    result = subprocess.run(
        [sys.executable, "-c", "from app.core.config import settings; print(settings.data_dir)"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return Path(result.stdout.strip())


def test_data_dir_defaults_to_the_mosael_home_directory(tmp_path: Path) -> None:
    env = dict(os.environ)
    env.pop("MOSAEL_DATA_DIR", None)
    env["HOME"] = str(tmp_path)

    assert _configured_data_dir(env) == tmp_path / ".mosael"


def test_data_dir_honours_the_mosael_environment_variable(tmp_path: Path) -> None:
    configured = tmp_path / "library"
    env = {**os.environ, "MOSAEL_DATA_DIR": str(configured)}

    assert _configured_data_dir(env) == configured


def test_数据目录名里带百分号_数据库还开在这个目录里(tmp_path: Path) -> None:
    # SQLAlchemy 2.1 起解析 URL 字符串会把库名里的 `%41` 反转义成 `A`;手拼 `sqlite:///{路径}` 的话,
    # 引擎打开的是 `aAb/mosael.db` —— 一个不存在的目录,后端连启动都起不来。走的是真的 app.core.db。
    configured = tmp_path / "a%41b"
    env = {**os.environ, "MOSAEL_DATA_DIR": str(configured)}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.core.db import engine\n"
            "with engine.connect() as c: c.exec_driver_sql('create table t (x int)')\n"
            "print(engine.url.database)",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.stdout.strip() == str(configured / "mosael.db")
    assert (configured / "mosael.db").is_file()
