"""口播整理、视频译配两条模板:给人看的话跟着界面语言、说的是真话;目标语言放在明处、同语言译配花钱之前就拦。

- 英文界面建出来的项目叫「… · 智能整理」「… · 译配版」,完成通知、整理尺度也是中文 —— 这些默认值在建图时定语言;
- 译配通知说「配音轨整条删掉即可回到原样」,而只去掉人声时原片被静音、背景音另放一条轨,删掉配音轨回不去;
  改口型那一版的通知没提盖在最上面的那条口型轨;
- 整理模板把原片的时长套在降噪后的那份上;降噪声明自己只出音频,却是视频进视频出;
- 目标语言默认英文、藏在节点里;原文已经是目标语言时照样付费翻译、逐句配音;
- 两条译配模板一个叫「视频译配」一个叫「视频翻译」;改口型那条的对话模型前置条件少了「可换成 Google 翻译」。
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest

from app.domain.workflows import NODE_TYPES, WorkflowDomainError
from app.domain.workflows.templates import TEMPLATE_CATALOG, ModelChoice, transcript_video_cleanup_graph, translated_dub_graph

CHINESE = re.compile(r"[一-鿿]")


def _node(graph: dict, node_id: str) -> dict:
    return next(one for one in graph["nodes"] if one["id"] == node_id)


def test_英文界面建出来的项目名_通知_整理尺度都是英文() -> None:
    cleanup = transcript_video_cleanup_graph(chat=ModelChoice(), locale="en")
    dub = translated_dub_graph(voice_id="", lipsync=True, locale="en")
    shown = [
        _node(cleanup, "cleanup_project")["config"]["name"],
        _node(cleanup, "done_notice")["config"],
        _node(cleanup, "start")["config"]["params"]["cleanup_style"],
        _node(cleanup, "start")["config"]["params"]["filler_policy"],
        _node(dub, "dub_project")["config"]["name"],
        _node(dub, "done_notice")["config"],
    ]
    assert not CHINESE.search(json.dumps(shown, ensure_ascii=False)), shown
    zh = translated_dub_graph(voice_id="", locale="zh")
    assert _node(zh, "dub_project")["config"]["name"] == "{{source_video.name}} · 译配版"


def test_译配通知不说删掉配音轨就回到原样_改口型那一版说清口型轨() -> None:
    plain = json.dumps(_node(translated_dub_graph(voice_id="", locale="zh"), "done_notice"), ensure_ascii=False)
    assert "回到原样" not in plain and "original_audio_note" in plain
    synced = json.dumps(_node(translated_dub_graph(voice_id="", lipsync=True, locale="zh"), "done_notice"), ensure_ascii=False)
    assert "最上面一条视频轨" in synced


def test_降噪后的那份按它自己的长度放上时间线_降噪声明视频进视频出() -> None:
    placed = _node(transcript_video_cleanup_graph(chat=ModelChoice(), locale="zh"), "source_on_timeline")
    assert "end" not in placed["config"] and "end" not in placed.get("inputs", [])
    assert set(NODE_TYPES["denoise_audio"]["output_media"]["asset_id"]) == {"audio", "video"}


def test_目标语言在目录步骤里_译配名字统一_改口型的前置条件说可换成_Google_翻译() -> None:
    cards = {card["id"]: card for card in TEMPLATE_CATALOG}
    for template_id in ("translated_dub", "translated_dub_lipsync"):
        assert "选择目标语言" in cards[template_id]["stages"]["zh"], template_id
        assert cards[template_id]["name"]["zh"].startswith("视频译配 · "), template_id
    chat = next(one for one in cards["translated_dub_lipsync"]["requires"] if one["check"] == "chat_model")
    assert "Google" in chat["text"]["zh"] and "Google" in chat["text"]["en"]
    for template_id in ("translated_dub_lipsync", "full_video_generation"):
        assert "费" in cards[template_id]["summary"]["zh"] and "Cost" in cards[template_id]["summary"]["en"], template_id


@pytest.mark.parametrize(("source", "target", "same"), [
    ("en", "en", True), ("ja", "ja", True), ("zh", "zh-CN", True), ("zh-TW", "zh-TW", True),
    ("zh", "zh-TW", False), ("yue", "zh-CN", False), ("ja", "en", False), ("", "en", False),
])
def test_原文和目标语言是不是同一种(source: str, target: str, same: bool) -> None:
    from app.domain.translate import same_language

    assert same_language(source, target) is same


def test_原文已经是目标语言_翻译节点在花钱之前就拒(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.domain import translate as translate_domain
    from app.domain.workflows.executors.ai import translate_lines

    called: list = []
    monkeypatch.setattr(translate_domain, "translate_many", lambda *a, **k: called.append(a) or ["x"])
    scope = SimpleNamespace(workspace_id="", id="wf", name="译配")
    with pytest.raises(WorkflowDomainError) as refused:
        translate_lines(None, scope, {"texts": ["Hello"], "target_lang": "en", "source_lang": "en"})
    assert refused.value.key == "wfErr_translateSameLanguage" and called == []
    assert "source_lang" in _node(translated_dub_graph(voice_id=""), "translate_lines")["inputs"], \
        "模板把识别出的语言接到翻译节点上"
