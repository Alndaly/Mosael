"""语速支不支持,按引擎说 —— 我之前一句话把两个引擎一起判了。

删语速控件时我写的理由是「本地克隆的 worker 不吃这个参数」。实测:

    F5TTS.infer(..., speed=...)          ← 吃
    ServeTTSRequest 的字段里没有 speed    ← 不吃

**那句话只对 fish 成立**,而我拿它把 F5 的语速一起删了 —— 又一次"一句只在一半情况下成立
的话被当成普遍真理",只不过这次是我自己说的。

判据落回同一条:能力是**引擎的属性**,写在目录里;界面照着渲染,而不是照着一句概括。
"""

from __future__ import annotations

from app.ai.runtime import tts_models


def test_f5_supports_speed() -> None:
    assert tts_models._BY_ID["f5-tts"].supports_speed is True


def test_fish_does_not() -> None:
    """ServeTTSRequest 里没有这个字段 —— 给它一个语速等于假装能调。"""
    assert tts_models._BY_ID["fish-speech"].supports_speed is False


def test_the_capability_reaches_the_ui() -> None:
    """界面据此决定显不显示那个下拉,而不是自己猜。"""
    row = tts_models.get_status("f5-tts")

    assert row["supports_speed"] is True
    assert tts_models.get_status("fish-speech")["supports_speed"] is False


def test_speed_rides_along_to_the_worker(monkeypatch) -> None:
    """声明支持还不够,得**真的传下去** —— 这正是"选项列在那里却什么都不改变"的形状。"""
    import io
    import wave

    from app.ai.runtime import tts_daemon
    from app.domain.voices import voices
    from app.core.db import SessionLocal
    from tests.util import fresh_client

    buf = io.BytesIO()
    with wave.open(buf, "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 16000 * 8)

    sent: dict = {}
    monkeypatch.setattr(tts_models, "resolve_engine_python", lambda engine_id: "/usr/bin/python3")
    monkeypatch.setattr(tts_models, "is_installed", lambda engine_id: True)

    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    voice = client.post(
        "/api/voices/upload",
        data={"workspace_id": workspace_id, "name": "我的", "reference_text": "今天是个好天气"},
        files={"file": ("ref.wav", buf.getvalue(), "audio/wav")},
    ).json()

    class _Pool:
        def request(self, engine, python, payload, **kwargs):
            sent.update(payload)
            raise RuntimeError("到此为止 —— 这条测试只看请求里带了什么")

    monkeypatch.setattr(tts_daemon, "pool", lambda: _Pool())

    with SessionLocal() as db:
        voices._run_synthesis_body(
            voices.start_synthesis(db, text="你好", project_id=None, created_by=None,
                                   voice_id=voice["id"], clone_engine="f5-tts", speed=1.5).id,
            voice["id"], "你好", None, engine="clone", speed=1.5, clone_engine="f5-tts",
        )

    assert sent.get("speed") == 1.5, sent
