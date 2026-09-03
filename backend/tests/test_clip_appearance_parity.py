from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from app.media.render_plan import _read_appearance


CONTRACT = json.loads((Path(__file__).parents[2] / "contracts" / "clip-appearance-cases.json").read_text())


def test_clip_appearance_contract_is_versioned() -> None:
    assert CONTRACT["contract"] == "clip-appearance"
    assert CONTRACT["version"] == 1


def test_backend_reads_every_clip_appearance_contract_case() -> None:
    for case in CONTRACT["cases"]:
        assert asdict(_read_appearance(case["effects"])) == case["expected"], case["name"]
