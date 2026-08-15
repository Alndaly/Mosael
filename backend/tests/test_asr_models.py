from __future__ import annotations

import pytest

from app.audio import asr_models


def test_catalog_status_shape() -> None:
    rows = asr_models.list_status()
    ids = {row["id"] for row in rows}
    assert "funasr" in ids
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
    # **环境也得就绪**:文件在盘上但没有解释器装了 funasr/whisperx 时,这个入口要放行去装环境
    # (见 tests/test_asr_runtime_is_honest)—— 否则那个按钮点了没有任何反应。
    monkeypatch.setattr(asr_models, "_measure", lambda e: 10**12)
    monkeypatch.setattr(asr_models, "runtime_ready", lambda engine: True)
    assert asr_models.start_download("funasr")["status"] == "installed"


def test_entry_for_transcribe() -> None:
    assert asr_models.entry_for_transcribe("funasr").id == "funasr"
    # whisperx maps to the configured whisper model size
    entry = asr_models.entry_for_transcribe("whisperx")
    assert entry is not None and entry.engine == "whisperx"
