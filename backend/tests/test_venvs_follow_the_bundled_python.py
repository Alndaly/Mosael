"""托管 venv 跟着随包解释器的次版本走 —— 换了次版本,旧 venv 就删掉重装。

随包 CPython 从 3.12 升到 3.13 时,用户机器上那些用 3.12 建的 venv(克隆、转写、分离各一份
或几份)跑不起来了:site-packages 在 `lib/python3.12/` 下,扩展绑着 3.12 的 ABI,建它的
解释器也随旧版应用一起没了。留着它,引擎在界面上是「已安装」,一跑就炸。

`drop_venvs_built_on_another_python` 由 `_drop_venvs_built_on_another_python` 这条对账每次
启动调用一次。这里验它删对了东西,也验它不碰不该碰的。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.core import interpreter
from app.core.interpreter import drop_venvs_built_on_another_python, venv_python_minor

HERE = f"{sys.version_info.major}.{sys.version_info.minor}"


def _venv(root: Path, name: str, version: str | None) -> Path:
    venv = root / name
    (venv / "bin").mkdir(parents=True)
    if version is not None:
        (venv / "pyvenv.cfg").write_text(
            f"home = /old/app/python/bin\ninclude-system-site-packages = false\nversion = {version}\n",
            encoding="utf-8",
        )
    return venv


@pytest.fixture
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    # 建 venv 用的解释器就是跑测试的这一个 —— 开发时 base_python() 也正是它。
    monkeypatch.setattr(interpreter, "base_python", lambda: sys.executable)
    tts, asr = tmp_path / "tts", tmp_path / "asr"
    tts.mkdir()
    asr.mkdir()
    return tts, asr


def test_另一个次版本建的_删掉(roots: tuple[Path, Path]) -> None:
    tts, asr = roots
    old_f5 = _venv(tts, "venv-f5-tts", "3.12.11")
    old_funasr = _venv(asr, "venv-funasr", "3.13.7")

    dropped = drop_venvs_built_on_another_python((tts, asr))

    assert sorted(dropped) == sorted([old_f5, old_funasr])
    assert not old_f5.exists() and not old_funasr.exists()


def test_同一个次版本建的_留着_补丁号不同也留着(roots: tuple[Path, Path]) -> None:
    tts, _ = roots
    same = _venv(tts, "venv-fish-speech", f"{HERE}.0")

    assert drop_venvs_built_on_another_python((tts,)) == []
    assert same.is_dir()


def test_不是托管venv的东西一概不碰(roots: tuple[Path, Path]) -> None:
    """权重、源码检出和认不出版本的目录都不归这里判。"""
    tts, _ = roots
    weights = tts / "f5-tts-weights"
    weights.mkdir()
    (weights / "model.safetensors").write_bytes(b"w")
    unknown = _venv(tts, "venv-half-made", None)  # 没有 pyvenv.cfg:半截的,或不是我们建的

    assert drop_venvs_built_on_another_python((tts,)) == []
    assert (weights / "model.safetensors").is_file()
    assert unknown.is_dir()


def test_跑第二次什么都不做(roots: tuple[Path, Path]) -> None:
    tts, _ = roots
    _venv(tts, "venv-f5-tts", "3.12.11")
    drop_venvs_built_on_another_python((tts,))

    assert drop_venvs_built_on_another_python((tts,)) == []


def test_找不到解释器时不删(roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    """说不出「现在是哪个版本」,就没有资格判谁旧 —— 删了只会逼用户白白重下几个 GB。"""
    tts, _ = roots
    old = _venv(tts, "venv-f5-tts", "3.12.11")
    monkeypatch.setattr(interpreter, "base_python", lambda: "")

    assert drop_venvs_built_on_another_python((tts,)) == []
    assert old.is_dir()


def test_读得懂uv建的venv(tmp_path: Path) -> None:
    """`python -m venv` 写 `version`,uv 写 `version_info`;两种都认。"""
    venv = tmp_path / "venv-x"
    venv.mkdir()
    (venv / "pyvenv.cfg").write_text("home = /x\nversion_info = 3.12.11\n", encoding="utf-8")

    assert venv_python_minor(venv) == "3.12"


def test_启动时的对账真的会调到它(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """登记在迁移计划里、指向三个托管根目录 —— 少登记一个根,那一类引擎就永远是「装好了却跑不起来」。"""
    from app.ai.runtime import asr_models, separation_models
    from app.ai.runtime import config as tts_config
    from app.db.migrations import _drop_venvs_built_on_another_python, migration_plan

    monkeypatch.setattr(interpreter, "base_python", lambda: sys.executable)
    roots = {}
    for module, attr, name in (
        (tts_config, "MANAGED_TTS_ROOT", "tts"),
        (asr_models, "MANAGED_ASR_ROOT", "asr"),
        (separation_models, "MANAGED_SEPARATION_ROOT", "separation"),
    ):
        root = tmp_path / name
        root.mkdir()
        monkeypatch.setattr(module, attr, root)
        roots[name] = _venv(root, "venv-engine", "3.12.11")

    _drop_venvs_built_on_another_python()

    assert not any(venv.exists() for venv in roots.values()), roots
    step = next(one for one in migration_plan().steps if one.operation is _drop_venvs_built_on_another_python)
    assert step.once is False, "这是对账:下一次换次版本时同样的事还会发生,不能跑一次就记账"


def test_别的解释器的版本是问出来的(tmp_path: Path) -> None:
    """随包那个解释器不是本进程 —— 它的版本要问它自己。"""
    from app.core.interpreter import python_minor

    fake = tmp_path / "python3"
    fake.write_text("#!/bin/sh\necho 'Python 3.12.11'\n", encoding="utf-8")
    fake.chmod(0o755)

    assert python_minor(str(fake)) == "3.12"
    assert python_minor(str(tmp_path / "missing")) == ""
