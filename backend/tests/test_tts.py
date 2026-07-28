from __future__ import annotations

import wave
from pathlib import Path

from app.audio import tts_models, tts_worker
from app.domain import tts_config


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


def _fake_repo(root: Path) -> Path:
    """A minimal dir that looks like a real fish-speech checkout (has the marker)."""
    repo = root / "fish-speech-src"
    (repo / Path(tts_config.FISH_REPO_MARKER).parent).mkdir(parents=True, exist_ok=True)
    (repo / tts_config.FISH_REPO_MARKER).write_text("# schema\n", encoding="utf-8")
    return repo


def _fake_model(root: Path) -> Path:
    model = root / "fish-speech-s2-pro"
    model.mkdir(parents=True, exist_ok=True)
    (model / tts_config.FISH_MODEL_MARKER).write_text("weights", encoding="utf-8")
    return model


def test_managed_dirs_resolve_over_sibling(tmp_path, monkeypatch) -> None:
    # A managed install (source + weights under data_dir) resolves without any Settings config.
    repo, model = _fake_repo(tmp_path), _fake_model(tmp_path)
    monkeypatch.setattr(tts_config, "MANAGED_FISH_REPO", repo)
    monkeypatch.setattr(tts_config, "MANAGED_FISH_MODEL", model)
    cfg = tts_config.TtsRuntimeConfig(
        engine="fish-speech", python_path="", source="hf-mirror", fish_repo_dir="", fish_model_dir=""
    )
    assert cfg.resolved_fish_repo == str(repo)
    assert cfg.resolved_fish_model == str(model)


def test_explicit_path_overrides_managed(tmp_path, monkeypatch) -> None:
    repo, model = _fake_repo(tmp_path), _fake_model(tmp_path)
    monkeypatch.setattr(tts_config, "MANAGED_FISH_REPO", repo)
    monkeypatch.setattr(tts_config, "MANAGED_FISH_MODEL", model)
    override = tmp_path / "custom"
    cfg = tts_config.TtsRuntimeConfig(
        engine="fish-speech", python_path="", source="hf-mirror",
        fish_repo_dir=str(override), fish_model_dir=str(override),
    )
    # Configured path wins even without the marker — the user takes responsibility.
    assert cfg.resolved_fish_repo == str(override)
    assert cfg.resolved_fish_model == str(override)


def test_marker_guards_half_clone(tmp_path, monkeypatch) -> None:
    # A dir that exists but lacks the marker file must NOT resolve (half-clone / empty).
    empty_repo = tmp_path / "fish-speech-src"
    empty_repo.mkdir()
    monkeypatch.setattr(tts_config, "MANAGED_FISH_REPO", empty_repo)
    cfg = tts_config.TtsRuntimeConfig(
        engine="fish-speech", python_path="", source="hf-mirror", fish_repo_dir="", fish_model_dir=""
    )
    assert cfg.resolved_fish_repo == ""


def test_ensure_fish_source_noop_when_present(tmp_path, monkeypatch) -> None:
    # Marker already there → no git clone attempted (would fail loudly if it ran a fake git).
    repo = _fake_repo(tmp_path)
    monkeypatch.setattr(tts_config, "MANAGED_FISH_REPO", repo)

    def _boom(*a, **k):
        raise AssertionError("git clone should not run when source already present")

    monkeypatch.setattr(tts_models.subprocess, "run", _boom)
    tts_models._ensure_fish_source()  # no exception = pass
