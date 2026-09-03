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
