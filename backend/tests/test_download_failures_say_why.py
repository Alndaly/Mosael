"""下载失败要说**为什么**失败,而不是猜一句"可能引擎未安装"。

用户这台机器上的实情(实测):

    引擎已就绪(解释器能 import f5_tts)         ← 顶部横幅这么说
    下载未完成,可能引擎未安装                   ← 同一页的卡片这么说
    ~/.cache/huggingface/hub/models--SWivid--F5-TTS/ 里只有一个空的 refs/main

真正的原因是第三句谁都没说出来的话:**「模型下载源」选的 hf-mirror.com 在这台机器上下不动**
(直连 huggingface.co 反而是通的)。这句话本来存在过 ——

    huggingface_hub.errors.LocalEntryNotFoundError: ... Please check your connection

—— 而 worker 的 `warmup` 用一个空的 `except Exception` 把它接住,写了个 marker wav,返回
"placeholder",**退出码 0**。于是宿主手里没有 stderr、没有非零退出码,只好回落到那句猜测。

一个吞掉的异常就是一次删掉的证据。这里要的不是更多日志,是别把已有的那句话扔了。
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from app.ai.runtime.workers import tts as tts_worker
from app.ai.runtime import tts_models
WORKER = tts_models.WORKER_PATH


def test_warmup_does_not_swallow_the_reason(tmp_path) -> None:
    """引擎导不进来 / 连不上 Hub —— 都要抛出来,而不是返回 "placeholder" 装作跑完了。"""
    with pytest.raises(Exception) as caught:
        tts_worker.warmup({"engine": "f5-tts"}, str(tmp_path / "warm.wav"))

    assert "f5_tts" in str(caught.value) or "No module" in str(caught.value), str(caught.value)


def test_the_worker_exits_non_zero_so_the_host_can_tell(tmp_path) -> None:
    """退出码 0 + 空 stderr,是宿主唯一能拿到的两样东西同时为空。"""
    proc = subprocess.run(
        [sys.executable, str(WORKER), str(tmp_path / "warm.wav")],
        input='{"action":"warmup","engine":"f5-tts"}',
        capture_output=True, text=True, timeout=120,
    )

    assert proc.returncode != 0, "预热失败了却报成功"
    assert proc.stderr.strip(), "失败了却什么都没说"


def test_the_failure_message_carries_the_real_error(monkeypatch) -> None:
    """卡片上那句话,要来自子进程说的那句,而不是一句猜测。"""
    captured: dict[str, str] = {}

    class _Child:
        def __init__(self, *a, **k) -> None:
            self.stdin = _Stdin()

        def poll(self):
            return 1

        def wait(self, *a, **k):
            return 1

    class _Stdin:
        def write(self, _data):
            return None

        def close(self):
            return None

    monkeypatch.setattr(tts_models.subprocess, "Popen", lambda *a, **k: _Child())
    monkeypatch.setattr(
        tts_models, "ChildProcess",
        lambda proc: type("C", (), {
            "raw_lines": lambda self: iter(()),
            "finish": lambda self, timeout=600: "LocalEntryNotFoundError: 连不上 hf-mirror.com",
        })(),
    )
    monkeypatch.setattr(tts_models, "_is_installed", lambda engine: False)
    #: 运行环境当作已经备好 —— 这条测试要看的是**拉权重失败时那句话**。不挡的话,单独跑时
    #: 建 venv 那一步会先撞上上面这个 Popen 桩(它替的不是那件事),测的就成了另一段代码。
    monkeypatch.setattr(tts_models, "ensure_engine_runtime", lambda engine_id: None)
    monkeypatch.setattr(tts_models, "resolve_engine_python", lambda engine_id: sys.executable)
    tts_models._store.clear("f5-tts")

    tts_models._run_download("f5-tts")

    live = tts_models._store.get("f5-tts")
    # 卡片上存的是文案 key + 参数(出口按读的人的语言翻),所以按渲染出来的那句断言。
    from app.core.i18n import render_message

    shown = render_message(live.message, "zh", live.params)
    captured["message"] = shown
    assert live.status == "failed"
    assert "hf-mirror" in shown, f"把子进程说的话丢了,只剩猜测:{shown}"
