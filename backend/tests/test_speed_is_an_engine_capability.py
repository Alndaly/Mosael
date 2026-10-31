"""语速由谁来调,按引擎说 —— 我之前一句话把两个引擎一起判了。

删语速控件时我写的理由是「本地克隆的 worker 不吃这个参数」。实测:

    F5TTS.infer(..., speed=...)          ← 吃
    ServeTTSRequest 的字段里没有 speed    ← 不吃

**那句话只对 fish 成立**,而我拿它把 F5 的语速一起删了 —— 又一次"一句只在一半情况下成立
的话被当成普遍真理",只不过这次是我自己说的。

判据落回同一条:能力是**引擎的属性**,写在目录里;界面照着渲染,而不是照着一句概括。

后来(2026-10-31,维护者问「Fish Speech S2 Pro 没办法调节语速吗」)把「支不支持」改成了「由谁来调」:
`native` 随请求交给引擎;`stretch` 的引擎按原速念,宿主合成之后用 atempo 变速(音高不变)。
于是语速对每个引擎都可调,不再有「不支持」这一档(media/tempo.stretch_in_place)。
"""

from __future__ import annotations

from app.ai.runtime import tts_models
from app.domain.voices.voice_ref import VoiceRef


def test_f5_takes_speed_natively() -> None:
    assert tts_models._BY_ID["f5-tts"].speed_control == "native"


def test_fish_and_qwen_are_stretched_by_the_host() -> None:
    """ServeTTSRequest(本机检出与上游 main)、generate_custom_voice 里都没有语速 —— 交给宿主变速。"""
    assert tts_models._BY_ID["fish-speech"].speed_control == "stretch"
    assert tts_models._BY_ID["qwen-tts"].speed_control == "stretch"


def test_the_capability_reaches_the_ui() -> None:
    """界面据此标明哪些是后处理变速,而不是自己猜。"""
    assert tts_models.get_status("f5-tts")["speed_control"] == "native"
    assert tts_models.get_status("fish-speech")["speed_control"] == "stretch"


def test_speed_rides_along_to_the_worker(monkeypatch) -> None:
    """声明支持还不够,得**真的传下去** —— 这正是"选项列在那里却什么都不改变"的形状。"""
    import io
    import wave

    from app.ai.runtime import tts_daemon
    from app.domain.voices import voices
    from app.domain.voices.speech import CLONE_ENGINE
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
        data={"workspace_id": workspace_id, "name": "我的", "reference_text": "今天是个好天气", "consent_kind": "self"},
        files={"file": ("ref.wav", buf.getvalue(), "audio/wav")},
    ).json()

    class _Pool:
        def request(self, engine, python, payload, **kwargs):
            sent.update(payload)
            raise RuntimeError("到此为止 —— 这条测试只看请求里带了什么")

    monkeypatch.setattr(tts_daemon, "pool", lambda: _Pool())

    with SessionLocal() as db:
        job_id = voices.start_synthesis(db, text="你好", project_id=None, created_by=None,
                                        voice=VoiceRef("builtin:clone", cloned_voice=voice["id"], model="f5-tts"), speed=1.5).id
        db.commit()  # 测试是入口:任务在提交之后才派发(jobs.dispatch_job)
        voices._run_synthesis_body(
            job_id,
            #: 引擎 id 带前缀(`builtin:clone`)。写成裸名 "clone" 时这一句根本走不到 pool,断言只能靠
            #: start_synthesis 起的后台线程赶在它之前填上 `sent` —— 整套里偶尔赶不上,测试就时红时绿。
            VoiceRef(CLONE_ENGINE, cloned_voice=voice["id"], model="f5-tts"), "你好", 1.5,
            workspace_id=workspace_id, project_id=None,
        )

    assert sent.get("speed") == 1.5, sent
