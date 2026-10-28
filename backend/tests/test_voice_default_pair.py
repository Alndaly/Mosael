"""配音的部署默认是**一对**(引擎 + 音色),不是一次单选的「用哪一家」。

维护者原话:「**配音应该也有默认机制**」。此前 `Capability.defaultable=False`,理由是「引擎和音色是成对选的
(克隆音色的 id 换到 Edge 上就是错的),每个入口都点名」—— 成对是对的,「因此不能有默认」是错的:默认也可以
是一对。所以这里存的是一把嗓子(`VoiceRef`,ADR 0087:引擎 + 音色,绑模型的连模型),设的时候整把一起校验。

**两层,谁也不是谁的替代(和转写 / 降噪同一条规则):**

- **部署默认**(本模块,`VoiceDefaultConfig`):这台机器默认那一对;只有部署管理员能改,和装引擎同一道门。
- **按人选的**(设置 → 能力提供方 → 配音):某个人自己定过的那一台引擎。它是**覆盖**,部署默认只补
  「他没选过」的那一半;这个人的引擎和部署的引擎不是同一家时,部署的音色不硬套过去(给空,交给现有的
  「必须点名音色」)。

有效值**只有一处**算:`domain/voices/defaults.resolve_voice_default()`。所有念字的入口都经过
`engine_catalog.voice_for_synthesis` —— 没点名时它先问那一处,所以设置页写着的和真念出来的永远是
同一个答案。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.db import SessionLocal
from app.db.models import User
from tests.util import fresh_client, second_client

EDGE = "builtin:edge"
EDGE_VOICE = "zh-CN-XiaoxiaoNeural"
EDGE_VOICE_2 = "zh-CN-YunxiNeural"
OPENAI = "builtin:openai"
OPENAI_VOICE = "alloy"
VOLCANO = "builtin:volcano"
VOLCANO_VOICE = "zh_female_cancan_mars_bigtts"


def _client():
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    return client


def _me() -> str:
    with SessionLocal() as db:
        return db.query(User).filter(User.username == "tester").one().id


def _set(client, engine: str, voice: str):
    """设这台机器的默认那一把嗓子(引擎 + 引擎音色);两格都空 = 清掉。"""
    chosen = {"engine": engine, "voice": voice} if engine or voice else None
    return client.put("/api/settings/voice-default", json={"voice": chosen})


def _engines(client) -> list[dict]:
    reply = client.get("/api/tts/engines")
    assert reply.status_code == 200, reply.text
    return reply.json()


def _voices(client, engine: str) -> list[dict]:
    reply = client.get(f"/api/tts/voices?engine={engine}")
    assert reply.status_code == 200, reply.text
    return reply.json()


def _default_engine(client) -> str:
    return next((row["id"] for row in _engines(client) if row.get("is_default")), "")


def _default_voice(client, engine: str) -> str:
    return next((row["id"] for row in _voices(client, engine) if row.get("is_default")), "")


def _choose_personal(client, provider_id: str):
    """这个人在「设置 → 能力提供方 → 配音」里选的那一台引擎(个人覆盖)。"""
    reply = client.put("/api/settings/capabilities/speech", json={"provider_id": provider_id})
    assert reply.status_code == 200, reply.text
    return reply.json()


def _resolve() -> tuple[str, str]:
    """唯一那个解析点的答案:(引擎, 音色);没有默认是 `("", "")`。"""
    from app.domain.voices.defaults import resolve_voice_default

    with SessionLocal() as db:
        found = resolve_voice_default(db, _me())
    return (found.engine, found.voice) if found is not None else ("", "")


@pytest.fixture
def remote_engines_ready(monkeypatch):
    """让需要钥匙的两家(OpenAI、火山)看起来已经配好。

    判据本身是「这个人 / 这台机器上那条连接在不在」(见 speech.engine_ready);这里只回答那一个问题,
    不碰别的实现 —— 测试要的是「两家都能选」,不是替实现编一个连接出来。
    """
    from app.domain.voices import speech

    monkeypatch.setattr(speech, "engine_ready", lambda *args, **kwargs: True)


# ---------------------------------------------------------------------------
# ① 能设一对默认;音色不匹配 / 未安装 / 不认识的引擎 / 非管理员各走各的
# ---------------------------------------------------------------------------
def test_能设一对默认_两个候选接口都标出来() -> None:
    """默认就是那一对:引擎在 /tts/engines 上标 is_default,音色在 /tts/voices 上标 is_default。

    不另开一个「当前默认」的 GET —— 同一个答案只有一处来源(和降噪、转写同一条)。
    """
    client = _client()

    reply = _set(client, EDGE, EDGE_VOICE_2)

    assert reply.status_code == 200, reply.text
    assert reply.json()["voice"] == {"engine": EDGE, "voice": EDGE_VOICE_2, "cloned_voice": "", "model": "",
                                     "connection": "", "extra": {}}
    assert _default_engine(client) == EDGE
    assert _default_voice(client, EDGE) == EDGE_VOICE_2
    #: 别的引擎、别的音色都不该被标成默认。
    assert [row["id"] for row in _engines(client) if row.get("is_default")] == [EDGE]
    assert [row["id"] for row in _voices(client, EDGE) if row.get("is_default")] == [EDGE_VOICE_2]


def test_清掉默认() -> None:
    """两格都空 = 没设过:行为和这一格出现之前完全一样(每个入口各自点名)。"""
    client = _client()
    assert _set(client, EDGE, EDGE_VOICE).status_code == 200

    reply = _set(client, "", "")

    assert reply.status_code == 200, reply.text
    assert _default_engine(client) == ""
    assert _default_voice(client, EDGE) == ""


def test_音色不属于这个引擎_409且说人话() -> None:
    """成对选的另一半:火山的音色拿到 Edge 上就是错的,设的时候就说,不等下一次合成。"""
    client = _client()

    reply = _set(client, EDGE, VOLCANO_VOICE)

    assert reply.status_code == 409, reply.text
    detail = reply.json()["detail"]
    assert "音色" in detail, detail
    assert EDGE in detail or "Edge" in detail, detail
    assert VOLCANO_VOICE in detail, detail
    assert _default_engine(client) == ""


def test_未安装的引擎_409() -> None:
    """OpenAI 还没配连接时设成默认,「默认」就是一句空话 —— 下一次合成照样先失败。"""
    client = _client()

    reply = _set(client, OPENAI, OPENAI_VOICE)

    assert reply.status_code == 409, reply.text
    #: 人话:说清它还缺什么(而不是一句 Not Found)。
    assert "用不了" in reply.json()["detail"] or "连接" in reply.json()["detail"], reply.json()["detail"]
    assert _default_engine(client) == ""


def test_不认识的引擎_404() -> None:
    client = _client()

    reply = _set(client, "builtin:no-such-engine", "whatever")

    assert reply.status_code == 404, reply.text
    assert "配音引擎" in reply.json()["detail"], reply.json()["detail"]


def test_只有部署管理员能改默认() -> None:
    """默认是**这台机器**的设定(和装引擎同一类),所以只给部署管理员;别人的候选列表照看。"""
    _client()
    member = second_client("member")

    assert _set(member, EDGE, EDGE_VOICE).status_code == 403
    assert member.get("/api/tts/engines").status_code == 200


# ---------------------------------------------------------------------------
# ② 一处解析,优先级:入口点名 > 按人选的 > 部署默认 > 空
# ---------------------------------------------------------------------------
def test_入口点名的那一把压过所有默认(remote_engines_ready) -> None:
    from app.domain.voices.engine_catalog import voice_for_synthesis
    from app.domain.voices.voice_ref import VoiceRef

    client = _client()
    assert _set(client, OPENAI, OPENAI_VOICE).status_code == 200
    _choose_personal(client, VOLCANO)

    named = VoiceRef(EDGE, voice=EDGE_VOICE)
    with SessionLocal() as db:
        assert voice_for_synthesis(db, named, user_id=_me(), workspace_id="") == named


def test_按人选的引擎压过部署默认_音色不硬套到另一家(remote_engines_ready) -> None:
    """他在能力提供方里选的是一家引擎;部署默认的嗓子属于**另一家**,不能拿到这一家上去念 —— 没有一把能念的嗓子,
    交给「必须点名」(不是悄悄用部署那一家)。"""
    client = _client()
    assert _set(client, OPENAI, OPENAI_VOICE).status_code == 200
    _choose_personal(client, VOLCANO)

    assert _resolve() == ("", "")


def test_按人选的引擎和部署默认是同一家_音色跟着部署那一对(remote_engines_ready) -> None:
    client = _client()
    assert _set(client, OPENAI, OPENAI_VOICE).status_code == 200
    _choose_personal(client, OPENAI)

    assert _resolve() == (OPENAI, OPENAI_VOICE)


def test_没人在能力提供方里选过_用部署默认那一对(remote_engines_ready) -> None:
    client = _client()
    assert _set(client, OPENAI, OPENAI_VOICE).status_code == 200

    assert _resolve() == (OPENAI, OPENAI_VOICE)


def test_什么都没设_解析给空_交给现有的必须点名() -> None:
    _client()

    assert _resolve() == ("", "")


# ---------------------------------------------------------------------------
# ③ 「点名」那条路行为不变:没有默认时仍然要求点名
# ---------------------------------------------------------------------------
def test_没有默认时点名的入口照旧要求点名() -> None:
    """`pick_speech`(智能体开卡)和 `voice_for_synthesis`(念字的执行入口)在没有默认时给的是同一句话。"""
    from app.domain.voices.engine_catalog import pick_speech, voice_for_synthesis
    from app.domain.voices.speech import SpeechProviderUnavailable
    from app.domain.voices.errors import VoiceError

    _client()
    with SessionLocal() as db, pytest.raises(SpeechProviderUnavailable):
        pick_speech(db, engine="", voice="", user_id=_me(), workspace_id="")
    with SessionLocal() as db, pytest.raises(VoiceError, match="音色"):
        voice_for_synthesis(db, None, user_id=_me(), workspace_id="")


def test_有默认时没点名的入口用默认那一把() -> None:
    """默认替掉的正是「没点名、于是要求点名」这一步 —— 点名了的不被默认改写。"""
    from app.domain.voices.engine_catalog import pick_speech, voice_for_synthesis
    from app.domain.voices.voice_ref import VoiceRef

    client = _client()
    assert _set(client, EDGE, EDGE_VOICE).status_code == 200

    with SessionLocal() as db:
        assert pick_speech(db, engine="", voice="", user_id=_me(), workspace_id="") == (EDGE, EDGE_VOICE)
    with SessionLocal() as db:
        assert voice_for_synthesis(db, None, user_id=_me(), workspace_id="") == VoiceRef(EDGE, voice=EDGE_VOICE)

    #: 点名了另一把:默认一个字都不改。
    with SessionLocal() as db:
        named = voice_for_synthesis(db, VoiceRef(EDGE, voice=EDGE_VOICE_2), user_id=_me(), workspace_id="")
    assert named == VoiceRef(EDGE, voice=EDGE_VOICE_2)


# ---------------------------------------------------------------------------
# ④ 一处解析:有效值只能由一个函数决定
# ---------------------------------------------------------------------------
def test_配音默认只有一处解析() -> None:
    """`VoiceDefaultConfig` 只在 domain/voices/defaults 里读写;`resolve_voice_default` 只在
    `voice_for_synthesis` 里调一次。

    任何一个入口自己再算一遍,迟早给出两个答案 —— 设置页写着一对、念出来的是另一对,
    而用户看到的是「设了却没生效」。
    """
    app_root = Path(__file__).resolve().parents[1] / "app"
    readers = sorted(
        str(path.relative_to(app_root)) for path in app_root.rglob("*.py") if "VoiceDefaultConfig" in path.read_text()
    )
    #: ownership 只是归属地图上的一笔(它不读值),另外三处是模型定义、模型出口和那一个解析点。
    assert readers == [
        "db/model_slices/runtime_config.py",
        "db/models.py",
        "domain/ownership.py",
        "domain/voices/defaults.py",
    ], readers

    catalog = (app_root / "domain/voices/engine_catalog.py").read_text()
    assert catalog.count("resolve_voice_default(") == 1
