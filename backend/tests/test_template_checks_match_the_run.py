"""模板前置检查说「齐了」,真跑的时候就用得上 —— 判据和运行时同一套(requirement_statuses 的承诺)。

此前几处各说各的:
- 插件:只要有一家配好就算齐;而转写、人声分离都**不许自动用插件**(capabilities.choose),真跑时照样没得用;
- 人声分离:运行时按「没有人」去挑(`available(db, None)`),没有人就没有插件 —— 定了分离插件的人被说成没有分离能力;
- 克隆音色:只看有没有音色行,不看克隆引擎跑不跑得起来;数字人用的那把还得声明过是谁的。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.db.models import User, Voice
from app.domain.workflows.templates import built_in_template_graph, requirement_statuses
from tests.test_audio_plugins import _setup
from tests.util import fresh_client, make_voice


def _statuses(me: str, workspace: str) -> dict[str, str]:
    with SessionLocal() as db:
        return requirement_statuses(db, user_id=me, workspace_id=workspace)


@pytest.fixture()
def engines_known_missing(monkeypatch: pytest.MonkeyPatch):
    """本机的转写、分离引擎都测过了、都跑不起来 —— 能不能用全看插件。"""
    from app.ai.runtime import asr_models, separation_models

    monkeypatch.setattr(asr_models, "runtime_status", lambda engine: (False, True))
    monkeypatch.setattr(separation_models, "runtime_status", lambda engine: (False, True))


def test_分离插件配好了但没定成默认_真跑时用不上_检查也说缺(tmp_path, engines_known_missing) -> None:
    from app.domain import audio_capabilities, capabilities

    _client, ws, me, plugin, _asset = _setup(tmp_path)
    assert _statuses(me, ws)["separation_engine"] == "missing", "分离不许自动用插件(auto_single=False)"
    with SessionLocal() as db:
        capabilities.set_default(db, me, audio_capabilities.SEPARATION, plugin)
        db.commit()
    assert _statuses(me, ws)["separation_engine"] == "met", "定成默认之后真跑用的就是它"


def test_定了分离插件的人_配音前的预检认得他的插件(tmp_path, engines_known_missing) -> None:
    """配音排任务前的预检此前按「没有人」挑提供方,插件永远不在候选里。"""
    from app.domain import audio_capabilities, capabilities
    from app.domain.voices.original_audio import OriginalAudioError, ensure_original_audio_mode

    _client, _ws, me, plugin, _asset = _setup(tmp_path)
    with pytest.raises(OriginalAudioError):
        ensure_original_audio_mode("separate", owner_user_id=me)
    with SessionLocal() as db:
        capabilities.set_default(db, me, audio_capabilities.SEPARATION, plugin)
        db.commit()
    ensure_original_audio_mode("separate", owner_user_id=me)


def test_克隆音色要克隆引擎跑得起来_数字人用的还要声明过是谁的(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ai.runtime import tts_models

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        me = db.query(User).order_by(User.created_at).first().id
    voice = make_voice(ws, "未声明的嗓子")

    monkeypatch.setattr(tts_models, "runtime_status", lambda engine: (False, True))
    assert _statuses(me, ws)["cloned_voice"] == "missing", "有音色、克隆引擎跑不起来:模板里的配音节点照样失败"
    monkeypatch.setattr(tts_models, "runtime_status", lambda engine: (False, False))
    assert _statuses(me, ws)["cloned_voice"] == "unknown", "还没测出来就说不知道"
    monkeypatch.setattr(tts_models, "runtime_status", lambda engine: (True, True))
    statuses = _statuses(me, ws)
    assert statuses["cloned_voice"] == "met"
    assert statuses["digital_human_voice"] == "missing", "未声明的克隆音色不能交给数字人"

    declared = make_voice(ws, "声明过的嗓子")
    with SessionLocal() as db:
        db.get(Voice, declared).consent_kind = "self"
        db.commit()
        assert requirement_statuses(db, user_id=me, workspace_id=ws)["digital_human_voice"] == "met"
        graph = built_in_template_graph(db, "translated_dub_lipsync", user_id=me, workspace_id=ws, locale="zh")
        dubbing = next(one for one in graph["nodes"] if one["id"] == "dubbing")
        assert dubbing["config"]["voice"] == declared, "改口型那一版只预填声明过的嗓子,不是最早建的那把"
        plain = built_in_template_graph(db, "translated_dub", user_id=me, workspace_id=ws, locale="zh")
        assert next(one for one in plain["nodes"] if one["id"] == "dubbing")["config"]["voice"] == voice


def test_译配模板的嗓子那一条有检查键() -> None:
    """配音节点的引擎写死 builtin:clone,前置条件却是一句查不了的话 —— 界面说「运行时选择」,跑到配音才失败。"""
    from app.domain.workflows.templates import TEMPLATE_CATALOG

    cards = {card["id"]: card for card in TEMPLATE_CATALOG}
    assert "cloned_voice" in {one["check"] for one in cards["translated_dub"]["requires"]}
    assert "digital_human_voice" in {one["check"] for one in cards["translated_dub_lipsync"]["requires"]}


def test_口播模板_逐段说话用分段时挑定的模型_嗓子要声明过是谁的() -> None:
    """分段按说话照片模型的音频上限切;下游「让它说话」留空模型会再挑一次,可能挑到上限更短的另一个。
    嗓子要交给数字人,前置条件查的是声明过的克隆音色,不只是「有一把克隆音色」。"""
    from app.domain.workflows.templates import TEMPLATE_CATALOG
    from app.domain.workflows.templates_business import talking_script_video_graph

    graph = talking_script_video_graph(voice_id="")
    loop = next(one for one in graph["nodes"] if one["id"] == "speak_segments")
    speak = next(one for one in loop["config"]["body"]["nodes"] if one["id"] == "speak")
    assert speak["config"]["model"] == "{{loop.item.model}}"
    card = next(one for one in TEMPLATE_CATALOG if one["id"] == "talking_script_video")
    checks = {one["check"] for one in card["requires"]}
    assert "digital_human_voice" in checks and "cloned_voice" not in checks
