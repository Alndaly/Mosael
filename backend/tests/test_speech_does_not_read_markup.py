"""念出来的文字**是说话的文字**,不是 markdown 源码。

维护者原话:「现在**所有地方**的语音为何会将**部分符号念出来** —— 比如 `*` 会念成「星号」」。

根子在**送进合成的那一段文本**:对话朗读、免提、笔记朗读、配音、画板音、工作流合成词、字幕逐句配音
……每个入口都把「屏幕上那一份 markdown」原样交给了引擎,而引擎不认识 markdown —— 它只看见一串标点,
于是 `*` 念「星号」、`#` 念「井号」、`|` 念「竖线」、URL 逐字符念。

修在一个地方(域里唯一的出口),而不是在每个调用点各加一遍:这一条钉的是
- `speakable_text` 本身:去掉标记、**字还在**、该念的照旧;
- 它是**怎么进来的**:两扇门(start_synthesis / speak_to_file)之外没有第三条路能到引擎;
- 每个入口(对话 / 试听 / 朗读 / 配音任务 / 克隆)送到引擎的文本确实过了一遍。
"""

from __future__ import annotations

import io
import wave
from pathlib import Path

import pytest

from app.ai.runtime import tts_models
from app.domain.voices import voices
from app.domain.voices import errors
from app.domain.voices.speakable import speakable_text
from app.domain.voices.voice_ref import VoiceRef
from tests.util import fresh_client

#: 一段真会出现在助手回复里的 markdown:标题、粗体、斜体、删除线、列表、表格、省略号、破折号、URL、
#: 行内代码、代码围栏。**数字 / 单位 / 百分号 / 中英文标点必须原样留着。**
MARKDOWN = (
    "# 标题\n"
    "**粗体** 和 *星号* 与 ~~删除~~、`代码`,再看 [文档](https://example.com/doc)。\n"
    "- 列表一\n"
    "- 列表二\n"
    "| a | b |\n"
    "|---|---|\n"
    "| 1 | 2 |\n"
    "等了 3.5 秒…… 温度 20°C,完成 50% —— 看 https://example.com/x?y=1 这份。\n"
)

MARKERS = set("*#`~|…—–")


def test_去掉标记_字还在_该念的照旧() -> None:
    spoken = speakable_text(MARKDOWN)

    assert not (MARKERS & set(spoken)), f"还有标记会被念出来:{sorted(MARKERS & set(spoken))}"
    assert "http" not in spoken and "example.com" not in spoken, f"URL 被逐字符念:{spoken}"
    for word in ("标题", "粗体", "星号", "删除", "代码", "文档", "列表一", "列表二", "这份"):
        assert word in spoken, f"字被一起删掉了:{word} / {spoken}"
    #: 表格的竖线去掉,**格子里的字**还在。
    assert "a" in spoken and "b" in spoken and "1" in spoken and "2" in spoken, spoken
    #: 该念的照旧。
    for kept in ("3.5", "20°C", "50%", ",", "。"):
        assert kept in spoken, f"该念的也被洗掉了:{kept} / {spoken}"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("**粗体**", "粗体"),
        ("*星号*", "星号"),
        ("__粗体__", "粗体"),
        ("~~删除~~", "删除"),
        ("# 标题", "标题"),
        ("### 三级标题", "三级标题"),
        ("> 引用", "引用"),
        ("`代码`", "代码"),
        ("```python\nprint(1)\n```", "print(1)"),
        ("[文档](https://example.com)", "文档"),
        ("等等……", "等等"),
        ("一 — 二", None),
        ("50% 的 3.5 秒", "50% 的 3.5 秒"),
        ("", ""),
        ("   ", ""),
        ("***", ""),
        ("| a | b |", None),
    ],
)
def test_一条一条地看(source: str, expected: str | None) -> None:
    spoken = speakable_text(source)
    assert not (MARKERS & set(spoken)), spoken
    if expected is not None:
        assert spoken == expected


def test_列表和表头的字都还在() -> None:
    spoken = speakable_text("- 列表一\n- 列表二\n| 名字 | 数量 |\n|---|---|\n| 苹果 | 3 |")
    assert "列表一" in spoken and "列表二" in spoken
    assert "名字" in spoken and "数量" in spoken and "苹果" in spoken and "3" in spoken


def test_洗第二遍不会继续变() -> None:
    once = speakable_text(MARKDOWN)
    assert speakable_text(once) == once, "两层都过一遍的时候,第二遍必须是无操作"


# --------------------------------------------------------------------------- 入口:两扇门


