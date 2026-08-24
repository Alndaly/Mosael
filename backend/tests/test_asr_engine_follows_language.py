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

import pytest

from app.ai.runtime import asr_models
from app.domain.voices import service


@pytest.fixture(autouse=True)
def _both_engines_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asr_models, "resolve_engine_python", lambda engine: f"/fake/{engine}")
    monkeypatch.setattr(service.settings, "asr_provider", "auto")


def test_there_is_exactly_one_funasr_entry() -> None:
    """一个引擎一个入口。两个 FunASR 会逼用户回答一个他不该被问的问题:该装哪套权重。"""
    funasr = [entry for entry in asr_models.CATALOG if entry.engine == "funasr"]
    assert [entry.id for entry in funasr] == ["funasr"]


def test_the_funasr_model_is_multilingual() -> None:
    assert service.FUNASR_MODEL == "iic/SenseVoiceSmall"


@pytest.mark.parametrize("language", ["", "zh", "en", "ja", "auto"])
def test_language_changes_neither_engine_nor_model(language: str) -> None:
    """**语言不再分流**:识别模型本来就支持 50+ 语种,把语言传给它即可,不必换模型、更不必换引擎。"""
    assert service.resolve_asr_runtime(language)[1] == "funasr"
    assert service.FUNASR_MODEL == "iic/SenseVoiceSmall"


def test_speaker_diarisation_survives_the_switch() -> None:
    """换识别模型不能把说话人分离弄丢 —— 它是独立阶段(按 VAD 切段后聚类),而转写面板的
    说话人标签、按人筛选全靠它。cam++ 的权重必须还在要下载的清单里。"""
    entry = next(e for e in asr_models.CATALOG if e.id == "funasr")
    names = [sub.cache_dir for sub in entry.sub_models]
    assert any("campplus" in name for name in names), names
    assert any("vad" in name for name in names), names


def test_an_explicit_setting_still_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service.settings, "asr_provider", "whisperx")
    assert service.resolve_asr_runtime("zh")[1] == "whisperx"


def test_warmup_and_transcribe_build_the_same_pipeline() -> None:
    """**预热要预热的,必须正是转写要用的那些。**

    这两处曾经各写一份 AutoModel 入参:目录换成 SenseVoice 之后,预热仍按老的中文四件套拉
    paraformer + punc —— 于是点「下载」下的是目录里根本没列的权重,进度停在 33/972 MB 不动,
    最后报失败。而且它下完也没用:转写要的 SenseVoice 一个字节都没拉。
    """
    import ast
    from pathlib import Path

    source = Path("app/ai/runtime/asr_worker.py").read_text(encoding="utf-8")
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
    from app.ai.runtime import asr_worker

    assert asr_worker.DEFAULT_FUNASR_MODEL == service.FUNASR_MODEL
