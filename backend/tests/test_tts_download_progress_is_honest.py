"""装运行环境那一阶段,进度条量的是**另一件事**。

用户截图:F5-TTS 卡片上写着 `0 MB / 1.5 GB`、0%,底下一行是「安装 F5-TTS 运行依赖(数 GB,
首次较慢)…」。这两句话互相矛盾:此刻在下的是 pip 轮子(torch 等,几 GB),它们进的是托管 venv,
**一个字节都不会落进 HuggingFace 权重缓存**;而进度条的分子正是按那个缓存目录的大小算的,
分母则借了权重的 1.5 GB。于是整个 pip 阶段——也就是最慢的那一段——都会停在 0%。

「0%」在这里不是"还没开始",是"量错了东西"。而它长得和"卡住了"一模一样,于是用户要么干等,
要么以为坏了去重来一次。

转写那边已经这么修过了(见 test_asr_runtime_is_honest 里同名的那条):没有分母的阶段就
**别报分母**,只报在做哪一步。这里是把同一个判据补到 TTS 上。
"""

from __future__ import annotations

import pathlib

from app.ai.runtime import tts_models
from app.ai.runtime import download_state


class _Failed:
    returncode = 1
    stderr = "boom"
    stdout = ""


def test_the_runtime_phase_does_not_borrow_the_weights_size(monkeypatch) -> None:
    """1.5 GB 是**权重**的大小,而这一阶段跑的是 pip。"""
    monkeypatch.setattr(tts_models, "resolve_engine_python", lambda engine_id: None)
    monkeypatch.setattr(tts_models.subprocess, "run", lambda *a, **k: _Failed())
    from app.ai.runtime import config as tts_config

    monkeypatch.setattr(tts_config, "managed_venv_python", lambda engine_id: pathlib.Path("/nope/python"))
    tts_models._store.clear("f5-tts")

    try:
        tts_models.ensure_engine_runtime("f5-tts")
    except RuntimeError:
        pass

    live = tts_models._store.get("f5-tts")
    assert live is not None, "这一阶段一个字都没往界面上写"
    # 同上:断言说的是哪一句(建环境 / 装依赖两句都算这一阶段),不断言字面。
    assert live.message in ("dlMsg_creatingRuntime", "dlMsg_installingDeps")
    assert live.total == 0, f"借用了权重的大小当分母:{live.total}"


def test_the_status_does_not_put_the_weights_size_back(monkeypatch) -> None:
    """光在进度记录里置 0 不够 —— `_status_dict` 曾经用 `live.total or expected_bytes` 把它顶回去。

    这正是转写那边踩过的:改对了一处,另一处又把它填回来,界面上什么都没变。
    """
    monkeypatch.setattr(tts_models, "_is_installed", lambda engine: False)
    tts_models._store.set("f5-tts", download_state.DownloadProgress(status="downloading", message="安装运行依赖…"))
    try:
        row = tts_models.get_status("f5-tts")
        assert row["total_bytes"] == 0, f"没有分母的阶段被填上了分母:{row['total_bytes']}"
        assert row["status"] == "downloading"
    finally:
        tts_models._store.clear("f5-tts")


def test_the_weights_phase_still_reports_bytes() -> None:
    """真的在下权重时,分母要在 —— 这道闸只挡"量纲不同"的那一段。"""
    tts_models._store.set(
        "f5-tts",
        download_state.DownloadProgress(status="downloading", downloaded=300_000_000, total=1_500_000_000, message="下载中"),
    )
    try:
        row = tts_models.get_status("f5-tts")
        assert row["downloaded_bytes"] == 300_000_000
        assert row["total_bytes"] == 1_500_000_000
    finally:
        tts_models._store.clear("f5-tts")


def test_installing_the_runtime_works_on_already_downloaded_weights(monkeypatch) -> None:
    """权重齐了、只差运行环境时,「安装运行环境」那颗按钮必须真的做事。

    维护者截图:F5-TTS、Fish Speech、Qwen3-TTS 三行都写着「权重已下好,…点右边补上运行环境即可」,
    点了没有任何反应 —— `start_download` 见权重齐了就早返回,没走到 ensure_engine_runtime。
    转写那边修过同一个坑(见 test_asr_runtime_is_honest 里同名的那条),这里补到 TTS 上。
    """
    started: list[str] = []
    monkeypatch.setattr(tts_models, "_is_installed", lambda engine: True)
    monkeypatch.setattr(tts_models, "runtime_status", lambda engine_id: (False, True))
    monkeypatch.setattr(
        tts_models.threading, "Thread",
        lambda target=None, args=(), daemon=False, **_kwargs: type(
            "T", (), {"start": lambda self: started.append(args[0]) if args else None}
        )(),
    )
    tts_models._store.clear("qwen-tts")
    try:
        tts_models.start_download("qwen-tts")
    finally:
        tts_models._store.clear("qwen-tts")

    assert started == ["qwen-tts"], "权重在盘上时,装运行环境这条路被挡住了"


def test_nothing_to_do_when_weights_and_runtime_are_both_there(monkeypatch) -> None:
    started: list[str] = []
    monkeypatch.setattr(tts_models, "_is_installed", lambda engine: True)
    monkeypatch.setattr(tts_models, "runtime_status", lambda engine_id: (True, True))
    monkeypatch.setattr(tts_models.threading, "Thread", lambda *a, **k: started.append("thread"))

    tts_models.start_download("f5-tts")

    assert started == []
