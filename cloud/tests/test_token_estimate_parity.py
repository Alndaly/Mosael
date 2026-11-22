"""计费回退的 token 估算:Cloud 与桌面端共用同一份契约语料。"""

from __future__ import annotations

import json
from pathlib import Path

from cloud.gateway.token_estimate import estimate_text_tokens

CASES = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "token-estimate-cases.json").read_text(encoding="utf-8")
)["cases"]


def test_token_estimate_matches_the_contract() -> None:
    for case in CASES:
        assert estimate_text_tokens(case["text"]) == case["tokens"], case
