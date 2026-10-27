from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("check_support_window", ROOT / "scripts" / "check-support-window.py")
assert spec and spec.loader
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

TAGS = [
    "v2.2.3", "v2.2.2", "v2.2.1", "v2.2.0", "v2.1.1", "v2.1.0",
    "v2.0.1", "v2.0.0", "v1.9.11", "v1.9.10",
]


def releases(tags: list[str]) -> list[dict]:
    return [{"tag_name": tag, "draft": False, "prerelease": False} for tag in tags]


def test_current_window_is_exactly_eight_versions_behind() -> None:
    assert check.check_window(releases(TAGS), latest="v2.2.3") == 8


def test_next_release_requires_retiring_the_oldest_baseline() -> None:
    with pytest.raises(ValueError, match="expected exactly 8"):
        check.check_window(releases(["v2.2.4", *TAGS]), latest="v2.2.4")


def test_draft_and_prerelease_do_not_count() -> None:
    noisy = [
        {"tag_name": "v9.9.9", "draft": True, "prerelease": False},
        {"tag_name": "v9.9.8", "draft": False, "prerelease": True},
        *releases(TAGS),
    ]
    assert check.check_window(noisy, latest="v2.2.3") == 8


def test_oldest_must_be_a_real_release() -> None:
    with pytest.raises(ValueError, match="not a published stable release"):
        check.check_window(releases(TAGS), latest="v2.2.3", oldest="v1.9.9")
