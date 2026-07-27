"""Isolate every test run in a throwaway data dir BEFORE app modules import.

Without this, reset_db() would drop tables in the developer's live
~/.mibu-cut/mibu.db. Environment variables outrank .env in pydantic-settings,
so setting OPEN_STUDIO_DATA_DIR here is sufficient.
"""

from __future__ import annotations

import os
import tempfile

os.environ["OPEN_STUDIO_DATA_DIR"] = tempfile.mkdtemp(prefix="mibu-test-")
# Tests drive the scheduler tick() directly; the background loop stays off.
os.environ["OPEN_STUDIO_SCHEDULER_ENABLED"] = "0"
os.environ["OPEN_STUDIO_FEISHU_AUTOSTART"] = "0"
# Don't spawn ffmpeg proxy threads on every video import during the suite;
# test_proxy.py re-enables it explicitly to exercise the pipeline.
os.environ["OPEN_STUDIO_GENERATE_PROXIES"] = "0"
# Force software (libx264+CRF) export so render output is deterministic and we
# don't depend on a hardware encoder being present on the CI/dev box.
os.environ["OPEN_STUDIO_HW_ENCODE"] = "0"
# Don't launch a headless Chromium to rasterize subtitles/花字 in the suite; the ASS
# fallback path stays exercised and tests don't depend on Playwright/dist being present.
os.environ["OPEN_STUDIO_TEXT_RASTERIZE"] = "0"

import pytest


@pytest.fixture(autouse=True)
def _reset_kb_embedding_cache():
    """The KB embedding config is cached in-process; reset it around each test
    so monkeypatched settings / DB rows don't leak between tests."""
    from app.domain.kb import config as kb_config

    kb_config.refresh()
    yield
    kb_config.refresh()
