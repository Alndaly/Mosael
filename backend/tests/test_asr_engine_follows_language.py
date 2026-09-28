"""FunASR 就是多语种的,不存在「中文预设 / 多语种」这种分法。

这里踩过两次坑,都是同一个根源 —— 把「我们当初只装了中文权重」当成了 FunASR 的属性:

  1. 最早目录里只有中文那套(paraformer-zh),于是非中文素材被中文权重转坏,结果还被标成
     language=zh,下游全按中文处理;
  2. 第一次修的时候改成「非中文一律走 WhisperX」—— 那是把命名上的绑定搬进了路由逻辑;
  3. 第二次改成「中文预设 / 多语种」两个目录项 —— 那是把一次打包选择变成了要用户做的选择。

FunASR 的 SenseVoice 按官方说明「支持超过 50 种语言,识别效果上优于 Whisper 模型」,而且自带
标点与逆文本规整。所以只留一个:**FunASR = 多语种**,语言交给模型自己判。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ai.runtime import asr_models
from app.core.db import SessionLocal
from app.domain.voices import transcription
from tests.util import fresh_client


@pytest.fixture(autouse=True)
def _both_engines_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asr_models, "resolve_engine_python", lambda engine: f"/fake/{engine}")


def _heard(monkeypatch: pytest.MonkeyPatch, language: str, provider: str = "") -> tuple[str, str]:
    """挑出来的那一家转写这段音频时,交给 worker 的(引擎, 语言)。"""
    seen: dict[str, str] = {}

    def fake(_wav, _python, engine_id, lang=""):
        seen.update(engine=engine_id, language=lang)
        return {"language": lang, "segments": []}

    monkeypatch.setattr(transcription, "transcribe_with_engine", fake)
    with SessionLocal() as db:
        transcription.transcriber(db, None, provider).transcribe(Path("x.wav"), language)
    return seen["engine"], seen["language"]


def test_there_is_exactly_one_funasr_entry() -> None:
    """一个引擎一个入口。两个 FunASR 会逼用户回答一个他不该被问的问题:该装哪套权重。"""
    funasr = [entry for entry in asr_models.CATALOG if entry.engine == "funasr"]
    assert [entry.id for entry in funasr] == ["funasr"]


def test_the_funasr_model_is_multilingual() -> None:
    assert transcription.FUNASR_MODEL == "iic/SenseVoiceSmall"


@pytest.mark.parametrize("language", ["", "zh", "en", "ja", "auto"])
def test_language_changes_neither_engine_nor_model(monkeypatch: pytest.MonkeyPatch, language: str) -> None:
    """**语言不再分流**:识别模型本来就支持 50+ 语种,把语言传给它即可,不必换模型、更不必换引擎。"""
    fresh_client()
    assert _heard(monkeypatch, language) == ("funasr", language)
    assert transcription.FUNASR_MODEL == "iic/SenseVoiceSmall"


def test_speaker_diarisation_survives_the_switch() -> None:
    """换识别模型不能把说话人分离弄丢 —— 它是独立阶段(按 VAD 切段后聚类),而转写面板的
    说话人标签、按人筛选全靠它。cam++ 的权重必须还在要下载的清单里。"""
    entry = next(e for e in asr_models.CATALOG if e.id == "funasr")
    names = [sub.cache_dir for sub in entry.sub_models]
    assert any("campplus" in name for name in names), names
    assert any("vad" in name for name in names), names


def test_a_named_engine_wins_over_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """工作流节点选的是这一次任务的执行方式,不应该被默认悄悄改回去。"""
    fresh_client()
    assert _heard(monkeypatch, "zh", "builtin:whisperx")[0] == "whisperx"


def test_without_a_runtime_the_next_engine_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    """没定默认时用第一个**装好了运行环境**的本机引擎 —— 只装了 WhisperX 的机器照样能转。"""
    fresh_client()
    monkeypatch.setattr(asr_models, "resolve_engine_python", lambda engine: "/fake/w" if engine == "whisperx" else None)
    assert _heard(monkeypatch, "")[0] == "whisperx"


def test_an_unknown_engine_is_rejected() -> None:
    fresh_client()
    with SessionLocal() as db, pytest.raises(transcription.ASRError) as raised:
        transcription.transcriber(db, None, "not-an-engine")
    assert raised.value.key == "asrErr_unsupportedEngine"


def test_the_workflow_node_lists_transcription_providers() -> None:
    """节点的引擎格是能力表的提供方(ADR 0032):本机引擎和插件并列,不再写死 auto / funasr / whisperx。"""
    from app.domain.workflows import NODE_TYPES

    engine = NODE_TYPES["transcribe_asset"]["config"]["engine"]
    assert engine["options_from"] == "providers.transcription"
    assert "default" not in engine and "options" not in engine


def test_warmup_and_transcribe_build_the_same_pipeline() -> None:
    """**预热要预热的,必须正是转写要用的那些。**

    这两处曾经各写一份 AutoModel 入参:目录换成 SenseVoice 之后,预热仍按老的中文四件套拉
    paraformer + punc —— 于是点「下载」下的是目录里根本没列的权重,进度停在 33/972 MB 不动,
    最后报失败。而且它下完也没用:转写要的 SenseVoice 一个字节都没拉。
    """
    import ast
    from pathlib import Path

    source = Path("app/ai/runtime/workers/asr.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    builders = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in ("run_funasr", "warmup_funasr")
    }
    assert set(builders) == {"run_funasr", "warmup_funasr"}
    for name, node in builders.items():
        calls = [
            call
            for call in ast.walk(node)
            if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "_funasr_kwargs"
        ]
        assert calls, f"{name} 没走共用的 _funasr_kwargs —— 又变成两份实现了"


def test_the_default_model_matches_the_backend() -> None:
    """worker 的默认模型和后端挑的必须是同一个 —— 不然"装了却用不上"会再来一次。"""
    from app.ai.runtime.workers import asr as asr_worker
    assert asr_worker.DEFAULT_FUNASR_MODEL == transcription.FUNASR_MODEL
