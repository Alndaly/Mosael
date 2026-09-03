from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FRAGILE_UV_ENTRYPOINT = re.compile(r"\buv run(?: --frozen)? (uvicorn|pytest|pyinstaller)\b", re.IGNORECASE)
COMMAND_DOCS = (
    ROOT / "README.md",
    ROOT / "README.zh-CN.md",
    ROOT / "browser-extension" / "README.md",
    ROOT / "browser-extension" / "README.zh-CN.md",
    ROOT / "docs" / "MAINTENANCE_HOTSPOTS.md",
)


def test_repository_commands_do_not_execute_venv_console_wrappers() -> None:
    """uv console scripts bake the venv's absolute path into their shebang.

    The repository is frequently renamed or moved.  Invoke Python modules instead so a relocated
    environment can still run long enough for ``uv sync`` to repair its generated wrappers.
    """

    package = json.loads((ROOT / "package.json").read_text("utf-8"))
    commands = [f"package.json scripts.{name}: {command}" for name, command in package["scripts"].items()]
    for path in COMMAND_DOCS:
        commands.extend(
            f"{path.relative_to(ROOT)}: {line}" for line in path.read_text("utf-8").splitlines()
        )

    offenders = [command for command in commands if FRAGILE_UV_ENTRYPOINT.search(command)]
    assert offenders == [], "Use `uv run [--frozen] python -m <module>`:\n" + "\n".join(offenders)
