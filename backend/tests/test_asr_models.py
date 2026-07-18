from __future__ import annotations

import pytest

from app.audio import asr_models


def test_catalog_status_shape() -> None:
    rows = asr_models.list_status()
    ids = {row["id"] for row in rows}
    assert "funasr-zh" in ids
    assert any(r["id"].startswith("whisperx-") for r in rows)
    for row in rows:
        assert row["status"] in {"installed", "missing", "downloading", "failed"}
        assert {"id", "engine", "label", "detail", "expected_bytes"} <= row.keys()


def test_installed_detection_by_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = asr_models._BY_ID["whisperx-small"]
    # Below the install threshold → missing; above → installed.
    monkeypatch.setattr(asr_models, "_measure", lambda e: 0)
    assert asr_models.get_status("whisperx-small")["status"] == "missing"
    monkeypatch.setattr(asr_models, "_measure", lambda e: entry.expected_bytes)
    assert asr_models.get_status("whisperx-small")["status"] == "installed"


def test_start_download_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asr_models, "_measure", lambda e: 0)  # nothing installed
    with pytest.raises(KeyError):
        asr_models.start_download("nope")

    # Installed model → no-op, returns installed status without spawning a thread.
    monkeypatch.setattr(asr_models, "_measure", lambda e: 10**12)
    assert asr_models.start_download("funasr-zh")["status"] == "installed"


def test_entry_for_transcribe() -> None:
    assert asr_models.entry_for_transcribe("funasr").id == "funasr-zh"
    # whisperx maps to the configured whisper model size
    entry = asr_models.entry_for_transcribe("whisperx")
    assert entry is not None and entry.engine == "whisperx"
