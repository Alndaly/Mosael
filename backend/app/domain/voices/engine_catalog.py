"""引擎目录:界面挑引擎时看到的那一份。

不在 `ai/providers/contracts/speech.py` 里,因为它要读**本地模型的就绪状态**(clone 引擎装没装、
百炼当前配的是哪个模型)—— 那是 `audio` 与 `domain` 的事。搬过去会让 `ai` 反过来依赖
`audio`,和既有的 `audio → ai` 撞成环(见 tests/test_import_layering)。

界线因此是清楚的:**"怎么跟这家说话"在 ai,"这个部署现在能用什么"在这里。**
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

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

logger = logging.getLogger(__name__)

#: 播客引擎:一次产出一整段双人对话,不是"念一句话"那种 —— 念字的地方都不该列它。
PODCAST_ENGINE = "volcano-podcast"
#: 「克隆音色」这一项。没选引擎时按它算。
CLONE_ENGINE = "clone"


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
            "id": PODCAST_ENGINE,
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


def list_engine_voices(db: Session, engine: str, *, user_id: str | None) -> list[dict[str, str]]:
    """The voices an engine can speak in, live where the account allows it.

    火山's catalogue depends on the account, and a voice used with the wrong resource family
    fails with an opaque 55000000 — so when AK/SK are configured the list is pulled from the
    account and each voice carries its family. Without them, the built-in list still works;
    it is smaller and can go stale, which is a far better failure than an empty dropdown.
    """
    from app.ai.providers import REMOTE_SPEECH_ADAPTERS
    from app.domain.providers import resolve_connection

    # **固定音色的引擎不在这里再写一遍。** 这个函数原本是逐引擎的 if 分支,末尾一句
    # `if engine != "volcano": return []` —— 于是加一个引擎要改两处(引擎目录 + 这里),
    # 漏掉第二处的表现是"引擎选得出来,但音色下拉是空的"。百炼刚接进来时就是这样。
    # 音色清单只有一个产地:describe_engines()。这里只负责**火山那条实时的**。
    if engine in (BailianSpeechAdapter.engine_id, "alibaba-cosyvoice"):
        # 百炼的音色**跟着模型走**(qwen3-tts-flash 有 qwen-tts 没有的几个,CosyVoice 的
        # id 更是完全另一套)。这里解析模型必须和合成时**同一条路径**,否则下拉列的是 A 的
        # 音色、发出去的是 B 的请求 —— 用户选了个看着合法的音色,拿回一句"音色不存在"。
        engine_cls = REMOTE_SPEECH_ADAPTERS[engine]
        return [
            {"value": voice, "label": voice}
            for voice in engine_cls.voices_for(active_model_for(engine_cls, user_id))
        ]

    if engine != "volcano":
        fixed = next((item for item in describe_engines(user_id) if item["id"] == engine), None)
        voices = list(fixed.get("voices") or []) if fixed else []
        # **标签要从所有带标签的清单里找**,不只是 edge。engine 目录里的 `voices` 是纯 id
        # (schema 是 list[str]),而 edge / 播客 / 火山内置那三张表都是 (id, 名字) 成对的 ——
        # 只查 edge 的话,播客那四个会显示成 `zh_male_dayixiansheng_v2_saturn_bigtts`
        # 这种一眼认不出谁是谁的原始 id(真机截图)。
        labels = {**dict(EDGE_BUILTIN_VOICES), **dict(PODCAST_SPEAKERS), **dict(VOLCANO_BUILTIN_VOICES)}
        return [{"value": voice, "label": labels.get(voice, voice)} for voice in voices]

    # ak/sk 是密字段,跟着**我自己**那把钥匙走(见 domain/provider_credentials) ——
    # 列音色用的是我的账号,不是"这个部署里随便谁的"。
    volcano = resolve_connection(db, "volcano", user_id=user_id)
    ak, sk = str((volcano.extra if volcano else {}).get("ak") or ""), str((volcano.extra if volcano else {}).get("sk") or "")
    if ak and sk:
        from app.integrations.volc_openapi import VolcOpenAPIError, list_all_speakers

        try:
            live = list_all_speakers(ak, sk)
        except VolcOpenAPIError as exc:
            # Falling back beats failing: the user can still synthesise, and the reason the
            # live list is missing belongs in the log rather than in a broken dropdown.
            logger.info("volcano live voice list unavailable: %s", exc)
        else:
            if live:
                return [
                    {
                        "value": speaker.get("VoiceType", ""),
                        "label": speaker.get("Name") or speaker.get("VoiceType", ""),
                        "resource_id": speaker.get("ResourceID", ""),
                    }
                    for speaker in live
                    if speaker.get("VoiceType")
                ]
    return [{"value": voice, "label": label} for voice, label in VOLCANO_BUILTIN_VOICES]


def voice_resource_for(db: Session, engine: str, voice: str, *, user_id: str | None) -> str:
    """这个音色的资源族(只有火山有)。**合成的那一方自己查**,不靠界面选音色时顺手填上 ——
    那样的话,每一个挑音色的地方都得记得多存一个字段,而忘了存的后果是音色不生效、也不报错。
    查不到就是空串:内置音色由合成那边按 id 推断。
    """
    if not voice:
        return ""
    for item in list_engine_voices(db, engine, user_id=user_id):
        if item.get("value") == voice:
            return str(item.get("resource_id") or "")
    return ""


#: 只属于某一条路的附加项。另一条路收到它们会报"没有这个参数",所以按引擎挑着带。
_CLONE_OPTIONS = ("clone_engine", "clone_model")
_ENGINE_OPTIONS = ("provider_profile_id", "engine_model", "engine_voice_resource")


def synthesis_params(db: Session, *, engine: str, voice: str, speed: float = 1.0,
                     user_id: str | None, workspace_id: str, **options: object) -> dict[str, object]:
    """「引擎 + 一格音色」→ voices.start_synthesis 要的那组参数。念字的入口(工作流、智能体、
    字幕配音)都走这里,不各自拼。

    音色一格,按引擎分两种意思:克隆时是配音库里的音色 id(`voice_id`),其余是那个引擎的
    音色(`engine_voice`)。两条路要的参数不是一个集合 —— 都塞过去,合成那边会收到它这条路上
    根本没有的参数。火山的音色还要一个资源族,调用方没给就**这里自己查**,不靠界面选音色时
    顺手存下。引擎那条要一个工作区来认领产出(克隆那条从 Voice 行上取)。
    `options` 是两条路各自的附加项(克隆权重、引擎连接/模型),不属于这条路的丢掉。
    """
    from app.domain.voices.voices import VoiceError

    engine = (engine or "").strip() or CLONE_ENGINE
    voice = (voice or "").strip()
    if not voice:
        raise VoiceError("没有选音色")
    unknown = set(options) - set(_CLONE_OPTIONS) - set(_ENGINE_OPTIONS)
    if unknown:
        raise TypeError(f"synthesis_params 不认识:{sorted(unknown)}")
    params: dict[str, object] = {"engine": engine, "speed": float(speed or 1.0)}
    clone = engine == CLONE_ENGINE
    for key in _CLONE_OPTIONS if clone else _ENGINE_OPTIONS:
        if options.get(key):
            params[key] = options[key]
    if clone:
        #: 音色 id 可能来自任何地方(上游节点的输出、模型填的参数)—— 收进这个工作区。
        from app.db.models import Voice

        row = db.get(Voice, voice)
        if row is None or row.workspace_id != workspace_id:
            raise VoiceError("这个工作区的配音库里没有这个音色")
        params["voice_id"] = voice
    else:
        params["engine_voice"] = voice
        params["workspace_id"] = workspace_id
        if not params.get("engine_voice_resource"):
            params["engine_voice_resource"] = voice_resource_for(db, engine, voice, user_id=user_id)
    return params
