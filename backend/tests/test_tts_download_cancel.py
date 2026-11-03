"""取消本机引擎下载:线程要停、状态要翻、半截文件要清。"""
from __future__ import annotations

import threading
import time

from app.ai.runtime import tts_models


def test_cancel_download_stops_status_and_cleans_partial_files(monkeypatch) -> None:
    tts_models._store.reset()
    tts_models._download_scopes.clear()
    tts_models._cancel_pending.clear()
    started = threading.Event()
    release = threading.Event()
    cleaned: list[str] = []

    monkeypatch.setattr(tts_models, "_is_installed", lambda _engine: False)
    monkeypatch.setattr(tts_models, "runtime_status", lambda _engine_id: (False, True))
    monkeypatch.setattr(tts_models, "_cleanup_cancelled", lambda engine_id: cleaned.append(engine_id))

    def body(_engine_id: str) -> None:
        started.set()
        release.wait(5)

    monkeypatch.setattr(tts_models, "_download_body", body)
    try:
        tts_models.start_download("f5-tts")
        assert started.wait(5)
        status = tts_models.cancel_download("f5-tts")
        assert status["status"] == "failed"
        assert status["message"] == "dlMsg_cancelled"
        release.set()
        deadline = time.monotonic() + 5
        while "f5-tts" in tts_models._download_scopes and time.monotonic() < deadline:
            time.sleep(0.01)
        assert cleaned == ["f5-tts"]
        assert "f5-tts" not in tts_models._download_scopes
    finally:
        release.set()
        tts_models._store.reset()
        tts_models._download_scopes.clear()
        tts_models._cancel_pending.clear()


def test_cancelled_download_removes_partial_venv_and_weights(tmp_path, monkeypatch) -> None:
    venv = tmp_path / "venv-f5-tts"
    weights = tmp_path / "f5-model"
    venv.mkdir()
    weights.mkdir()
    (venv / "bin").mkdir()
    (weights / "model.safetensors").write_bytes(b"partial")
    monkeypatch.setattr(tts_models.tts_config, "managed_venv_dir", lambda _engine_id: venv)
    monkeypatch.setattr(tts_models.tts_config, "MANAGED_F5_MODEL", weights)
    monkeypatch.setattr(tts_models, "_is_installed", lambda _engine: False)

    tts_models._cleanup_cancelled("f5-tts")

    assert not venv.exists()
    assert not weights.exists()
