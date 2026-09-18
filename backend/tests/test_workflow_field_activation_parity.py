"""条件字段的后端一侧：跑 contracts/workflow-field-activation.json。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.workflows.field_activation import config_field_active


RATCHET = True


CASES = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts/workflow-field-activation.json").read_text()
)["cases"]


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_field_activation_contract(case: dict) -> None:
    assert config_field_active(case["spec"], case["config"], case["specs"]) is case["active"]
