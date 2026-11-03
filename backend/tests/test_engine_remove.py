"""删除已安装引擎:删权重,最后一份同引擎模型才删运行环境。"""
from __future__ import annotations

from app.ai.runtime import asr_models, tts_models


def test_remove_asr_model_deletes_weights_and_last_runtime(tmp_path, monkeypatch) -> None:
    asr_models._store.reset()
    entry = asr_models.CATALOG[1]  # sherpa-onnx:一个托管目录
    weights = tmp_path / "sherpa-model"
    venv = tmp_path / "venv-sherpa"
    weights.mkdir()
    venv.mkdir()
    (weights / "model.onnx").write_bytes(b"x")
    monkeypatch.setattr(asr_models, "_find_sub_dir", lambda _engine, _cache: weights)
    monkeypatch.setattr(asr_models, "managed_venv_dir", lambda _engine: venv)
    monkeypatch.setattr(asr_models, "_is_installed", lambda _entry: False)
    cleared: list[bool] = []
    monkeypatch.setattr(asr_models, "clear_runtime_probes", lambda: cleared.append(True))

    asr_models.remove(entry.id)

    assert not weights.exists()
    assert not venv.exists()
    assert cleared == [True], "删掉 venv 后要让探测缓存失效，否则重下会拿旧解释器路径"


def test_remove_tts_engine_deletes_weights_and_runtime(tmp_path, monkeypatch) -> None:
    tts_models._store.reset()
    weights = tmp_path / "f5-weights"
    venv = tmp_path / "venv-f5"
    weights.mkdir()
    venv.mkdir()
    (weights / "model.safetensors").write_bytes(b"x")
    monkeypatch.setattr(tts_models.tts_config, "MANAGED_F5_MODEL", weights)
    monkeypatch.setattr(tts_models.tts_config, "managed_venv_dir", lambda _engine: venv)

    tts_models.remove("f5-tts")

    assert not weights.exists()
    assert not venv.exists()
