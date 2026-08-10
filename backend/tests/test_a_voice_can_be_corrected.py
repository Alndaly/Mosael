"""音色建好之后要能改 —— 至少能补上参考文本。

我刚把「参考文本」变成 Fish Speech 的必填项(因为它不带 ASR,空文本会让输出听不懂)。
而音色的接口只有 upload / from-speaker / delete —— **没有 update**。于是用户那条已经录好的
7.5 秒音色,只因为当初表单说「留空则自动识别」而没填文本,现在只能删了重建。

**一个新加的必填项,如果没有对应的补填入口,就是在逼用户重做一遍已经做过的事。**

改名同理:音色是长期资产(参考音频是用户自己录的),而名字是最容易一开始随手写的东西。

不能改的是**参考音频本身** —— 换了音频就是另一个音色了,而已经用它生成过的配音还在时间线上;
让同一个 id 底下的声音悄悄变成另一个人,比让用户新建一条更糟。
"""

from __future__ import annotations

import io
import wave

from tests.util import fresh_client


def _wav(seconds: float = 8) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buf.getvalue()


def _a_voice(client, *, text: str = "") -> dict:
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    created = client.post(
        "/api/voices/upload",
        data={"workspace_id": workspace_id, "name": "我的", "reference_text": text},
        files={"file": ("ref.wav", _wav(), "audio/wav")},
    ).json()
    return {**created, "workspace_id": workspace_id}


def test_the_reference_text_can_be_filled_in_afterwards() -> None:
    client = fresh_client()
    voice = _a_voice(client)
    assert voice["reference_text"] == ""

    updated = client.patch(f"/api/voices/{voice['id']}", json={"reference_text": "今天是个好天气"})

    assert updated.status_code == 200, updated.text
    assert updated.json()["reference_text"] == "今天是个好天气"


def test_the_name_can_be_changed() -> None:
    client = fresh_client()
    voice = _a_voice(client)

    updated = client.patch(f"/api/voices/{voice['id']}", json={"name": "老板的声音"})

    assert updated.json()["name"] == "老板的声音"


def test_omitted_fields_are_left_alone() -> None:
    """只改一个字段时别把另一个清空 —— PATCH 的语义就是"没提到的不动"。"""
    client = fresh_client()
    voice = _a_voice(client, text="原来的文本")

    client.patch(f"/api/voices/{voice['id']}", json={"name": "改个名"})

    listed = client.get(f"/api/voices?workspace_id={voice['workspace_id']}").json()[0]
    assert listed["reference_text"] == "原来的文本"
    assert listed["name"] == "改个名"


def test_an_empty_name_is_refused() -> None:
    """名字是用户在下拉里认这条音色的唯一凭据,不能改成空的。"""
    client = fresh_client()
    voice = _a_voice(client)

    resp = client.patch(f"/api/voices/{voice['id']}", json={"name": "   "})

    assert resp.status_code == 422, resp.text


def test_a_missing_voice_is_404() -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})

    assert client.patch("/api/voices/nope", json={"name": "x"}).status_code == 404


def test_filling_in_the_text_unblocks_fish(monkeypatch) -> None:
    """补上文本之后,fish 那道闸就该放行 —— 这条把两件事连起来:
    没有补填入口的必填项,等于一条死路。"""
    from app.audio import tts_models, voices
    from app.core.db import SessionLocal

    monkeypatch.setattr(tts_models, "resolve_engine_python", lambda engine_id: "/usr/bin/python3")
    monkeypatch.setattr(tts_models, "is_installed", lambda engine_id: True)
    client = fresh_client()
    voice = _a_voice(client)
    client.patch(f"/api/voices/{voice['id']}", json={"reference_text": "今天是个好天气"})

    with SessionLocal() as db:
        job = voices.start_synthesis(db, text="你好", project_id=None, created_by=None,
                                     voice_id=voice["id"], clone_engine="fish-speech")
    assert job.kind == "tts"
