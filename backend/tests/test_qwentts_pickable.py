"""「Qwen3-TTS 装好了,可我切不到它」—— 后端这一侧钉的是**它到底在哪儿能选**,以及选它时不该发生什么。

维护者在「管理 → 引擎 → 声音克隆」里把 Qwen3-TTS 装好(那一行写着「✓ 已安装」),抬头却只看到
一个「引擎」下拉,里面是 F5-TTS / Fish Speech —— 于是结论是"装了却切不过去"。

那个下拉存的是**默认克隆引擎**(`TtsConfigUpdate.engine` 只收 `f5-tts|fish-speech`)。Qwen3-TTS
是**预置音色**引擎、不克隆,它本来就不属于那里:塞进去既会让那一节的话撒谎,保存也会 422。
用户真正要切的地方是**配音 / 合成的引擎选择器**(剪辑台「配音」、创作页「语音」),那里本来就有它
(`GET /api/tts/engines` 的 `builtin:qwentts`);那一节现在按能力分组、并在 Qwen 那行指路
(见 VoiceCloneSection 与文案表的 `voiceClonePickElsewhere`)。

这份测试钉住指路脚下那层事实,免得以后有人"顺手把 Qwen 塞进克隆下拉"或"合成时给预置音色引擎
带一份参考音频":

① 目录里 Qwen 那条自报的能力与它自己的说明一致:不克隆、不要音色 id、不吃语速、9 个预置音色;
② 那个「默认克隆引擎」的下拉/接口仍然只收克隆引擎(克隆这件事不被搅浑);
③ 真按那条路合成一次:请求是 `builtin:qwentts` + 预置音色,不带参考音频。
"""
from __future__ import annotations

import io
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ai.runtime import qwen_models
from app.core.messages.workflows import MESSAGES
from app.domain.voices import engine_catalog, voices
from app.domain.voices.speech import QWEN_ENGINE
from tests.util import fresh_client, wait_status


