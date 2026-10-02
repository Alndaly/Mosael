"""开始节点选项参数「值不在选项里」的后端一侧:跑 contracts/workflow-start-option-cases.json。

画布那一侧(analyze.ts 的 startOptionViolations)跑同一份语料,见 startOptions.parity.test.ts。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.workflows import start_option_violations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

CASES = json.loads((Path(__file__).resolve().parents[2] / "contracts/workflow-start-option-cases.json").read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_start_option_contract(case: dict) -> None:
    assert start_option_violations(case["config"]) == case["violations"]
