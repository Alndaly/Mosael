"""失败时**完整输出必须留在盘上**。

界面上只能放一句话(见 core/text.blame_line),而排查要的是全文。此前全文哪儿都没有:
`run_logged` 的失败日志只留 800 字符,报错消息只留几百字 —— 于是真机上那句
「下载没有完成,而子进程没有留下原因」除了让用户重跑一遍并录屏之外**无法诊断**。

装依赖那条路先补上了落盘,而下载权重、下载转写模型两条路还没有 —— 同一个根因的第二、
第三处。这里钉的是三条路都留。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core import run_log


@pytest.fixture(autouse=True)
def _logs_in_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(run_log.settings, "data_dir", tmp_path)
    return tmp_path


def test_it_writes_the_whole_thing_not_a_slice(_logs_in_tmp: Path) -> None:
    """裁过的日志没有意义 —— 被裁掉的那半正是没人看过的那半。"""
    body = "\n".join(f"第 {i} 行" for i in range(5_000))
    path = run_log.save(body, kind="worker", what="download-f5-tts")

    assert path is not None
    saved = path.read_text(encoding="utf-8")
    assert saved == body
    assert "第 0 行" in saved and "第 4999 行" in saved


def test_the_name_says_which_run_it_was(_logs_in_tmp: Path) -> None:
    """一个目录里躺着十几份日志,名字得说得出是谁、什么时候。"""
    path = run_log.save("x", kind="worker", what="download-f5-tts")
    assert path is not None
    assert path.name.startswith("worker-download-f5-tts-")
    assert path.suffix == ".log"


def test_a_hostile_name_cannot_escape_the_logs_dir(_logs_in_tmp: Path) -> None:
    """`what` 来自调用方拼的字符串。哪天它带上引擎 id、而 id 里有斜杠,
    不该因此写到日志目录外面去。"""
    path = run_log.save("x", kind="worker", what="../../etc/passwd")
    assert path is not None
    assert path.parent == run_log.logs_dir()


def test_old_logs_are_pruned_but_not_the_other_kind(_logs_in_tmp: Path) -> None:
    """留最近若干份:只留一份的话「上次成功、这次失败差在哪」就没得比,
    不清理则是往用户的数据目录里堆垃圾。**按类别各留各的** —— 下了几十次模型
    不该把装依赖的日志挤掉。"""
    pip_log = run_log.save("pip 的那份", kind="pip", what="install")
    assert pip_log is not None
    for i in range(run_log.KEEP + 5):
        run_log.save(f"第 {i} 次", kind="worker", what=f"download-{i}")

    workers = list(run_log.logs_dir().glob("worker-*.log"))
    assert len(workers) <= run_log.KEEP
    assert pip_log.exists(), "另一类的日志被挤掉了"


def test_a_write_failure_is_swallowed_not_raised(monkeypatch, tmp_path: Path) -> None:
    """落不了盘是件小事,不该让它把正在报的那个错盖掉。"""
    monkeypatch.setattr(run_log.settings, "data_dir", tmp_path / "nope")
    monkeypatch.setattr(run_log.Path, "write_text", _boom)
    assert run_log.save("x", kind="worker", what="w") is None


def _boom(*_args, **_kwargs):
    raise OSError("read-only file system")


def test_all_three_failure_paths_save_their_output() -> None:
    """三条路都得留:装依赖、下载克隆权重、下载转写模型。

    少一条,那一条的失败就又变回"请用户再跑一遍并录屏"。
    """
    import inspect

    from app.ai.runtime import asr_models, tts_models
    from app.core import pip_install

    for module, name in ((pip_install, "core/pip_install"),
                         (tts_models, "ai/runtime/tts_models"),
                         (asr_models, "ai/runtime/asr_models")):
        source = inspect.getsource(module)
        assert "run_log.save(" in source, f"{name} 的失败路径没有把完整输出落盘"
