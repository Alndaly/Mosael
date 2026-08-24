"""一个引擎一个 venv —— 两个引擎共用一个,是"装一边弄坏另一边"。

这次是差一点:Fish Speech 的上游 `pyproject.toml` 钉着 `torch==2.8.0`、`transformers<=4.57.3`,
而同一个 venv 里 f5-tts 装的是 torch 2.13 / transformers 5.14。照它的钉子装,f5 当场废掉;
最后是**把版本钉子全去掉**才让两边同时跑起来 —— 那不是解决,是赌两边的 API 恰好兼容。
赌注会在上游某次更新时兑现,而症状是"我明明只动了 A,B 怎么坏了",最难查的那一类。

转写那边是同一个形状(funasr 和 whisperx 共用 `asr/venv`),而代码里的注释**早就写着**
「共用一个 venv 意味着装一边可能弄坏另一边」—— 一句写下来却没有兑现的判断。

已经存在的那个共用 venv 不留作兼容候选(多路兼容本身就是负担),而是**迁移**:它实际能跑
哪个引擎,就搬到那个引擎名下;两个都能跑就归当前选中的那个,另一个按需自己装;一个都跑不了
就是没用的数据,删掉。
"""

from __future__ import annotations

from pathlib import Path

from app.ai.runtime import asr_models, tts_models
from app.domain import tts_config


def _fake_venv(root: Path) -> Path:
    """一个长得像 venv 的目录:有 bin/python 就够这些测试用。"""
    python = tts_config._venv_python(root)
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text("#!/bin/sh\n")
    python.chmod(0o755)
    return root


def test_tts_venv_paths_differ_per_engine() -> None:
    assert tts_config.managed_venv_python("f5-tts") != tts_config.managed_venv_python("fish-speech")


def test_the_venv_path_names_the_engine() -> None:
    """路径里看得出是谁的 —— 出问题时用户和我都要能一眼认出该删哪个。"""
    assert "fish-speech" in str(tts_config.managed_venv_python("fish-speech"))
    assert "f5-tts" in str(tts_config.managed_venv_python("f5-tts"))


def test_the_shared_venv_is_not_a_candidate_anymore() -> None:
    """**不做旧版兼容**:共用的那个不在探测名单里,它由迁移处理掉。"""
    for engine in ("f5-tts", "fish-speech"):
        candidates = [str(p) for p in tts_models.candidate_pythons(engine)]
        assert not any(p.endswith("/tts/venv/bin/python") for p in candidates), candidates


def test_provisioning_targets_the_engine_directory() -> None:
    import inspect

    source = inspect.getsource(tts_models.ensure_engine_runtime)

    assert "managed_venv_dir(engine_id)" in source, source


def test_a_shared_venv_moves_to_the_engine_it_serves(tmp_path, monkeypatch) -> None:
    """只跑得了 fish,就归 fish。"""
    monkeypatch.setattr(tts_config, "MANAGED_TTS_ROOT", tmp_path)
    monkeypatch.setattr(tts_config, "LEGACY_SHARED_VENV", tmp_path / "venv")
    _fake_venv(tmp_path / "venv")
    monkeypatch.setattr(tts_config, "_engines_a_venv_can_run", lambda python: ["fish-speech"])

    tts_config.migrate_shared_venv()

    assert (tmp_path / "venv-fish-speech").is_dir()
    assert not (tmp_path / "venv").exists(), "旧目录还在 —— 那就还是两条路"


def test_a_shared_venv_serving_both_goes_to_the_selected_engine(tmp_path, monkeypatch) -> None:
    """两个都跑得了,归当前选中的那个;另一个按需自己装。"""
    monkeypatch.setattr(tts_config, "MANAGED_TTS_ROOT", tmp_path)
    monkeypatch.setattr(tts_config, "LEGACY_SHARED_VENV", tmp_path / "venv")
    _fake_venv(tmp_path / "venv")
    monkeypatch.setattr(tts_config, "_engines_a_venv_can_run", lambda python: ["f5-tts", "fish-speech"])
    monkeypatch.setattr(tts_config, "_selected_engine", lambda: "fish-speech")

    tts_config.migrate_shared_venv()

    assert (tmp_path / "venv-fish-speech").is_dir()
    assert not (tmp_path / "venv").exists()


def test_a_useless_shared_venv_is_deleted(tmp_path, monkeypatch) -> None:
    """一个引擎都跑不了的,就是没用的数据。"""
    monkeypatch.setattr(tts_config, "MANAGED_TTS_ROOT", tmp_path)
    monkeypatch.setattr(tts_config, "LEGACY_SHARED_VENV", tmp_path / "venv")
    _fake_venv(tmp_path / "venv")
    monkeypatch.setattr(tts_config, "_engines_a_venv_can_run", lambda python: [])

    tts_config.migrate_shared_venv()

    assert not (tmp_path / "venv").exists()


def test_migration_does_not_clobber_an_existing_engine_venv(tmp_path, monkeypatch) -> None:
    """目标已经有一个了就别搬 —— 那是用户后来自己装好的,盖掉它比留着旧的更糟。"""
    monkeypatch.setattr(tts_config, "MANAGED_TTS_ROOT", tmp_path)
    monkeypatch.setattr(tts_config, "LEGACY_SHARED_VENV", tmp_path / "venv")
    _fake_venv(tmp_path / "venv")
    _fake_venv(tmp_path / "venv-fish-speech")
    monkeypatch.setattr(tts_config, "_engines_a_venv_can_run", lambda python: ["fish-speech"])

    tts_config.migrate_shared_venv()

    assert (tmp_path / "venv-fish-speech" / "bin" / "python").is_file()


def test_migration_is_idempotent(tmp_path, monkeypatch) -> None:
    """没有旧目录时跑一遍什么都不该发生 —— 它每次启动都会跑。"""
    monkeypatch.setattr(tts_config, "MANAGED_TTS_ROOT", tmp_path)
    monkeypatch.setattr(tts_config, "LEGACY_SHARED_VENV", tmp_path / "venv")

    tts_config.migrate_shared_venv()
    tts_config.migrate_shared_venv()

    assert list(tmp_path.iterdir()) == []


def test_asr_engines_are_separated_too() -> None:
    assert asr_models.managed_venv_python("funasr") != asr_models.managed_venv_python("whisperx")


def test_asr_does_not_keep_the_shared_venv_as_a_candidate() -> None:
    candidates = [str(p) for p in asr_models.candidate_pythons("funasr")]

    assert not any(p.endswith("/asr/venv/bin/python") for p in candidates), candidates


def test_asr_migrates_its_shared_venv_too(tmp_path, monkeypatch) -> None:
    """转写那边同一个形状,同一条规矩 —— 不留兼容路径,搬走。"""
    python = tmp_path / "venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n")
    monkeypatch.setattr(asr_models, "MANAGED_ASR_ROOT", tmp_path)
    monkeypatch.setattr(asr_models, "LEGACY_SHARED_VENV", tmp_path / "venv")
    monkeypatch.setattr(asr_models, "_engines_a_venv_can_run", lambda p: ["funasr"])

    asr_models.migrate_shared_venv()

    assert (tmp_path / "venv-funasr").is_dir()
    assert not (tmp_path / "venv").exists()


def test_both_migrations_run_at_startup() -> None:
    """它们得**有人叫** —— 只写一个函数而没人调用,和没写一样。"""
    import inspect

    from app.db import migrations

    source = inspect.getsource(migrations)

    assert "migrate_shared_venv" in source, "启动时没有人跑这两个迁移"