def _wave_bytes(seconds: float = 0.1, sr: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes(b"\x00\x00" * int(sr * seconds))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# ① 它自报的能力 = 它说明里写的那几件事
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("locale", ["zh-CN", "en-US"])
def test_its_capabilities_match_what_its_description_says(
    locale: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """引擎目录里这一条要说"不克隆",而且能力字段也得是同一句话。

    界面据此决定:列不列它(要)、要不要让用户手打音色 id(不要)、摆不摆语速旋钮(不摆)。
    这几项一旦和说明对不上,用户看到的就是一个和他读到的不一样的引擎。
    """
    client = fresh_client()
    engines = {
        row["id"]: row
        for row in client.get("/api/tts/engines", headers={"Accept-Language": locale}).json()
    }
    row = engines[QWEN_ENGINE]

    # 9 个预置音色:是模型自带的,不是谁的嗓子,也不用用户手打 id。
    assert row["needs_key"] is False
    assert row["needs_voice_id"] is False
    assert row["voices"] == [speaker.id for speaker in qwen_models.MODEL.speakers]
    # 它不是能复刻嗓子到远端的那一类,更不是本地克隆。
    assert row["clones_voices"] is False
    # 它的 API 没有语速参数 —— 摆一个拨不动的旋钮比不摆更糟。
    assert row["supports_speed"] is False

    # 装好之后挑引擎的那一刻读到的就是这句 note:讲预置音色,不讲克隆。
    monkeypatch.setattr(voices.tts_models, "runtime_status", lambda engine_id: (True, True))
    monkeypatch.setattr(voices.tts_models, "is_installed", lambda engine_id: True)
    installed = next(one for one in engine_catalog.describe_engines(None) if one["id"] == QWEN_ENGINE)
    assert installed["ready"] is True
    assert installed["note"] == "ttsProviderNote_qwenReady"
    note = MESSAGES["ttsProviderNote_qwenReady"]
    if locale == "zh-CN":
        assert "预置音色" in note["zh"]
        assert "参考音频" in note["zh"]
    else:
        assert "preset voices" in note["en"]
        assert "reference audio" in note["en"]

    # 安装那一行的说明(管理页那一行)同样不能声称能克隆。
    models = {
        one["id"]: one
        for one in client.get("/api/tts/models", headers={"Accept-Language": locale}).json()
    }
    detail = models[qwen_models.ENGINE_ID]["detail"]
    if locale == "zh-CN":
        assert "不克隆" in detail
        assert "参考音频" in detail
    else:
        lowered = detail.lower()
        assert "no cloning" in lowered
        assert "reference audio" in lowered


def test_the_clone_entry_in_the_catalog_is_a_different_thing() -> None:
    """「本地克隆」是目录里**另一条**;Qwen 与它并列,不是它的另一种配置。"""
    rows = {str(row["id"]): row for row in engine_catalog.describe_engines(None)}
    assert rows["builtin:clone"]["id"] != rows[QWEN_ENGINE]["id"]
    assert rows[QWEN_ENGINE]["clones_voices"] is False


# ---------------------------------------------------------------------------
# ② 「默认克隆引擎」这一格的语义不变
# ---------------------------------------------------------------------------


def test_the_clone_engine_setting_still_refuses_a_preset_voice_engine() -> None:
    """它存的是克隆引擎 —— 收下 qwen-tts 就等于让「声音克隆」这句话撒谎。

    这一条也解释了为什么不能"把 Qwen 塞进那个下拉":下拉与这个接口是同一份配置。
    """
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    before = client.get("/api/settings/tts").json()["engine"]

    res = client.put(
        "/api/settings/tts",
        json={"engine": qwen_models.ENGINE_ID, "python_path": "", "fish_repo_dir": "", "fish_model_dir": ""},
    )
    assert res.status_code == 422, res.text
    # 没写进去:克隆引擎仍是 f5-tts。
    assert client.get("/api/settings/tts").json()["engine"] == before


# ---------------------------------------------------------------------------
# ③ 真合成一次:qwentts + 预置音色,不带参考音频
# ---------------------------------------------------------------------------


def test_synthesis_through_the_api_sends_no_reference_audio(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """选 Qwen + 预置音色 vivian,请求里就是 `builtin:qwentts` + `engine_voice=vivian`。

    worker 那一侧收到的只有文本、发音人和语言 —— **没有参考音频**(那是克隆那条路的参数)。
    """
    sent: dict[str, object] = {}

    def request(engine, python, payload, **_kwargs):
        sent.update(payload)
        Path(payload["output_path"]).write_bytes(_wave_bytes())
        return {"engine": engine, "output": payload["output_path"]}

    monkeypatch.setattr(voices.tts_models, "resolve_engine_python", lambda engine_id: "/usr/bin/python3")
    monkeypatch.setattr(voices.tts_models, "is_installed", lambda engine_id: True)
    monkeypatch.setattr(voices.tts_daemon, "pool", lambda: SimpleNamespace(request=request))

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    res = client.post(
        "/api/tts/synthesize",
        json={
            "workspace_id": workspace,
            "text": "你好,这是一次真实合成。",
            "voice": {"engine": QWEN_ENGINE, "voice": "vivian"},
        },
    )
    assert res.status_code == 200, res.text
    job = res.json()
    #: 念的是引擎自己的预置音色,不是配音库里的克隆嗓子:这条不带参考音频。
    assert job["payload"]["voice"] == {"engine": QWEN_ENGINE, "voice": "vivian"}

    assert wait_status(client, job["id"], timeout=30) == "succeeded"
    assert client.get(f"/api/jobs/{job['id']}").json()["result"]["engine"] == QWEN_ENGINE

    # worker 那条请求:引擎是运行时的 qwen-tts,发音人是 vivian,没有任何参考音频字段。
    assert sent["engine"] == qwen_models.ENGINE_ID
    assert sent["speaker"] == "vivian"
    assert sent["language"] == "Auto"
    assert "reference_audio" not in sent and "reference_text" not in sent and "voice_id" not in sent
