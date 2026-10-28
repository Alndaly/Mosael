"""语音合成的账记在**连接的厂商**名下,对得上价目规则;老账一次改过来。

百炼一条连接下有两个引擎(qwen-tts、CosyVoice),价目规则 —— 成本规则里「预填价格」填的、手写的 —— 按厂商 `alibaba` 配。
此前合成的账记的是引擎 id `alibaba-cosyvoice`,规则永远对不上,CosyVoice 念多少都是「未定价」。
"""

from __future__ import annotations

import wave
from pathlib import Path


from app.ai.providers.adapters.alibaba.dashscope.speech import CosyVoiceSpeechAdapter
from app.core.db import SessionLocal
from app.db.models import ProviderUsageEvent
from app.domain.billing.usage import create_pricing_rule
from tests.util import add_provider, fresh_client, user_id

MODEL = "cosyvoice-v3-flash"


def _silence(adapter, request, out_path: Path) -> None:
    with wave.open(str(out_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(22050)
        handle.writeframes(b"\0\0" * 2205)


def test_CosyVoice的账记在alibaba名下_预填价格那种按厂商配的价对得上(monkeypatch, tmp_path) -> None:
    from app.domain.voices.voices import speak_to_file

    monkeypatch.setattr(CosyVoiceSpeechAdapter, "synthesize", _silence)
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        profile = add_provider(db, name="百炼", vendor="alibaba", base_url="", api_key="sk-test",
                               model=MODEL, capability_ids=["tts"])
        # 官方价 1 元/万字符 = 每字符 100 微元;和 pricing_prefill 一样按厂商配(provider = 连接的 vendor)。
        create_pricing_rule(db, provider_profile_id=profile.id, provider="alibaba", capability="tts", model=MODEL,
                            billing_unit="character", unit_amount_micros=100, currency="CNY", source="reference")
        speak_to_file(db, text="点下方链接", engine="builtin:alibaba-cosyvoice", engine_voice="longxiaochun_v3",
                      speed=1.0, workspace_id=ws, user_id=user_id(), provider_profile_id=profile.id,
                      out_dir=tmp_path, source_type="test", source_id="t")
        db.commit()
        event = db.query(ProviderUsageEvent).filter(ProviderUsageEvent.capability == "tts").one()
    assert (event.provider, event.model) == ("alibaba", MODEL), "记连接的厂商,不是引擎 id"
    assert (event.cost_micros, event.currency) == (500, "CNY"), "5 个字符 × 100 微元"
