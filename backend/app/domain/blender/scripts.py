"""Fixed Blender scripts. No user-provided Python or paths enter this API.

MCP executes on Blender's main thread. Imported scenes are separate datablocks;
writing a library preserves only their dependency graph, not unrelated projects.
"""
from __future__ import annotations

import json
from pathlib import Path


def command(operation: str, payload: dict) -> str:
    if operation not in {"send", "receive"}:
        raise ValueError("Unknown Blender operation")
    implementation = Path(__file__).with_name("worker.py").read_text(encoding="utf-8")
    # JSON is data, never interpolated into Python statements.
    return implementation + "\nrun(" + repr(operation) + ", json.loads(" + repr(json.dumps(payload)) + "))\n"
