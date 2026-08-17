"""声音克隆的运行环境由 App 托管,用户不需要手动指定 Python 解释器。

设置页那个「TTS 解释器」输入框曾是**必填**——不填就只能合成占位音,而要填对得先自己
`pip install f5-tts` 到某个 venv 里。现在点「下载」时后端会用随 App 分发的独立解释器自建
venv 并装依赖,输入框降级为高级覆盖项。

这里钉的是判定与顺序,不真装 torch(数 GB)。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.audio import tts_models
from app.core import interpreter
from app.domain import tts_config


def test_managed_venv_is_probed_before_this_interpreter() -> None:
    """托管 venv 必须排在本进程解释器之前——否则用户点完下载,探测仍旧命中装不了引擎的后端解释器。"""
    candidates = tts_models.candidate_pythons("f5-tts")
    managed = tts_config.managed_venv_python("f5-tts")
    assert managed in candidates
    import sys

    assert candidates.index(managed) < candidates.index(Path(sys.executable))


def test_explicit_override_still_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """自带环境的高级用法不能被托管 venv 抢走。"""
    monkeypatch.setattr(
        tts_config, "get",
        lambda: tts_config.TtsRuntimeConfig(
            engine="f5-tts", python_path="/custom/bin/python", source="hf-mirror", pip_index="",
            fish_repo_dir="", fish_model_dir="",
        ),
    )
    candidates = tts_models.candidate_pythons("f5-tts")
    assert candidates[0] == Path("/custom/bin/python")
    assert candidates.index(Path("/custom/bin/python")) < candidates.index(tts_config.managed_venv_python("f5-tts"))


def test_base_python_prefers_the_injected_bundled_interpreter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """壳注入的随包解释器优先——打包版后端是冻结二进制,只有它建得了 venv。"""
    fake = tmp_path / "python3"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setenv("OPEN_STUDIO_TTS_BASE_PYTHON", str(fake))
    assert interpreter.base_python() == str(fake)


def test_base_python_ignores_a_missing_injected_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """注入了但文件不在(资源没打进去)→ 退回本解释器,而不是拿着坏路径去建 venv。"""
    monkeypatch.setenv("OPEN_STUDIO_TTS_BASE_PYTHON", "/nope/python3")
    import sys

    assert interpreter.base_python() == sys.executable


def test_provision_is_skipped_when_an_interpreter_already_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """已经有能 import 引擎的解释器 → 不该再建 venv、不该跑 pip(重复装 3GB 是灾难)。"""
    monkeypatch.setattr(tts_models, "probe_interpreter", lambda _id: {"worker_ready": True, "worker_python": "/x"})

    def _boom(*args, **kwargs):
        raise AssertionError("环境已就绪时不应执行任何子进程")

    monkeypatch.setattr(tts_models.subprocess, "run", _boom)
    tts_models.ensure_engine_runtime("f5-tts")  # 不抛即通过


def test_provision_reports_a_readable_error_when_no_base_python(monkeypatch: pytest.MonkeyPatch) -> None:
    """连建 venv 的解释器都没有时,要给一句用户能照做的话,而不是 FileNotFoundError。"""
    monkeypatch.setattr(tts_models, "probe_interpreter", lambda _id: {"worker_ready": False, "worker_python": ""})
    monkeypatch.setattr(tts_config, "managed_venv_python", lambda engine=None: Path("/nope/bin/python"))
    monkeypatch.setattr(interpreter, "base_python", lambda: "")
    with pytest.raises(RuntimeError) as excinfo:
        tts_models.ensure_engine_runtime("f5-tts")
    assert "Python" in str(excinfo.value)


def test_provision_installs_declared_requirements(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """venv 已在 → 直接装依赖;装的必须是引擎声明的那几个包。"""
    venv_python = tmp_path / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/bin/sh\n")
    monkeypatch.setattr(tts_models, "probe_interpreter", lambda _id: {"worker_ready": False, "worker_python": ""})
    monkeypatch.setattr(tts_config, "managed_venv_python", lambda engine=None: venv_python)

    calls: list[list[str]] = []

    def _fake_run(cmd, **kwargs):
        calls.append([str(part) for part in cmd])
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(tts_models.subprocess, "run", _fake_run)
    tts_models.ensure_engine_runtime("f5-tts")

    # 断言的是**意图**而不是调用次数:装依赖前会先把 venv 里的 pip 升一下
    # (ensurepip 里那个是打包 CPython 时冻结的,见 core/pip_install._upgrade_pip),
    # 数次数的话,每加一步准备动作这条测试就假红一次。
    assert not any("venv" in part for call in calls for part in call), "venv 已存在时不该再建一次"
    installs = [call for call in calls if call[1:4] == ["-m", "pip", "install"] and "f5-tts" in call]
    assert len(installs) == 1
    assert installs[0][0] == str(venv_python)


def test_provision_surfaces_pip_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    venv_python = tmp_path / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/bin/sh\n")
    monkeypatch.setattr(tts_models, "probe_interpreter", lambda _id: {"worker_ready": False, "worker_python": ""})
    monkeypatch.setattr(tts_config, "managed_venv_python", lambda engine=None: venv_python)
    monkeypatch.setattr(
        tts_models.subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "no matching distribution"),
    )
    with pytest.raises(RuntimeError) as excinfo:
        tts_models.ensure_engine_runtime("f5-tts")
    assert "no matching distribution" in str(excinfo.value)


def test_pip_mirror_is_passed_to_pip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """设置页选了镜像就必须真的传给 pip —— 直连 PyPI 拉 3GB 在国内常常慢到不可用。"""
    venv_python = tmp_path / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/bin/sh\n")
    monkeypatch.setattr(tts_models, "probe_interpreter", lambda _id: {"worker_ready": False, "worker_python": ""})
    monkeypatch.setattr(tts_config, "managed_venv_python", lambda engine=None: venv_python)
    monkeypatch.setattr(
        tts_config, "get",
        lambda: tts_config.TtsRuntimeConfig(
            engine="f5-tts", python_path="", source="hf-mirror", pip_index="tsinghua",
            fish_repo_dir="", fish_model_dir="",
        ),
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        tts_models.subprocess, "run",
        lambda cmd, **kw: (calls.append([str(p) for p in cmd]), subprocess.CompletedProcess(cmd, 0, "", ""))[1],
    )
    tts_models.ensure_engine_runtime("f5-tts")
    assert "--index-url" in calls[0]
    assert calls[0][calls[0].index("--index-url") + 1] == tts_config.PIP_INDEXES["tsinghua"]


def test_default_pip_index_passes_no_index_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """留空 = 官方 PyPI:不该塞一个空的 --index-url 进 argv。"""
    venv_python = tmp_path / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/bin/sh\n")
    monkeypatch.setattr(tts_models, "probe_interpreter", lambda _id: {"worker_ready": False, "worker_python": ""})
    monkeypatch.setattr(tts_config, "managed_venv_python", lambda engine=None: venv_python)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        tts_models.subprocess, "run",
        lambda cmd, **kw: (calls.append([str(p) for p in cmd]), subprocess.CompletedProcess(cmd, 0, "", ""))[1],
    )
    tts_models.ensure_engine_runtime("f5-tts")
    assert "--index-url" not in calls[0]


def test_a_bogus_custom_index_is_ignored() -> None:
    """自定义 index 只接受 http(s):别把任意字符串塞进子进程 argv。"""
    def cfg(value: str) -> tts_config.TtsRuntimeConfig:
        return tts_config.TtsRuntimeConfig(
            engine="f5-tts", python_path="", source="hf-mirror", pip_index=value,
            fish_repo_dir="", fish_model_dir="",
        )

    assert cfg("https://example.com/simple").pip_index_url == "https://example.com/simple"
    assert cfg("--upgrade-strategy eager").pip_index_url == ""
    assert cfg("file:///etc").pip_index_url == ""
