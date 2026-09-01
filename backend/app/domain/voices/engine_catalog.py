"""引擎目录:界面挑引擎时看到的那一份。

不在 `ai/providers/contracts/speech.py` 里,因为它要读**本地模型的就绪状态**(clone 引擎装没装、
百炼当前配的是哪个模型)—— 那是 `audio` 与 `domain` 的事。搬过去会让 `ai` 反过来依赖
`audio`,和既有的 `audio → ai` 撞成环(见 tests/test_import_layering)。

界线因此是清楚的:**"怎么跟这家说话"在 ai,"这个部署现在能用什么"在这里。**
"""

from __future__ import annotations

from app.ai.providers import (
    EDGE_BUILTIN_VOICES,
    PODCAST_SPEAKERS,
    VOLCANO_BUILTIN_VOICES,
    BailianSpeechAdapter,
    CosyVoiceSpeechAdapter,
    EdgeSpeechAdapter,
    OpenAISpeechAdapter,
    VolcanoSpeechAdapter,
    connection_vendor_for_speech_engine,
)

def active_model_for(engine_cls: type, user_id: str | None = None) -> str:
    """当前用户给某个百炼引擎配的模型;取不到就回它的默认模型。

    引擎目录本来是"纯静态的一张表",这里破了一次例 —— 因为百炼的音色**随模型变**,
    而界面要在**挑引擎的那一刻**就把音色列对,不能等用户填完文本才发现选的音色不存在。
    """
    prefixes = getattr(engine_cls, "MODEL_PREFIXES", ())
    default = getattr(engine_cls, "DEFAULT_MODEL", "")
    try:
        from app.core.db import SessionLocal
        from app.domain import provider_models
        from app.domain.providers import find_enabled_connection

        with SessionLocal() as db:
            profile = find_enabled_connection(
                db,
                connection_vendor_for_speech_engine(getattr(engine_cls, "engine_id", "")),
                owner_user_id=user_id,
            )
            found = provider_models.model_id_for_family(db, profile, "tts", prefixes) if profile else ""
            return found or default
    except Exception:  # noqa: BLE001 —— 引擎目录不该因为取不到模型就整个拉不出来
        return default


def describe_engines(user_id: str | None = None) -> list[dict[str, object]]:
    """What the UI needs to render an engine picker, without importing the classes.

    本地克隆这一条的 note 跟着**这台机器上装没装引擎**变:装了就说怎么用,没装就说去哪装。
    在这里说,是因为这是用户**挑引擎**的那一刻 —— 比让他填完文本、点了生成、再收到一句
    「还没有可用的引擎」要早得多。
    """
    from app.ai.runtime import tts_models
    from app.ai.runtime import config as tts_config

    # **不等探测**:这个接口只是"引擎选择器要什么",而探测要起子进程 import torch。
    # 没测过时按"还没就绪"渲染,后台探完下一次拉列表就对了(见 tts_models.runtime_status)。
    clone_ready, _checked = tts_models.runtime_status(tts_config.get().engine)
    return [
        {
            "id": "clone",
            "label": "ttsProvider_clone",
            "needs_key": False,
            # 本地克隆按**模型**定(F5 的 infer 吃 speed,fish 的请求里根本没这项),
            # 所以这里不表态,由 tts_models 那份 supports_speed 说了算。
            "supports_speed": True,
            "needs_voice_id": False,
            "voices": [],
            "ready": clone_ready,
            "note": "ttsProviderNote_cloneReady" if clone_ready else "ttsProviderNote_cloneMissing",
        },
        {
            "id": EdgeSpeechAdapter.engine_id,
            "label": EdgeSpeechAdapter.label_key,
            "needs_key": False,
            "supports_speed": True,
            "needs_voice_id": False,
            "voices": [voice for voice, _ in EDGE_BUILTIN_VOICES],
            "note": "ttsProviderNote_edge",
        },
        {
            "id": OpenAISpeechAdapter.engine_id,
            "label": OpenAISpeechAdapter.label_key,
            "needs_key": True,
            "supports_speed": True,
            "needs_voice_id": False,
            "voices": list(OpenAISpeechAdapter.VOICES),
            "note": "ttsProviderNote_openai",
        },
        {
            "id": "volcano-podcast",
            "label": "ttsProvider_volcanoPodcast",
            "needs_key": True,
            "supports_speed": True,
            "needs_voice_id": False,
            "voices": [voice for voice, _ in PODCAST_SPEAKERS],
            "note": "ttsProviderNote_volcanoPodcast",
        },
        {
            "id": BailianSpeechAdapter.engine_id,
            "label": BailianSpeechAdapter.label_key,
            "needs_key": True,
            # qwen-tts 家族没有语速参数。摆一个拨不动的旋钮比不摆更糟。
            "supports_speed": False,
            # 模型是开放集合(日期快照、instruct / vd / vc 变体),而百炼没有列音色的接口。
            # 认得出的模型走下拉(见 /api/tts/voices),认不出的退回填 id —— 而不是空下拉。
            "needs_voice_id": True,
            "voices": list(BailianSpeechAdapter.voices_for(active_model_for(BailianSpeechAdapter, user_id))),
            "note": "ttsProviderNote_bailian",
        },
        {
            # 同一把 DashScope Key 的第二套 API。分开列的理由见 CosyVoiceSpeechAdapter 的说明。
            "id": CosyVoiceSpeechAdapter.engine_id,
            "label": CosyVoiceSpeechAdapter.label_key,
            "needs_key": True,
            # 实测 rate=1.5 把 2.25 秒的句子变成 1.50 秒,是真变速。
            "supports_speed": True,
            "needs_voice_id": True,
            "voices": list(CosyVoiceSpeechAdapter.voices_for(active_model_for(CosyVoiceSpeechAdapter, user_id))),
            "note": "ttsProviderNote_cosyvoice",
        },
        {
            "id": VolcanoSpeechAdapter.engine_id,
            "label": VolcanoSpeechAdapter.label_key,
            "needs_key": True,
            "supports_speed": True,
            # The catalogue is account-dependent, so the real list comes from /api/tts/voices —
            # live when AK/SK are set, the built-in list otherwise. Either way it is a list, so
            # the panel offers a dropdown rather than asking the user to type an opaque id.
            "needs_voice_id": False,
            "voices": [voice for voice, _ in VOLCANO_BUILTIN_VOICES],
            "note": "ttsProviderNote_volcano",
        },
    ]
