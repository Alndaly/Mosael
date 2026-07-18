from __future__ import annotations

import wave

from app.audio import tts_models, tts_worker


def test_tts_catalog_status_shape() -> None:
    rows = tts_models.list_status()
    ids = {r["id"] for r in rows}
    assert "f5-tts" in ids and "fish-speech" in ids
    for row in rows:
        assert row["status"] in {"installed", "missing", "downloading", "failed"}
        assert {"id", "label", "detail", "expected_bytes"} <= row.keys()


def test_worker_placeholder_produces_valid_wav(tmp_path) -> None:
    # No f5-tts installed in the test interpreter → placeholder tone of estimated length.
    out = tmp_path / "out.wav"
    engine = tts_worker.synthesize({"engine": "f5-tts", "text": "你好,测试一段语音合成。"}, str(out))
    assert engine == "placeholder"
    with wave.open(str(out)) as handle:
        assert handle.getnchannels() == 1
        assert handle.getframerate() == 24000
        assert handle.getnframes() > 24000  # > 1 second


def test_estimate_scales_with_text() -> None:
    short = tts_worker._estimate_seconds("hi")
    long = tts_worker._estimate_seconds("这是一段明显更长的文本" * 5)
    assert 1.0 <= short < long <= 30.0
