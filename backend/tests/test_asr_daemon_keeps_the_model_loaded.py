"""识别 worker 常驻:权重加载一次,不是每次识别加载一次。

此前每次识别起一个新进程,权重跟着进程一起生一起灭 —— 一段十秒的音频,绝大部分时间花在
加载上,而上一次识别刚把同一个模型读进内存。批量转写场景下这笔账不显眼(一小时的视频,
加载那几十秒占比很小);语音对话里它就是全部:用户说完一句到看见回应,中间不能插一次加载。

合成那边同一个问题、同一套解法(见 ai/runtime/tts_daemon 与它的 511.9 秒),进程管理现在
是共用的一份(worker_pool)。这里验的是识别这一侧接对了:同一个引擎复用同一个进程、
不同引擎各占各的、失败不会把进程留在池子里。
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

from app.ai.runtime import asr_daemon


def _worker(tmp_path: Path, body: str) -> str:
    """一个假的识别 worker:按行收请求,用 ASR 的协议回话。

    **不碰真模型** —— 这条测试要证的是"进程被复用了",不是"funasr 能识别"。用真引擎的话
    这条用例要下几个 GB 权重,而它验的东西和权重无关。
    """
    script = tmp_path / "fake_asr.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import json, os, sys
            sys.path.insert(0, {str(Path(__file__).resolve().parents[1] / "app/ai/runtime/workers")!r})
            from asr_protocol import encode_event_line

            LOADS = 0

            def emit(payload):
                sys.stdout.write(encode_event_line(payload))
                sys.stdout.flush()

            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                request = json.loads(line)
                {body}
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return str(script)


COUNT_LOADS = """
                LOADS += 1
                emit({"event": "done", "language": "zh", "segments": [{"loads": LOADS}]})
"""


def test_第二次识别不再重新加载(tmp_path: Path) -> None:
    pool = asr_daemon.WorkerPool(worker_path=_worker(tmp_path, COUNT_LOADS))
    try:
        first = pool.request("funasr", sys.executable, {"audio_path": "a.wav"}, timeout=30)
        second = pool.request("funasr", sys.executable, {"audio_path": "b.wav"}, timeout=30)
    finally:
        pool.shutdown()
    # 同一个进程:计数器活着,说明权重也活着。换成一次性进程的话两次都是 1。
    assert first["segments"][0]["loads"] == 1
    assert second["segments"][0]["loads"] == 2, "第二次又重新起了进程 —— 常驻没生效"


def test_不同引擎各占各的进程(tmp_path: Path) -> None:
    """一个进程只抱一套权重。funasr 和 whisperx 挤在一起等于同时挂两份模型。"""
    pool = asr_daemon.WorkerPool(worker_path=_worker(tmp_path, COUNT_LOADS))
    try:
        pool.request("funasr", sys.executable, {}, timeout=30)
        other = pool.request("whisperx-small", sys.executable, {}, timeout=30)
    finally:
        pool.shutdown()
    assert other["segments"][0]["loads"] == 1, "另一个引擎复用了同一个进程"


def test_失败不会把进程留在池子里(tmp_path: Path) -> None:
    """报错之后再来一次要拿到一个能用的进程,而不是同一具尸体。"""
    body = """
                if request.get("boom"):
                    emit({"event": "error", "message": "引擎炸了"})
                else:
                    LOADS += 1
                    emit({"event": "done", "language": "", "segments": []})
"""
    pool = asr_daemon.WorkerPool(worker_path=_worker(tmp_path, body))
    try:
        try:
            pool.request("funasr", sys.executable, {"boom": True}, timeout=30)
        except RuntimeError as exc:
            assert "引擎炸了" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("报错没有抛出来")
        # 还能接着用。
        assert pool.request("funasr", sys.executable, {}, timeout=30)["segments"] == []
    finally:
        pool.shutdown()


def test_报错的措辞说的是识别不是合成(tmp_path: Path) -> None:
    """名词是绑定层给的。用户读到的是这个词,而"合成超时"出现在转写里只会让人找错地方。"""
    script = tmp_path / "mute.py"
    script.write_text("import sys\nfor line in sys.stdin:\n    pass\n", encoding="utf-8")
    pool = asr_daemon.WorkerPool(worker_path=str(script))
    try:
        pool.request("funasr", sys.executable, {}, timeout=0.5)
    except RuntimeError as exc:
        assert "识别" in str(exc) and "合成" not in str(exc), exc
    else:  # pragma: no cover
        raise AssertionError("哑巴 worker 没有超时")
    finally:
        pool.shutdown()
