"""一个引擎一个 venv —— 两个引擎共用一个,是"装一边弄坏另一边"。

这次是差一点:Fish Speech 的上游 `pyproject.toml` 钉着 `torch==2.8.0`、`transformers<=4.57.3`,
而同一个 venv 里 f5-tts 装的是 torch 2.13 / transformers 5.14。照它的钉子装,f5 当场废掉;
最后是**把版本钉子全去掉**才让两边同时跑起来 —— 那不是解决,是赌两边的 API 恰好兼容。
赌注会在上游某次更新时兑现,而症状是"我明明只动了 A,B 怎么坏了",最难查的那一类。

转写那边是同一个形状(funasr 和 whisperx 共用 `asr/venv`),而代码里的注释**早就写着**
「共用一个 venv 意味着装一边可能弄坏另一边」—— 一句写下来却没有兑现的判断。

分开之前那个共用 venv 不留作兼容候选(多路兼容本身就是负担)。把它搬走的一次性迁移已随 v1.9.11
之前的迁移一起退休(见 db/support_window):支持窗口里的每一版都已经跑过它。
"""

from __future__ import annotations

from app.ai.runtime import asr_models, tts_models
from app.ai.runtime import config as tts_config


def test_tts_venv_paths_differ_per_engine() -> None:
    assert tts_config.managed_venv_python("f5-tts") != tts_config.managed_venv_python("fish-speech")


def test_the_venv_path_names_the_engine() -> None:
    """路径里看得出是谁的 —— 出问题时用户和我都要能一眼认出该删哪个。"""
    assert "fish-speech" in str(tts_config.managed_venv_python("fish-speech"))
    assert "f5-tts" in str(tts_config.managed_venv_python("f5-tts"))


def test_the_shared_venv_is_not_a_candidate_anymore() -> None:
    """**不做旧版兼容**:共用的那个不在探测名单里。"""
    for engine in ("f5-tts", "fish-speech"):
        candidates = [str(p) for p in tts_models.candidate_pythons(engine)]
        assert not any(p.endswith("/tts/venv/bin/python") for p in candidates), candidates


def test_provisioning_targets_the_engine_directory() -> None:
    import inspect

    source = inspect.getsource(tts_models.ensure_engine_runtime)

    assert "managed_venv_dir(engine_id)" in source, source


def test_asr_engines_are_separated_too() -> None:
    assert asr_models.managed_venv_python("funasr") != asr_models.managed_venv_python("whisperx")


def test_asr_does_not_keep_the_shared_venv_as_a_candidate() -> None:
    candidates = [str(p) for p in asr_models.candidate_pythons("funasr")]

    assert not any(p.endswith("/asr/venv/bin/python") for p in candidates), candidates
