"""这次合成走哪条连接、用哪个模型。

单独一个模块:合成(`voices.speak_to_file`)和远端副本(`voices.remote`:确认框里说复刻到哪个模型、复刻任务建在哪个模型上)
问的是同一个问题,答案只能有一处;而它要查供应商连接和模型行 —— 放进被处处引用的 `voices.speech` 叶子里,
会把那一圈(供应商模型 → 生成 → 资产库 → 配音引擎)拖成环。
"""

from __future__ import annotations

from app.domain.voices.speech import adapter_id


def speech_target(
    db,
    engine: str,
    *,
    user_id: str | None,
    provider_profile_id: str | None = None,
    model_override: str = "",
    voice_resource: str = "",
):
    """这次合成用哪条连接(带着这个人的钥匙)、哪个模型。合成(`voices.speak_to_file`)和合成之前的检查(远端副本的
    同意、复刻任务,见 `voices.remote`)问的是同一个问题,答案只有这一处 —— 两处各算一遍的话,确认框里说的模型和真复刻
    上去的会不一样。

    返回 `(连接或 None, 模型)`。
    """
    from app.ai.providers import REMOTE_SPEECH_ADAPTERS, connection_vendor_for_speech_engine
    from app.domain.providers import models as provider_models
    from app.domain.providers.selection import resolve_connection

    engine = adapter_id(engine)
    # The profile carries base_url too. Reading only the key would send a proxy user's request
    # to api.openai.com with a key that is not valid there — a 401 with no hint as to why.
    # 引擎 id 通常就是 vendor id,百炼是唯一的例外:qwen-tts 与 CosyVoice 是两个引擎、
    # 一条连接、一把 Key(见 providers.registry.connection_vendor_for_speech_engine)。
    profile = resolve_connection(
        db, connection_vendor_for_speech_engine(engine), provider_profile_id, user_id=user_id
    )
    # **模型要按引擎那一族筛**。同一条连接下可以同时挂着 qwen-tts 和 cosyvoice-v2,
    # 不筛的话切到 CosyVoice 引擎会把 qwen 的模型名发去 CosyVoice 的端点(得到 `url error`)。
    engine_cls = REMOTE_SPEECH_ADAPTERS.get(engine)
    prefixes = getattr(engine_cls, "MODEL_PREFIXES", ())
    resolved = (
        provider_models.model_id_for_family(db, profile, "tts", prefixes)
        or getattr(engine_cls, "DEFAULT_MODEL", "")
        if prefixes
        else provider_models.model_id_for(db, profile, "tts")
    )
    return profile, model_override or voice_resource or resolved


__all__ = ["speech_target"]
