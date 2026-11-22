"""计费回退的 token 估算:桌面端与 MosaelCloud 必须算同一个数。

`contracts/token-estimate-cases.json` 是唯一语料。两边各跑一遍:Cloud 的网关结算与桌面端
本地账本显示的是同一份用量,不能出现「应用里 1000 token,Cloud 扣 2000 token」。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.token_estimate import estimate_text_tokens

CASES = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "token-estimate-cases.json").read_text(encoding="utf-8")
)["cases"]


def test_token_estimate_matches_the_contract() -> None:
    for case in CASES:
        assert estimate_text_tokens(case["text"]) == case["tokens"], case
