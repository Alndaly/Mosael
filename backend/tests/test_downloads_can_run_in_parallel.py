"""哪些下载能并行,哪些不能 —— 判据是**它们跑在同一个进程里吗**。

此前一律串行:任意一个在下,别的按钮全灰。那条限制的原始理由是两个引擎共用一个 venv
(装一边弄坏另一边),而 venv 后来按引擎拆开了,理由没了、限制留着。

拆开之后:

- **引擎权重 / 转写模型**:各自的 venv、各自的权重目录,下载跑在**一次性子进程**里 →
  真能并行,放开。
- **F5 多语言权重**:向那个**常驻的** f5-tts 进程要(要用它 venv 里的 huggingface_hub)。
  管道有锁(见 tts_daemon._Worker),并发不会串,但也只会排队 —— 那是假的并行,
  两个都写着"下载中"而实际一个一个来,比老实说"等它下完"更误导。所以保持串行。
"""
from __future__ import annotations

import pytest

from app.audio import asr_models, f5_models, tts_models


def _recording_thread(started: list[str]):
    """替掉 threading.Thread:记下下载线程的目标 id,别的线程(后台探测等)照常放行成空操作。

    不能只写 `lambda target, args, daemon`:同一个模块里还有别处在起线程,而那些调用
    **不带 args** —— 打桩的签名比真的窄,测试就会死在一个和它无关的地方。
    """

    def factory(target=None, args=(), daemon=False, **kwargs):
        if args:
            started.append(args[0])
        return type("FakeThread", (), {"start": lambda self: None})()

    return factory


@pytest.fixture(autouse=True)
def _clean_state():
    for engine in tts_models.CATALOG:
        tts_models._store.clear(engine.id)
    for entry in asr_models.CATALOG:
        asr_models._store.clear(entry.id)
    yield
    for engine in tts_models.CATALOG:
        tts_models._store.clear(engine.id)
    for entry in asr_models.CATALOG:
        asr_models._store.clear(entry.id)


def test_a_second_engine_can_start_while_the_first_downloads(monkeypatch) -> None:
    started: list[str] = []
    monkeypatch.setattr(tts_models, "_is_installed", lambda engine: False)
    monkeypatch.setattr(tts_models.threading, "Thread",
                        _recording_thread(started))

    tts_models.start_download("f5-tts")
    assert tts_models._store.get("f5-tts").status == "downloading"
    # 另一个引擎此刻必须**也能开始** —— 它有自己的 venv 和权重目录。
    tts_models.start_download("fish-speech")
    assert started == ["f5-tts", "fish-speech"]


def test_the_same_engine_twice_is_still_refused(monkeypatch) -> None:
    """放开并行不等于放开重复:同一个引擎点两次,第二次该说它已经在下了。"""
    monkeypatch.setattr(tts_models, "_is_installed", lambda engine: False)
    monkeypatch.setattr(tts_models.threading, "Thread",
                        _recording_thread([]))

    tts_models.start_download("f5-tts")
    with pytest.raises(RuntimeError, match="已经在下载中"):
        tts_models.start_download("f5-tts")


def test_transcription_models_download_in_parallel_too(monkeypatch) -> None:
    started: list[str] = []
    monkeypatch.setattr(asr_models, "_is_installed", lambda entry: False)
    monkeypatch.setattr(asr_models, "runtime_ready", lambda engine: False)
    monkeypatch.setattr(asr_models.threading, "Thread",
                        _recording_thread(started))

    asr_models.start_download("funasr")
    asr_models.start_download("whisperx-small")
    assert started == ["funasr", "whisperx-small"]


def test_language_packs_stay_serialised(monkeypatch) -> None:
    """它们共用那个常驻进程 —— 并行只会排队,不如老实说。"""
    monkeypatch.setattr(f5_models, "installed", lambda model: False)
    monkeypatch.setattr(f5_models.threading, "Thread",
                        _recording_thread([]))

    f5_models.start_download("ja")
    try:
        with pytest.raises(RuntimeError, match="正在下载"):
            f5_models.start_download("fr")
    finally:
        f5_models.clear_live("ja")


def test_one_worker_serialises_its_own_pipe() -> None:
    """串行化放在 worker 自己身上,而不是靠每个调用方记得去拿 TTS_SLOTS。

    此前那句"外面有 TTS_SLOTS 串行化"只对合成成立;下语言权重走同一个常驻进程却绕过了它 ——
    一边下一边配音,两个请求一起写进同一个 stdin、两个线程一起读同一个 stdout,响应会串。
    """
    from app.audio import tts_daemon

    import inspect

    assert hasattr(tts_daemon._Worker, "_request_locked"), "管道锁没了?那并发请求会串"
    source = inspect.getsource(tts_daemon._Worker.request)
    assert "_pipe_lock" in source, "request() 没有先拿管道锁"