def _a_voice(client) -> str:
    buf = io.BytesIO()
    with wave.open(buf, "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 16000 * 8)
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    return client.post(
        "/api/voices/upload",
        data={"workspace_id": workspace_id, "name": "小明", "reference_text": "你好", "consent_kind": "self"},
        files={"file": ("ref.wav", buf.getvalue(), "audio/wav")},
    ).json()["id"]


def _workspace_of(voice_id: str) -> str:
    from app.core.db import SessionLocal
    from app.db.models import Voice

    with SessionLocal() as db:
        return db.get(Voice, voice_id).workspace_id


def _edge_voice(client) -> None:
    reply = client.put(
        "/api/settings/agent-voice",
        json={"voice": {"engine": "builtin:edge", "voice": "zh-CN-XiaoxiaoNeural"}, "speed": 1.0, "enabled": True},
    )
    assert reply.status_code == 200, reply.text


@pytest.fixture
def spoken(monkeypatch) -> list[str]:
    """把 Edge 的合成换掉,只记下**真正交给引擎的那段文字** —— 不真合成,不出网。"""
    import edge_tts

    calls: list[str] = []

    class _Communicate:
        def __init__(self, text: str, voice: str = "", rate: str = "") -> None:
            calls.append(text)

        async def save(self, path: str) -> None:
            Path(path).write_bytes(b"ID3fake")

    monkeypatch.setattr(edge_tts, "Communicate", _Communicate)
    return calls


def test_对话里念一句_送去合成的文本没有标记(monkeypatch, spoken) -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    _edge_voice(client)

    reply = client.post("/api/agent/speech", json={"text": "**粗体** 和 *星号*", "workspace_id": workspace["id"]})

    assert reply.status_code == 200, reply.text
    assert [one for one in spoken if "*" in one] == [], spoken
    assert spoken and spoken[-1] == "粗体 和 星号", spoken


@pytest.mark.parametrize("path", ["/api/agent/speech", "/api/agent/speech/preview", "/api/agent/speech/read"])
def test_对话音色的三个入口_送去合成的文本都没有标记(monkeypatch, spoken, path: str) -> None:
    """同一个「对话音色」的三个入口(念回复 / 试听 / 朗读)**走同一条合成路**,谁也别想绕过清洗。"""
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    _edge_voice(client)

    reply = client.post(path, json={"text": "**粗体** *星号* # 标题", "workspace_id": workspace["id"]})

    assert reply.status_code == 200, (path, reply.text)
    assert spoken[-1] == "粗体 星号 标题", (path, spoken)


def test_试听也是同一条路_标记不会念出来(spoken) -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()

    heard = client.post(
        "/api/tts/preview",
        json={
            "workspace_id": workspace["id"],
            "voice": {"engine": "builtin:edge", "voice": "zh-CN-XiaoxiaoNeural"},
            "text": "# 标题\n| a | b |",
        },
    )

    assert heard.status_code == 200, heard.text
    assert spoken == ["标题\na b"], spoken
    assert not (MARKERS & set(spoken[0])), spoken


def test_朗读笔记选中段_送去合成的文本没有标记(monkeypatch, spoken) -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    _edge_voice(client)

    reply = client.post(
        "/api/agent/speech/read",
        json={"text": "看 [文档](https://example.com/doc) 这一节", "workspace_id": workspace["id"]},
    )

    assert reply.status_code == 200, reply.text
    assert spoken[-1] == "看 文档 这一节", spoken


def test_配音任务_送去合成的文本没有标记(monkeypatch, spoken) -> None:
    from app.domain.jobs import wait_for_idle_jobs

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()

    job = client.post(
        "/api/tts/synthesize",
        json={
            "workspace_id": workspace["id"],
            "voice": {"engine": "builtin:edge", "voice": "zh-CN-XiaoxiaoNeural"},
            "text": "## 标题\n- 列表一\n| a | b |",
        },
    )
    assert job.status_code == 200, job.text
    assert wait_for_idle_jobs(timeout=30)

    assert spoken, "配音任务没把文本交给引擎"
    assert spoken[-1] == "标题\n列表一\na b", spoken
    assert not (MARKERS & set(spoken[-1])), spoken


def test_克隆配音_送给worker的文本没有标记(monkeypatch) -> None:
    from app.ai.runtime import tts_daemon
    from app.domain.jobs import wait_for_idle_jobs

    monkeypatch.setattr(tts_models, "resolve_engine_python", lambda engine_id: "/usr/bin/python3")
    monkeypatch.setattr(tts_models, "is_installed", lambda engine_id: True)

    sent: list[str] = []

    class _Pool:
        def request(self, engine, python, payload, **kwargs):
            sent.append(payload.get("text", ""))
            raise RuntimeError("到此为止 —— 这条测试只看请求里的文字")

    monkeypatch.setattr(tts_daemon, "pool", lambda: _Pool())
    client = fresh_client()
    voice_id = _a_voice(client)

    reply = client.post("/api/tts/synthesize", json={
        "workspace_id": _workspace_of(voice_id), "text": "**粗体** # 标题 | a | b |",
        "voice": {"engine": "builtin:clone", "cloned_voice": voice_id},
    })
    assert reply.status_code == 200, reply.text
    assert wait_for_idle_jobs(timeout=30)

    assert sent, "克隆那条路没把文本交给 worker"
    assert sent[-1] == "粗体 标题 a b", sent
    assert not (MARKERS & set(sent[-1])), sent


def test_只剩符号就说没话可念_不去合成一串符号(monkeypatch, spoken) -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()

    refused = client.post(
        "/api/tts/preview",
        json={"workspace_id": workspace["id"], "voice": {"engine": "builtin:edge", "voice": "zh-CN-XiaoxiaoNeural"},
              "text": "*** --- |"},
    )

    assert refused.status_code == 422, refused.text
    assert spoken == [], "只剩标记的文本还是送去合成了"


def test_只剩符号的配音任务在建任务之前就退回去(monkeypatch) -> None:
    from app.core.db import SessionLocal
    from app.db.models import Job

    client = fresh_client()
    voice_id = _a_voice(client)

    with SessionLocal() as db:
        before = db.query(Job).count()
        with pytest.raises(errors.VoiceError):
            voices.start_synthesis(db, text="***", voice=VoiceRef("builtin:clone", cloned_voice=voice_id), project_id=None,
                                   created_by=None)
        assert db.query(Job).count() == before
