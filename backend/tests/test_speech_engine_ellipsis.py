"""省略号怎么念是**引擎**的差异,不是文案的清洗规则。

Edge 把 `……` 当停顿(实测约 0.79 秒),另一些引擎会逐字念成「省略号」。所以:
- `speakable_text` 原样留下标点;
- 每个内置引擎在目录里声明 `pause` / `literal`;
- `literal` 的那几家在送进合成之前由 `text_for_engine` 换成停顿标点。
"""

from __future__ import annotations

from pathlib import Path

from app.ai.providers import speech_engines
from app.ai.providers.adapters.microsoft.edge_speech import EdgeSpeechAdapter
from app.ai.runtime import tts_models
from app.ai.speech_text import pause_ellipsis, text_for_engine
from app.domain.voices.speakable import speakable_text


def test_会念符号名的引擎把省略号换成停顿() -> None:
    assert pause_ellipsis("等等……") == "等等。"
    assert pause_ellipsis("又差一步......是不是,我真的不行") == "又差一步，是不是,我真的不行"
    assert pause_ellipsis("真的……！") == "真的！"
    #: 后面已经有停顿时不叠一个。
    assert pause_ellipsis("等等……。") == "等等。"


def test_认识的引擎拿到原样_不认识的拿到停顿() -> None:
    assert EdgeSpeechAdapter.ellipsis == "pause"
    assert text_for_engine("等等……", EdgeSpeechAdapter.ellipsis) == "等等……"
    assert text_for_engine("等等……", "literal") == "等等。"


def test_每个内置引擎都声明了省略号策略() -> None:
    for engine in speech_engines():
        assert engine.ellipsis in {"pause", "literal"}, engine.engine_id
    for engine in tts_models.CATALOG:
        assert engine.ellipsis in {"pause", "literal"}, engine.id


def test_文案层不再替引擎处理省略号() -> None:
    assert speakable_text("又差一步......是不是,我真的不行") == "又差一步......是不是,我真的不行"
    assert speakable_text("等等……") == "等等……"


def test_真实的远程合成路径按引擎策略改写(monkeypatch, tmp_path: Path) -> None:
    """不只测纯函数:`speak_to_file` 必须把 `literal` 引擎的文本换成停顿后再交给 Adapter。"""
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.db.models import User
    from app.domain.voices import voices
    from app.domain.voices.voice_ref import VoiceRef
    from tests.util import fresh_client

    seen: list[str] = []

    class _Recorder:
        ellipsis = "literal"
        speed_control = "native"
        free_of_charge = True

        def synthesize(self, request, out_path: Path) -> None:
            seen.append(request.text)
            out_path.write_bytes(b"RIFF")

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        me = db.scalars(select(User).order_by(User.created_at)).first().id
        monkeypatch.setattr(voices.providers, "build_speech_adapter", lambda *a, **k: _Recorder())
        monkeypatch.setattr(voices, "speech_target", lambda *a, **k: (None, ""))
        voices.speak_to_file(
            db,
            text="又差一步......是不是,我真的不行",
            voice=VoiceRef("builtin:openai", voice="alloy"),
            speed=1.0,
            workspace_id=workspace,
            user_id=me,
            out_dir=tmp_path,
            source_type="test",
            source_id="t",
        )
        db.commit()

    assert seen == ["又差一步，是不是,我真的不行"]
