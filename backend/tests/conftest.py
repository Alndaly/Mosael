"""Isolate every test run in a throwaway data dir BEFORE app modules import.

Without this, reset_db() would drop tables in the developer's live
~/.mibu-video/mibu.db. Environment variables outrank .env in pydantic-settings,
so setting MIBU_DATA_DIR here is sufficient.
"""

from __future__ import annotations

import os
import tempfile

os.environ["MIBU_DATA_DIR"] = tempfile.mkdtemp(prefix="mibu-test-")
# Tests drive the scheduler tick() directly; the background loop stays off.
os.environ["MIBU_SCHEDULER_ENABLED"] = "0"
os.environ["MIBU_FEISHU_AUTOSTART"] = "0"
# Don't spawn ffmpeg proxy threads on every video import during the suite;
# test_proxy.py re-enables it explicitly to exercise the pipeline.
os.environ["MIBU_GENERATE_PROXIES"] = "0"

import pytest


@pytest.fixture(autouse=True)
def _reset_kb_embedding_cache():
    """The KB embedding config is cached in-process; reset it around each test
    so monkeypatched settings / DB rows don't leak between tests."""
    from app.domain.kb import config as kb_config

    kb_config.refresh()
    yield
    kb_config.refresh()
