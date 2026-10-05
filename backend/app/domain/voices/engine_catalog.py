"""引擎目录:界面挑引擎时看到的那一份。

不在 `ai/providers/contracts/speech.py` 里,因为它要读**本地模型的就绪状态**(clone 引擎装没装、
百炼当前配的是哪个模型)—— 那是 `audio` 与 `domain` 的事。搬过去会让 `ai` 反过来依赖
`audio`,和既有的 `audio → ai` 撞成环(见 tests/test_import_layering)。

界线因此是清楚的:**"怎么跟这家说话"在 ai,"这个部署现在能用什么"在这里。**

配音是一项宿主能力(ADR 0032 第四步):id、契约和插件协议见 `voices.speech`;这里列的是界面上挑引擎看的那一份。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.domain.voices.speech import (
    BUILTIN_PREFIX,
    CAPABILITY,
    CLONE_ENGINE,
    PODCAST_ENGINE,
    SPEECH,
    SpeechProviderUnavailable,
    adapter_id,
    engine_ready,
    is_plugin,
    require_engine,
)

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

def active_model_for(engine_cls: type, user_id: str | None = None) -> str:
    """当前用户给某个百炼引擎配的模型;取不到就回它的默认模型。

    引擎目录本来是"纯静态的一张表",这里破了一次例 —— 因为百炼的音色**随模型变**,
    而界面要在**挑引擎的那一刻**就把音色列对,不能等用户填完文本才发现选的音色不存在。
    """
    prefixes = getattr(engine_cls, "MODEL_PREFIXES", ())
    default = getattr(engine_cls, "DEFAULT_MODEL", "")
    try:
        from app.core.db import SessionLocal
        from app.domain.providers import models as provider_models
        from app.domain.providers.selection import find_enabled_connection

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


def describe_engines(db: Session | None, user_id: str | None = None) -> list[dict[str, object]]:
    """What the UI needs to render an engine picker, without importing the classes.

    本地克隆这一条的 note 跟着**这台机器上装没装引擎**变:装了就说怎么用,没装就说去哪装。
    在这里说,是因为这是用户**挑引擎**的那一刻 —— 比让他填完文本、点了生成、再收到一句
    「还没有可用的引擎」要早得多。

    **每一条都带 `ready`**(见 `_engine_ready`)。它曾经只长在克隆那一条上,而"这个引擎现在
    能不能用"是所有引擎都要回答的问题 —— 结果是:只列就绪引擎的那个下拉里,除了克隆一个都不剩。
    给不出会话(没有 db)时,要钥匙的引擎按"不知道"算 = 不就绪:宁可少列一个,也不要让人选中之后
    才失败。
    """
    from app.ai.runtime import tts_models
    from app.ai.runtime import config as tts_config

    # **不等探测**:这个接口只是"引擎选择器要什么",而探测要起子进程 import torch。
    # 没测过时按"还没就绪"渲染,后台探完下一次拉列表就对了(见 tts_models.runtime_status)。
    clone_ready, _checked = tts_models.runtime_status(tts_config.get().engine)
    engines: list[dict[str, object]] = [
        {
            "id": CLONE_ENGINE,
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
            "id": f"{BUILTIN_PREFIX}{EdgeSpeechAdapter.engine_id}",
            "label": EdgeSpeechAdapter.label_key,
            "needs_key": False,
            "supports_speed": True,
            "needs_voice_id": False,
            "voices": [voice for voice, _ in EDGE_BUILTIN_VOICES],
            "note": "ttsProviderNote_edge",
        },
        {
            "id": f"{BUILTIN_PREFIX}{OpenAISpeechAdapter.engine_id}",
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
            "id": f"{BUILTIN_PREFIX}{BailianSpeechAdapter.engine_id}",
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
            "id": f"{BUILTIN_PREFIX}{CosyVoiceSpeechAdapter.engine_id}",
            "label": CosyVoiceSpeechAdapter.label_key,
            "needs_key": True,
            # 实测 rate=1.5 把 2.25 秒的句子变成 1.50 秒,是真变速。
            "supports_speed": True,
            "needs_voice_id": True,
            "voices": list(CosyVoiceSpeechAdapter.voices_for(active_model_for(CosyVoiceSpeechAdapter, user_id))),
            "note": "ttsProviderNote_cosyvoice",
        },
        {
            "id": f"{BUILTIN_PREFIX}{VolcanoSpeechAdapter.engine_id}",
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
    for engine in engines:
        engine.setdefault("ready", engine_ready(db, adapter_id(str(engine["id"])), bool(engine["needs_key"]), user_id))
        #: 能不能念配音库里的克隆音色(复刻上去),问注册表 —— 不在这张表里再写一遍是哪一家。
        engine["clones_voices"] = _clones_remotely(str(engine["id"]))
    return engines + _plugin_engines(db, user_id)


def _plugin_engines(db: Session | None, user_id: str | None) -> list[dict[str, object]]:
    """认领 `speech` 的插件连接,和内置引擎同一个形状。音色问插件要(`op: voices`);没配好的照列,`ready` 为假。"""
    if db is None:
        return []
    from app.domain import capabilities

    found: list[dict[str, object]] = []
    for provider in capabilities.plugin_providers(db, user_id, CAPABILITY):
        ready = not provider.missing and bool(provider.tool)
        found.append({
            "id": provider.id,
            "label": provider.name,
            "needs_key": False,
            "supports_speed": True,
            "needs_voice_id": False,
            "voices": [voice["value"] for voice in _plugin_voices(db, provider)] if ready else [],
            "ready": ready,
            "note": "",
            "plugin": True,
        })
    return found


def _plugin_voices(db: Session, provider) -> list[dict[str, str]]:
    """插件连接能念的音色(`op: voices`)。问不到就是空清单,原因记进日志 —— 一个坏插件不该让引擎下拉整个拉不出来。"""
    from app.domain.plugins.errors import PluginDomainError
    from app.domain.plugins.runtime import PluginRuntimeError
    from app.domain.plugins.tools import invoke_host

    try:
        output = invoke_host(db, provider.id, SPEECH, {"op": "voices"}, record=False)
    except (PluginDomainError, PluginRuntimeError) as exc:
        logger.info("speech plugin %s voices unavailable: %s", provider.id, exc)
        return []
    voices = output.get("voices") if isinstance(output, dict) else None
    return [
        {"value": str(voice.get("id")), "label": str(voice.get("name") or voice.get("id"))}
        for voice in (voices if isinstance(voices, list) else [])
        if isinstance(voice, dict) and voice.get("id")
    ]


def list_engine_voices(db: Session, engine: str, *, user_id: str | None, workspace_id: str = "") -> list[dict[str, Any]]:
    """The voices an engine can speak in, live where the account allows it.

    火山's catalogue depends on the account, and a voice used with the wrong resource family
    fails with an opaque 55000000 — so when AK/SK are configured the list is pulled from the
    account and each voice carries its family. Without them, the built-in list still works;
    it is smaller and can go stale, which is a far better failure than an empty dropdown.

    带了工作区、而这个引擎能复刻(CosyVoice)时,系统音色后面再接一组这个工作区配音库里的克隆音色(ADR 0037):
    `value` 是嗓子的 id,`cloned` 为真 —— 选它时请求带 `voice_id`,宿主在合成前把它解析成远端副本。
    """
    stock = _engine_voices(db, engine, user_id=user_id)
    if workspace_id and _clones_remotely(engine):
        stock = stock + cloned_voices(db, workspace_id)
    return stock


def _clones_remotely(engine: str) -> bool:
    from app.domain.voices.remote import clones_remotely

    return clones_remotely(engine)


def cloned_voices(db: Session, workspace_id: str) -> list[dict[str, Any]]:
    """这个工作区配音库里**能复刻出去**的嗓子(声明过是谁的;没声明的不往外传,ADR 0028 §5)。"""
    from sqlalchemy import select

    from app.db.models import Voice
    from app.domain.voices.consent import UNDECLARED

    rows = db.scalars(
        select(Voice)
        .where(Voice.workspace_id == workspace_id, Voice.consent_kind != UNDECLARED)
        .order_by(Voice.created_at)
    )
    return [{"value": row.id, "label": row.name, "cloned": True} for row in rows]


def _engine_voices(db: Session, engine: str, *, user_id: str | None) -> list[dict[str, Any]]:
    """引擎**自己的**音色(系统音色;火山按账号现拉)。"""
    from app.ai.providers import REMOTE_SPEECH_ADAPTERS
    from app.domain.providers.selection import resolve_connection

    # **固定音色的引擎不在这里再写一遍。** 这个函数原本是逐引擎的 if 分支,末尾一句
    # `if engine != "volcano": return []` —— 于是加一个引擎要改两处(引擎目录 + 这里),
    # 漏掉第二处的表现是"引擎选得出来,但音色下拉是空的"。百炼刚接进来时就是这样。
    # 音色清单只有一个产地:describe_engines()。这里只负责**火山那条实时的**。
    if is_plugin(engine):
        from app.domain import capabilities

        provider = next((one for one in capabilities.plugin_providers(db, user_id, CAPABILITY) if one.id == engine), None)
        return _plugin_voices(db, provider) if provider is not None and not provider.missing else []
    engine = adapter_id(engine)
    if engine in (BailianSpeechAdapter.engine_id, CosyVoiceSpeechAdapter.engine_id):
        # 百炼的音色**跟着模型走**(qwen3-tts-flash 有 qwen-tts 没有的几个,CosyVoice 的
        # id 更是完全另一套)。这里解析模型必须和合成时**同一条路径**,否则下拉列的是 A 的
        # 音色、发出去的是 B 的请求 —— 用户选了个看着合法的音色,拿回一句"音色不存在"。
        engine_cls = REMOTE_SPEECH_ADAPTERS[engine]
        return [
            {"value": voice, "label": voice}
            for voice in engine_cls.voices_for(active_model_for(engine_cls, user_id))
        ]

    if engine != "volcano":
        fixed = next((item for item in describe_engines(db, user_id) if item["id"] == f"{BUILTIN_PREFIX}{engine}"), None)
        voices = list(fixed.get("voices") or []) if fixed else []
        # **标签要从所有带标签的清单里找**,不只是 edge。engine 目录里的 `voices` 是纯 id
        # (schema 是 list[str]),而 edge / 播客 / 火山内置那三张表都是 (id, 名字) 成对的 ——
        # 只查 edge 的话,播客那四个会显示成 `zh_male_dayixiansheng_v2_saturn_bigtts`
        # 这种一眼认不出谁是谁的原始 id(真机截图)。
        labels = {**dict(EDGE_BUILTIN_VOICES), **dict(PODCAST_SPEAKERS), **dict(VOLCANO_BUILTIN_VOICES)}
        return [{"value": voice, "label": labels.get(voice, voice)} for voice in voices]

    # ak/sk 是密字段,跟着**我自己**那把钥匙走(见 domain/providers/credentials) ——
    # 列音色用的是我的账号,不是"这个部署里随便谁的"。
    volcano = resolve_connection(db, "volcano", user_id=user_id)
    ak, sk = str((volcano.extra if volcano else {}).get("ak") or ""), str((volcano.extra if volcano else {}).get("sk") or "")
    if ak and sk:
        from app.ai.providers import VolcOpenAPIError, list_all_speakers

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


def clone_engine_ready() -> bool | None:
    """本机克隆引擎(配音库的音色走它)跑不跑得起来:True 跑得起来,False 已知跑不起来(没有运行环境、或权重没下),
    None 还没测过。只读已经测过的结果，不在请求里起探测(起子进程 import torch 要十几秒)。"""
    from app.ai.runtime import config as tts_config
    from app.ai.runtime import tts_models

    engine = tts_config.get().engine
    ready, known = tts_models.runtime_status(engine)
    if known and not ready:
        return False
    if ready and not tts_models.is_installed(engine):
        return False
    return True if ready else None


def cloned_voice_status(db: Session, workspace_id: str, *, digital_human: bool = False) -> str:
    """这个工作区的配音库里有没有**能用的**克隆音色:`met` 有、而且克隆引擎跑得起来;`missing` 没有音色或引擎已知
    跑不起来;`unknown` 有音色、引擎还没测过。`digital_human`:要交给数字人的，只算声明过是谁的那几把(ADR 0028 §5)。

    模板的前置检查、建图时预填音色、配音节点说「用的是哪把嗓子」用的都是这一个判据。
    """
    from sqlalchemy import select

    from app.db.models import Voice
    from app.domain.voices.consent import UNDECLARED

    if not workspace_id:
        return "missing"
    query = select(Voice.id).where(Voice.workspace_id == workspace_id)
    if digital_human:
        query = query.where(Voice.consent_kind != UNDECLARED)
    if db.scalar(query.limit(1)) is None:
        return "missing"
    ready = clone_engine_ready()
    return "missing" if ready is False else "met" if ready else "unknown"


def voice_note(db: Session, *, engine: str, voice: str, workspace_id: str, user_id: str | None) -> str:
    """「这次配音用的是哪把嗓子」—— 按**实际**念的引擎和音色说的一句话(配音节点的 `voice_note`,完成通知里用)。

    用的不是克隆音色时,顺带说清楚配音库里有没有能用的克隆音色(判据和模板预填音色同一个,见
    cloned_voice_status):此前带货口播的那句是建图时写死的,之后在节点里换上克隆音色,通知照样说 Edge。
    """
    from app.core.i18n import fragment, tr
    from app.db.models import Voice

    engine = (engine or "").strip() or CLONE_ENGINE
    if engine == CLONE_ENGINE:
        row = db.get(Voice, voice) if voice else None
        return tr("wfVoice_cloned", name=row.name if row is not None else voice)
    entry = next((one for one in describe_engines(db, user_id) if one["id"] == engine), None)
    label = str(entry["label"]) if entry is not None else engine
    #: 带上工作区:CosyVoice 念的可能是配音库里的嗓子(ADR 0037),那时说它的名字,不说一串 id。
    named = {one["value"]: one["label"] for one in list_engine_voices(db, engine, user_id=user_id, workspace_id=workspace_id)}
    spoken = str(named.get(voice, voice)).split("(")[0].strip() or voice
    has_clone = cloned_voice_status(db, workspace_id) != "missing"
    return tr("wfVoice_engineCloneReady" if has_clone else "wfVoice_engineNoClone", voice=spoken, engine=fragment(label))


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


def speaking_engines(db: Session, user_id: str | None, workspace_id: str) -> list[dict[str, Any]]:
    """念一句话能用的引擎,各带着自己的音色(id + 名字)—— 给**不看界面的那一方**(智能体)挑引擎用。

    和界面那份目录(describe_engines)同一个产地,只是换成读得懂的形状:名字、说明翻好,音色带上名字,克隆那一项
    的音色是**这个工作区**音色库里的(界面上那一项的音色另有一个下拉)。播客不在其中 —— 它不念一句话。
    """
    from app.core.i18n import tr
    from app.domain.voices.voices import list_voices

    labels = {**dict(EDGE_BUILTIN_VOICES), **dict(VOLCANO_BUILTIN_VOICES)}
    found: list[dict[str, Any]] = []
    for engine in describe_engines(db, user_id):
        if engine["id"] == PODCAST_ENGINE:
            continue
        if engine["id"] == CLONE_ENGINE:
            voices = [{"id": voice.id, "name": voice.name} for voice in list_voices(db, workspace_id)]
        else:
            voices = [{"id": str(voice), "name": labels.get(str(voice), str(voice))} for voice in engine["voices"]]
            if _clones_remotely(str(engine["id"])):
                #: 能复刻的引擎(CosyVoice)也念得了配音库里的嗓子(念它的远端副本,第一次要用户同意上传)。
                voices += [{"id": one["value"], "name": one["label"], "cloned": True} for one in cloned_voices(db, workspace_id)]
        plugin = bool(engine.get("plugin"))
        found.append({
            "id": engine["id"],
            # 插件连接的名字是用户起的,不是文案 key。
            "name": str(engine["label"]) if plugin else tr(str(engine["label"])),
            "ready": bool(engine["ready"]),
            #: 不花钱、不用配钥匙(Edge、本机克隆)。
            "free": not engine["needs_key"] and not plugin,
            "note": tr(str(engine["note"])) if engine.get("note") else "",
            "voices": voices,
        })
    return found


def _engine_list(engines: list[dict[str, Any]]) -> str:
    from app.core.i18n import tr

    return tr("punct_listSep").join(f"{one['id']} ({one['name']})" for one in engines) or "—"



def pick_speech(db: Session, *, engine: str, voice: str, user_id: str | None, workspace_id: str) -> tuple[str, str]:
    """「引擎 + 音色」定成确定的一对 `(引擎 id, 音色)`,给**点名不全**的一方(智能体)用。

    配音没有默认(`defaultable=False`),所以这里从不替人挑引擎 —— 挑中一个要钥匙的就是替他花钱。能做的只有两件:

    - 引擎按名字或 id 认(和字幕配音同一个认法,`capabilities.resolve_named`),认不出就把能用的 id 都列出来 ——
      模型写成 `edge-tts` 时,下一次就能写对,而不是被一句「没有这个引擎」打发走,转头让用户去设置里配一个
      根本不用配的东西(真机反馈);
    - 只给了音色时按音色认出引擎:音色是某一家的(Edge 的 `zh-CN-XiaoxiaoNeural`、这个工作区克隆出来的音色),
      引擎就是那一家。认不出、或者好几家都有,就说出来让他点名。

    点名的引擎得**现在**就能用(没配连接、克隆没装都在这里说),而不是等人批准之后任务才失败。
    """
    from app.domain import capabilities
    from app.domain.voices.voices import VoiceError

    engine, voice = (engine or "").strip(), (voice or "").strip()
    engines = speaking_engines(db, user_id, workspace_id)
    #: 只给了音色时按音色**本来的那一家**认:配音库里的嗓子本来是本机克隆的;远端引擎念它要上传、要花钱,得点名才走。
    voices_of = {one["id"]: [listed["id"] for listed in one["voices"] if not listed.get("cloned")] for one in engines}
    usable = [one for one in engines if one["ready"]]
    if engine:
        named = capabilities.resolve_named(db, user_id, CAPABILITY, engine)
        if named is None:
            raise SpeechProviderUnavailable(
                "speechErr_unknownEngineChoose",
                name=engine,
                choices=_engine_list(usable),
                free=_engine_list([one for one in usable if one["free"]]),
            )
        capabilities.pick(db, user_id, CAPABILITY, named.id)  # 缺什么(连接、本机引擎)当场说
        if not voice:
            sample = ", ".join(voices_of.get(named.id, [])[:6]) or "—"
            raise SpeechProviderUnavailable("speechErr_pickVoice", engine=named.id, voices=sample)
        # 克隆音色是这个工作区音色库里的一行;别家的音色是开放的(百炼认不出的模型退回填 id),合成时再说。
        if named.id == CLONE_ENGINE and voice not in voices_of[CLONE_ENGINE]:
            raise VoiceError("voiceErr_voiceNotInWorkspace")
        return named.id, voice
    if not voice:
        free = [one for one in usable if one["free"]]
        raise SpeechProviderUnavailable("speechErr_pickEngineAndVoice", choices=_engine_list(usable), free=_engine_list(free))
    owners = [one for one in engines if voice in voices_of[one["id"]]]
    if not owners:
        raise SpeechProviderUnavailable("speechErr_voiceWithoutEngine", voice=voice, choices=_engine_list(usable))
    ready_owners = [one for one in owners if one["ready"]]
    if len(ready_owners) > 1:
        raise SpeechProviderUnavailable("speechErr_voiceInSeveralEngines", voice=voice, choices=_engine_list(ready_owners))
    owner = (ready_owners or owners)[0]
    capabilities.pick(db, user_id, CAPABILITY, owner["id"])  # 认出来的那一家还用不了:说缺什么
    return owner["id"], voice


#: 只属于某一条路的附加项。另一条路收到它们会报"没有这个参数",所以按引擎挑着带。
_CLONE_OPTIONS = ("clone_engine", "clone_model")
_ENGINE_OPTIONS = ("provider_profile_id", "engine_model", "engine_voice_resource")


def synthesis_params(db: Session, *, engine: str, voice: str, speed: float = 1.0,
                     user_id: str | None, workspace_id: str, **options: object) -> dict[str, object]:
    """「引擎 + 一格音色」→ voices.start_synthesis 要的那组参数。念字的入口(工作流、智能体、
    字幕配音)都走这里,不各自拼。

    音色一格,按引擎分两种意思:克隆时是配音库里的音色 id(`voice_id`),其余是那个引擎的
    音色(`engine_voice`)—— 能复刻的引擎(CosyVoice)例外,它也念得了配音库里的嗓子,那一格是嗓子 id 时
    同样交 `voice_id`(ADR 0037)。两条路要的参数不是一个集合 —— 都塞过去,合成那边会收到它这条路上
    根本没有的参数。火山的音色还要一个资源族,调用方没给就**这里自己查**,不靠界面选音色时
    顺手存下。引擎那条要一个工作区来认领产出(克隆那条从 Voice 行上取)。
    `options` 是两条路各自的附加项(克隆权重、引擎连接/模型),不属于这条路的丢掉。
    """
    from app.domain.voices.voices import VoiceError

    engine = (engine or "").strip() or CLONE_ENGINE
    voice = (voice or "").strip()
    if not voice:
        raise VoiceError("voiceErr_noVoiceSelected")
    require_engine(db, engine, user_id=user_id)
    unknown = set(options) - set(_CLONE_OPTIONS) - set(_ENGINE_OPTIONS)
    if unknown:
        # 调用方的编程错误,不会到界面上。
        raise TypeError(f"synthesis_params got unknown options: {sorted(unknown)}")
    params: dict[str, object] = {"engine": engine, "speed": float(speed or 1.0)}
    clone = engine == CLONE_ENGINE
    for key in _CLONE_OPTIONS if clone else _ENGINE_OPTIONS:
        if options.get(key):
            params[key] = options[key]
    from app.db.models import Voice

    if clone:
        #: 音色 id 可能来自任何地方(上游节点的输出、模型填的参数)—— 收进这个工作区。
        row = db.get(Voice, voice)
        if row is None or row.workspace_id != workspace_id:
            raise VoiceError("voiceErr_voiceNotInWorkspace")
        params["voice_id"] = voice
    elif _clones_remotely(engine) and db.get(Voice, voice) is not None:
        #: 能复刻的引擎(CosyVoice)点的是配音库里的一把嗓子:合成时念它的远端副本(ADR 0037)。嗓子 id 是 32 位 hex,
        #: 和引擎自己的音色名(`longxiaochun_v2`)撞不上。
        if db.get(Voice, voice).workspace_id != workspace_id:
            raise VoiceError("voiceErr_voiceNotInWorkspace")
        params["voice_id"] = voice
        params["workspace_id"] = workspace_id
    else:
        params["engine_voice"] = voice
        params["workspace_id"] = workspace_id
        if not params.get("engine_voice_resource"):
            params["engine_voice_resource"] = voice_resource_for(db, engine, voice, user_id=user_id)
    return params


def voice_slot(engine: str, *, voice_id: str | None, engine_voice: str) -> str:
    """请求里分开的两格(`voice_id` / `engine_voice`)→ synthesis_params 收的那一格音色。

    克隆引擎取 `voice_id`;别的引擎取它自己的音色,没给而点了配音库里的嗓子(`voice_id`)时 —— 只有能复刻的引擎
    这样点 —— 取那把嗓子。字幕配音、画板念字、智能体的配音卡收的都是两格,各自判一遍的话,远端引擎点的嗓子会在其中一处被丢掉。
    """
    if (engine or CLONE_ENGINE) == CLONE_ENGINE:
        return voice_id or ""
    if engine_voice:
        return engine_voice
    return (voice_id or "") if _clones_remotely(engine) else ""
