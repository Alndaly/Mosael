"""「已安装」得是**跑得起来**的意思。

用户撞到的:转写模型那一页三行写着「已安装」,而转写一开始就报「未找到可用的转写环境」。两句话
都没说谎 —— 它们在回答**不同的问题**:

    徽章   = 模型权重的文件在磁盘上吗(`_is_installed` 只量目录大小)
    运行时 = 有没有一个 Python 解释器能 `import funasr` / `import whisperx`

而这两件事完全可以一个成立一个不成立:模型缓存在 `~/.cache/modelscope`、`~/.cache/huggingface`
里,别的工具下过、或者换过解释器,文件就在那儿;而这个应用的解释器里从来没装过那两个包。
实测那台机器:funasr 2.2GB、whisperx large-v3 6.2GB 都在盘上,没有任何解释器 import 得动。

**一个状态显示回答的问题,和用户以为它回答的问题不是同一个** —— 这是这份代码里反复出现的那类
缺陷。修法不是把徽章改得更保守,而是让它把两件事**都**说出来:文件在不在、跑不跑得起来。

顺带:那一页的「下载」按钮也走同一条解释器探测(`_resolve_python`),所以在缺环境的机器上,
点下载同样只会报错 —— 页面上没有任何一个动作是能成的。TTS 那边早就解决了这个问题(托管 venv,
点下载时后端自己把环境建好,见 audio/tts_models.ensure_engine_runtime),ASR 还停在"请你自己
去设置 OPEN_STUDIO_ASR_PYTHON"。
"""

from __future__ import annotations

from app.audio import asr_models, service


def test_the_status_says_whether_it_can_actually_run(monkeypatch) -> None:
    """文件在盘上但没有能跑它的解释器时,状态必须说出来。"""
    monkeypatch.setattr(asr_models, "_is_installed", lambda entry: True)
    monkeypatch.setattr(asr_models, "runtime_ready", lambda engine: False)

    rows = {row["id"]: row for row in asr_models.list_status()}

    row = rows["funasr-zh"]
    assert row["status"] == "installed", "文件确实在,这一半不该被改掉"
    assert row["runtime_ready"] is False, "没说「跑不起来」"


def test_a_fully_ready_model_says_so(monkeypatch) -> None:
    monkeypatch.setattr(asr_models, "_is_installed", lambda entry: True)
    monkeypatch.setattr(asr_models, "runtime_ready", lambda engine: True)

    row = {r["id"]: r for r in asr_models.list_status()}["funasr-zh"]

    assert row["status"] == "installed" and row["runtime_ready"] is True


def test_runtime_ready_asks_the_interpreter_not_the_disk(monkeypatch) -> None:
    """判据是「import 得动吗」,不是「文件在不在」—— 两者可以一个真一个假。"""
    calls: list[str] = []

    def fake_probe(engine: str) -> str:
        calls.append(engine)
        raise RuntimeError("没有装了它的解释器")

    monkeypatch.setattr(asr_models, "_resolve_python", fake_probe)
    asr_models.runtime_ready.cache_clear()

    assert asr_models.runtime_ready("funasr") is False
    assert calls == ["funasr"]


def test_the_error_says_the_models_are_fine(monkeypatch) -> None:
    """报错要说清缺的是**运行环境**,不是模型 —— 否则用户会去重下已经在盘上的 6GB。"""
    monkeypatch.setattr(service, "_candidate_pythons", lambda: [])
    service.resolve_asr_runtime.cache_clear()

    try:
        service.resolve_asr_runtime()
    except service.AsrError as exc:
        message = str(exc)
    else:
        raise AssertionError("该报错的没报")

    assert "模型" in message, f"没提模型的处境:{message}"
    assert "下载" in message or "已" in message


# ---------------- 装得上运行环境 ----------------


def test_there_is_a_way_to_install_the_runtime() -> None:
    """必须有一条**从界面走得通**的路把环境装上。

    TTS 早就解决了这件事(托管 venv,点下载时后端自己建环境,见 tts_models.ensure_engine_runtime),
    而 ASR 停在"请你自己去设置 OPEN_STUDIO_ASR_PYTHON"。对一个桌面应用的用户,那句话等于
    "这个功能你用不了" —— 尤其 FunASR 是中文转写的默认引擎,他会第一个撞上。
    """
    assert hasattr(asr_models, "ensure_engine_runtime")


def test_installing_is_skipped_when_it_already_runs(monkeypatch) -> None:
    """已经有解释器能跑它了就什么都不做 —— 别去动用户自带的环境。"""
    calls: list = []
    monkeypatch.setattr(asr_models, "runtime_ready", lambda engine: True)
    monkeypatch.setattr(asr_models.subprocess, "run", lambda *a, **k: calls.append(a))

    asr_models.ensure_engine_runtime("funasr")

    assert calls == [], "已经跑得起来还去建环境"


def test_the_download_installs_the_runtime_first(monkeypatch) -> None:
    """点「下载」要先把环境建好 —— 此前它直接探测解释器,没有就报错,于是这一页上没有任何
    一个动作是能成的:显示「已安装」,点什么都失败。"""
    import inspect

    source = inspect.getsource(asr_models._download_body)

    assert "ensure_engine_runtime" in source


def test_installing_the_runtime_works_on_an_already_downloaded_model(monkeypatch) -> None:
    """模型文件已经在盘上、只差运行环境时,那个按钮必须真的做事。

    `start_download` 对「已安装」的模型直接返回 —— 那是"文件都在了还下什么"的意思,而这里要装的
    是**另一样东西**。不放行的话,那个按钮点了没有任何反应,比报错更让人摸不着头脑。
    """
    started: list[str] = []
    monkeypatch.setattr(asr_models, "_is_installed", lambda entry: True)
    monkeypatch.setattr(asr_models, "runtime_ready", lambda engine: False)
    monkeypatch.setattr(asr_models.threading, "Thread",
                        lambda target, args, daemon: type("T", (), {"start": lambda self: started.append(args[0])})())

    asr_models.start_download("funasr-zh")

    assert started == ["funasr-zh"], "文件在盘上时,装运行环境这条路被挡住了"
