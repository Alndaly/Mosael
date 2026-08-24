"""参考音频太短就当场拒绝 —— 而不是十分钟后交一段听不懂的东西。

用户:「实际克隆结果有大问题,应该几秒钟的话生成了四十多秒且根本听不懂」。

查下来:他那条音色的参考音频是 **2.6 秒**(另一份 1.5 秒)。而我们自己的界面提示写着
「上传或录制一段清晰的人声(5–15 秒)」—— **判据写在提示里,却没有任何地方执行它。**
零样本克隆靠这几秒钟把音色条件化,给不够就条件化不起来,模型一路漫游到 token 上限
(实测 1023),出来就是几十秒的胡话。

代价还不只是结果不可用:这台机器上一次 Fish Speech 合成要先花 8.5 分钟加载 18 GB 权重。
**一个开头就能判定的输入问题,让人等了十分钟才知道。**

这是今天反复出现的同一个形状:一句写下来但没有兑现的规则(「共用 venv 会互相弄坏」是注释、
「5–15 秒」是提示文案),而没有兑现的规则等于不存在。
"""

from __future__ import annotations

import io
import wave

import pytest

from app.domain.voices import voices
from tests.util import fresh_client


def _wav(seconds: float) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buf.getvalue()


def test_a_two_second_clip_is_refused() -> None:
    """用户那条就是这个长度。"""
    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]

    resp = client.post(
        "/api/voices/upload",
        data={"workspace_id": workspace_id, "name": "太短", "reference_text": "今天是个好天气"},
        files={"file": ("ref.wav", _wav(2.6), "audio/wav")},
    )

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "秒" in detail, detail
    assert "2.6" in detail or "2." in detail, f"没说清他给的是多长:{detail}"


def test_the_message_says_how_long_it_should_be() -> None:
    """拒绝要**能行动**:说清楚要多长,而不是只说"太短"。"""
    assert "5" in voices.REFERENCE_TOO_SHORT_HINT


def test_a_long_enough_clip_goes_through() -> None:
    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]

    resp = client.post(
        "/api/voices/upload",
        data={"workspace_id": workspace_id, "name": "够长", "reference_text": "今天是个好天气"},
        files={"file": ("ref.wav", _wav(8), "audio/wav")},
    )

    assert resp.status_code == 200, resp.text


def test_it_is_refused_before_the_voice_row_exists() -> None:
    """别留下一条注定合成不出东西的音色 —— 它会出现在音色库里,像个能用的选项。"""
    from app.core.db import SessionLocal
    from app.db.models import Voice

    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    client.post(
        "/api/voices/upload",
        data={"workspace_id": workspace_id, "name": "太短", "reference_text": "x"},
        files={"file": ("ref.wav", _wav(2.0), "audio/wav")},
    )

    with SessionLocal() as db:
        assert db.query(Voice).count() == 0


def test_an_existing_short_voice_is_flagged_not_silently_used() -> None:
    """库里已经有的短音色(用户那条)不能装作没事 —— 合成前就说清楚。"""
    with pytest.raises(voices.VoiceError) as caught:
        voices.check_reference_duration(2.6)

    assert "秒" in str(caught.value)


def test_synthesis_refuses_an_existing_short_voice(monkeypatch) -> None:
    """库里已经有的短音色(下限是后加的)也要挡在合成之前。

    这台机器上一次 Fish Speech 合成要先花 8.5 分钟加载 18 GB 权重 —— 一个开头就能判定的
    输入问题,不该让人等十分钟才知道。
    """
    from app.core.db import SessionLocal
    from app.db.models import Job

    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    # 绕过上传时的下限,造出一条"历史遗留"的短音色。
    monkeypatch.setattr(voices, "check_reference_duration", lambda seconds: None)
    voice = client.post(
        "/api/voices/upload",
        data={"workspace_id": workspace_id, "name": "历史遗留", "reference_text": "x"},
        files={"file": ("ref.wav", _wav(2.6), "audio/wav")},
    ).json()
    monkeypatch.undo()

    with SessionLocal() as db:
        before = db.query(Job).count()
        with pytest.raises(voices.VoiceError) as caught:
            voices.start_synthesis(db, text="你好", project_id=None, created_by=None, voice_id=voice["id"])
        assert db.query(Job).count() == before, "起了一个注定听不懂的十分钟任务"

    assert "秒" in str(caught.value)
