"""Isolate every test run in a throwaway data dir BEFORE app modules import.

Without this, reset_db() would drop tables in the developer's live
~/.mibu-new/mibu.db. Environment variables outrank .env in pydantic-settings,
so setting MIBU_DATA_DIR here is sufficient.
"""

from __future__ import annotations

import os
import tempfile

os.environ["MIBU_DATA_DIR"] = tempfile.mkdtemp(prefix="mibu-test-")
# Tests drive the scheduler tick() directly; the background loop stays off.
os.environ["MIBU_SCHEDULER_ENABLED"] = "0"
