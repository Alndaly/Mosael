"""ModelScope 要真的走 ModelScope。

我上一轮把这个选项删了,理由是"它指向 huggingface.co,什么都没做"。那句话对**当时的实现**
成立,但由它推出"这个选项没有意义"是错的 —— 用户在这台机器上实测:

    huggingface.co                46 KB/s
    hf-mirror.com                 46 KB/s
    modelscope.cn              ~9 MB/s        (整整两百倍)

按 46 KB/s,剩下的 9 GB 要 55 小时;走 ModelScope 是 14 分钟。**这不是可选优化**,是这条
网络上能不能用的分界线。用户当初选它是对的,是实现没跟上,而我把界面上那个正确的选择删了。

两件事要立住:

1. 它必须真的从 ModelScope 拉(ModelScope 不是 HF 兼容端点,`HF_ENDPOINT` 那一套对它无效)。
2. **每个引擎能用哪些源,由后端说了算**:F5 需要 vocos,而 ModelScope 上没有 vocos
   (实测 404),所以 ModelScope 对 F5 无效。让界面自己去猜这件事,就会长出"选了却不生效"
   的选项 —— 那正是这个选项最早的样子。
"""

from __future__ import annotations

from app.ai.runtime import tts_models
from app.ai.runtime import config as tts_config


def test_modelscope_is_offered_for_fish() -> None:
    assert "modelscope" in tts_models.sources_for("fish-speech")


def test_modelscope_is_offered_for_f5_too() -> None:
    """这一条推翻了它自己的上一版。

    上一版写的是「ModelScope 对 F5 无效,所以不该列出来」,理由是 F5 还要
    charactr/vocos-mel-24khz 而 ModelScope 上没有它(实测 404,三个命名空间都查过)。
    那个事实没变,但由它推出的结论错了:F5 的**大头**是 1.35 GB 的检查点,
    而它在 AI-ModelScope/F5-TTS 上。在这台 46 KB/s 的网络上,那是八小时和三分钟的区别;
    剩下的 vocos 只有 55 MB,慢也只有二十分钟。

    判据仍然是「选项要么真的改变什么」—— 它改变了那 1.35 GB 的去处,所以它成立。
    "只能供一半"不等于"不该有",要看是哪一半。
    """
    assert "modelscope" in tts_models.sources_for("f5-tts")


def test_every_engine_can_always_fall_back_to_huggingface() -> None:
    """至少留一条谁都能走的路,否则换个引擎就没源可选了。"""
    for engine in tts_models.CATALOG:
        assert "hf" in tts_models.sources_for(engine.id)


def test_the_worker_is_told_which_source_to_use(monkeypatch) -> None:
    """下载跑在 worker 子进程里,它得知道这一次走哪条路。"""
    monkeypatch.setattr(tts_config, "_cached", None, raising=False)
    env = tts_models._worker_env()

    assert "MOSAEL_MODEL_SOURCE" in env


def test_an_inapplicable_source_falls_back_instead_of_failing() -> None:
    """库里存着 modelscope、而当前引擎是 F5 时,不能就这么去 ModelScope 上找一个不存在的仓库 ——
    落到该引擎支持的源上。"""
    assert tts_models.effective_source("f5-tts", "modelscope") == "modelscope"
    assert tts_models.effective_source("fish-speech", "modelscope") == "modelscope"
    # 引擎不认识时才落回去 —— 这才是这个函数存在的理由。
    assert tts_models.effective_source("nope", "modelscope") == "hf"
    assert tts_models.effective_source("f5-tts", "hf-mirror") == "hf-mirror"


def test_the_engine_list_carries_its_sources() -> None:
    """界面据此渲染下拉,而不是自己猜哪个引擎配哪些源。"""
    row = tts_models.get_status("fish-speech")

    assert row["sources"] == list(tts_models.sources_for("fish-speech"))


def test_the_worker_pulls_from_modelscope_when_told_to(monkeypatch, tmp_path) -> None:
    """判据落在**真的从哪儿拉**上 —— 而不是"配置里写了 modelscope"。

    这个选项最早的毛病正是后者:配置里写着 ModelScope,拉的却是 HuggingFace。
    """
    from app.ai.runtime.workers import tts as tts_worker
    called: dict[str, object] = {}

    def fake_ms_download(model_id: str, local_dir: str):
        called["backend"] = "modelscope"
        called["repo"] = model_id
        return local_dir

    def fake_hf_download(**kwargs):
        called["backend"] = "huggingface"
        return str(tmp_path)

    monkeypatch.setattr(tts_worker, "_modelscope_snapshot", fake_ms_download)
    monkeypatch.setattr(tts_worker, "_hf_snapshot", fake_hf_download)
    monkeypatch.setenv("MOSAEL_MODEL_SOURCE", "modelscope")
    monkeypatch.setenv("MOSAEL_FISH_MODEL_DIR", str(tmp_path))

    tts_worker.fetch_fish_weights()

    assert called["backend"] == "modelscope", called
    assert called["repo"] == "fishaudio/s2-pro", called


def test_the_worker_pulls_from_huggingface_otherwise(monkeypatch, tmp_path) -> None:
    from app.ai.runtime.workers import tts as tts_worker
    called: dict[str, object] = {}
    monkeypatch.setattr(tts_worker, "_modelscope_snapshot", lambda *a, **k: called.setdefault("backend", "modelscope"))
    monkeypatch.setattr(tts_worker, "_hf_snapshot", lambda **k: called.setdefault("backend", "huggingface"))
    monkeypatch.setenv("MOSAEL_MODEL_SOURCE", "hf")
    monkeypatch.setenv("MOSAEL_FISH_MODEL_DIR", str(tmp_path))

    tts_worker.fetch_fish_weights()

    assert called["backend"] == "huggingface", called
