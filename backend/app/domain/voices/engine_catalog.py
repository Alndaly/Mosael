"""引擎目录:界面挑引擎时看到的那一份。

不在 `ai/providers/contracts/speech.py` 里,因为它要读**本地模型的就绪状态**(clone 引擎装没装、
百炼当前配的是哪个模型)—— 那是 `audio` 与 `domain` 的事。搬过去会让 `ai` 反过来依赖
`audio`,和既有的 `audio → ai` 撞成环(见 tests/test_import_layering)。

界线因此是清楚的:**"怎么跟这家说话"在 ai,"这个部署现在能用什么"在这里。**

配音是一项宿主能力(ADR 0032 第四步):id、契约和插件协议见 `voices.speech`;这里列的是界面上挑引擎看的那一份。
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from sqlalchemy.orm import Session

from app.domain.voices.speech import (
    BUILTIN_PREFIX,
    CAPABILITY,
    CLONE_ENGINE,
    LOCAL_SPEECH_ENGINES,
    PODCAST_ENGINE,
    QWEN_ENGINE,
    SpeechProviderUnavailable,
    adapter_id,
    engine_ready,
    is_plugin,
    known_engine,
    require_engine,
)
from mosael_formats.plugin_manifest import SPEECH

from app.ai.providers import (
    REMOTE_SPEECH_ADAPTERS,
    SpeechCatalogError,
    VoiceCatalogContext,
    VoiceOption,
    builtin_voice,
    connection_vendor_for_speech_engine,
    engine_voices,
    podcast_engine,
    speech_engines,
)

from app.domain.voices.voice_labels import builtin_voice_label
from app.ai.runtime import config as tts_config, qwen_models, tts_models
from app.core.i18n import fragment, tr
from app.db.models import Voice
from app.domain.consent import UNDECLARED
from app.domain.plugins import runtime as plugins_runtime, tools as plugins_tools
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.runtime import PluginRuntimeError
from app.domain.providers import selection as providers_selection
from app.domain.voices import defaults as voice_defaults
from app.domain.voices.defaults import resolve_voice_default
from app.domain.voices.errors import VoiceError
from app.domain.voices.remote import clones_remotely
from app.domain.voices.voice_ref import VoiceRef
from app.domain.voices.voices import list_voices

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
            found = provider_models.first_model_of_family(db, profile, "tts", prefixes)
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

    # **不等探测**:这个接口只是"引擎选择器要什么",而探测要起子进程 import torch。
    # 没测过时按"还没就绪"渲染,后台探完下一次拉列表就对了(见 tts_models.runtime_status)。
    clone_ready, _checked = tts_models.runtime_status(tts_config.get().engine)
    # 响应模型里 `ready` 是 bool:没测过时按 False 渲染(理由见 describe_engines 的说明)。
    qwen_ready = bool(local_engine_ready(LOCAL_SPEECH_ENGINES[QWEN_ENGINE]))
    engines: list[dict[str, object]] = [
        {
            "id": CLONE_ENGINE,
            "label": "ttsProvider_clone",
            "needs_key": False,
            # 本地克隆按**模型**定(F5 的 infer 吃 speed,fish 的请求里根本没这项),真正的答案在
            # tts_models 那份 speed_control(界面读克隆运行环境那一行);这一行只是占位,不当判据。
            "speed_control": "native",
            "needs_voice_id": False,
            "voices": [],
            "ready": clone_ready,
            "note": "ttsProviderNote_cloneReady" if clone_ready else "ttsProviderNote_cloneMissing",
        },
        {
            # 本机念字引擎:**不是克隆**。9 个预置音色、文本进音频出;语言支持由模型决定
            # (中文/英文/日文/韩文/德文/法文/俄文/葡文/西文/意文),界面照这份表列,不假装更多。
            "id": QWEN_ENGINE,
            "label": "ttsProvider_qwen",
            "needs_key": False,
            # generate_custom_voice 没有语速参数(它靠 instruct 控节奏,而界面没有这一格):宿主合成之后变速。
            "speed_control": tts_models._BY_ID[qwen_models.ENGINE_ID].speed_control,
            "needs_voice_id": False,
            "voices": [voice.id for voice in _preset_voices()],
            "ready": qwen_ready,
            "note": "ttsProviderNote_qwenReady" if qwen_ready else "ttsProviderNote_qwenMissing",
        },
        #: 内置的念字引擎照 Registry 列,每一家的目录信息由它自己在契约上声明(ADR 0086)。
        *(
            {
                "id": f"{BUILTIN_PREFIX}{engine.engine_id}",
                "label": engine.label_key,
                "needs_key": engine.needs_key,
                "speed_control": engine.speed_control,
                "needs_voice_id": engine.needs_voice_id,
                #: 音色随模型变的那几家(百炼)按这个人那条连接上配的模型给;认不出的模型回空,界面退回填 id。
                #: 这里只要 id、不按账号现拉(那要一次签名请求):整份清单在 list_engine_voices。
                "voices": [voice.id for voice in engine.voices(VoiceCatalogContext(model=active_model_for(engine, user_id)))],
                "note": engine.note_key,
            }
            for engine in speech_engines()
        ),
        {
            "id": PODCAST_ENGINE,
            "label": podcast_engine().label_key,
            "needs_key": True,
            "speed_control": "native",
            "needs_voice_id": False,
            "voices": [speaker.id for speaker in podcast_engine().speakers],
            "note": podcast_engine().note_key,
        },
    ]
    for engine in engines:
        engine.setdefault("ready", engine_ready(db, adapter_id(str(engine["id"])), bool(engine["needs_key"]), user_id))
        #: 能不能念配音库里的克隆音色(复刻上去),问注册表 —— 不在这张表里再写一遍是哪一家。
        engine["clones_voices"] = _clones_remotely(str(engine["id"]))
    return engines + _plugin_engines(db, user_id)


def engine_label(db: Session, engine: str, user_id: str | None) -> str:
    """一个配音引擎给人看的名字(按当前语言)。不问插件要音色 —— 只认名字,所以不起插件调用。认不出就是 id 本身。"""

    for row in describe_engines(None, user_id):
        if row["id"] == engine:
            return tr(str(row["label"]))
    if is_plugin(engine):
        from app.domain import capabilities

        for provider in capabilities.plugin_providers(db, user_id, CAPABILITY):
            if provider.id == engine:
                return provider.name
    return engine


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
            #: 插件的 `speak` 收 `speed`(协议见 voices.speech),由插件自己调。
            "speed_control": "native",
            "needs_voice_id": False,
            "voices": [voice.id for voice in _plugin_voices(db, provider)] if ready else [],
            "ready": ready,
            "note": "",
            "plugin": True,
        })
    return found


def _plugin_voices(db: Session, provider) -> list[VoiceOption]:
    """插件连接能念的音色(`op: voices`)。问不到就是空清单,原因记进日志 —— 一个坏插件不该让引擎下拉整个拉不出来。"""

    try:
        #: 音色清单是**目录类回答**(这个引擎 / 账号里能念的音色,随音色数线性变大):和工具清单 / 模型清单 /
        #: 模型库 / 工作流库 / 节点包同一份预算(见 runtime.CATALOG_OUTPUT_BYTES)。别的插件调用一个字节都没放宽。
        output = plugins_tools.invoke_host(db, provider.id, SPEECH, {"op": "voices"}, record=False,
                             output_budget=plugins_runtime.CATALOG_OUTPUT_BYTES)
    except (PluginDomainError, PluginRuntimeError) as exc:
        logger.info("speech plugin %s voices unavailable: %s", provider.id, exc)
        return []
    voices = output.get("voices") if isinstance(output, dict) else None
    return [
        VoiceOption(str(voice.get("id")), str(voice.get("name") or voice.get("id")))
        for voice in (voices if isinstance(voices, list) else [])
        if isinstance(voice, dict) and voice.get("id")
    ]


def list_engine_voices(db: Session, engine: str, *, user_id: str | None, workspace_id: str = "") -> list[VoiceOption]:
    """一个引擎能念的音色 —— **音色目录的唯一合并点**(ADR 0087)。

    引擎自己的那份来自它的音色目录(内置的照表;百炼按模型;火山配了 AK/SK 按账号现拉,资源族在 `extra` 里);
    本机预置的(Qwen3-TTS)和插件的由这里接上。带了工作区、而这个引擎能复刻(CosyVoice)时,后面再接一组这个工作区
    配音库里的克隆音色(`source="cloned"`,ADR 0037)—— 选它时请求带 `voice_id`,宿主在合成前把它解析成远端副本。
    """
    stock = _engine_voices(db, engine, user_id=user_id)
    if workspace_id and _clones_remotely(engine):
        stock = stock + cloned_voices(db, workspace_id)
    return stock


def set_default_voice(db: Session, choice: VoiceRef | None) -> VoiceRef | None:
    """把这台机器的默认定成这一把嗓子,校验放在这里;`None` = 清掉默认。

    **只许设现在就能跑的引擎、并且音色必须属于它**:设完下一次念字就得先下载 / 先配连接的"默认",
    和没设没有区别,只是屏幕上多了一句承诺。音色和引擎不是一对时也当场拒 —— 那正是这个功能存在的
    理由(引擎和音色是成对选的)。

    只收内置引擎的**引擎音色**(插件连接属于某个人,不是这台机器的资产;配音库的克隆音色归某个工作区,不在这台机器的
    默认里);音色清单和界面下拉同一个产地(`check_voice` → 音色目录)。

    不提交,由入口提交(和 `capabilities.set_default`、`denoise_defaults.set_default_engine` 同一套)。
    解析与存储在 `domain/voices/defaults`;本模块只负责问音色目录这一半。
    """
    from app.domain import capabilities

    if choice is None:
        return voice_defaults.store_default(db, None)
    #: 部署默认只可能是内置引擎:插件连接在 provider 列表里要靠"谁"才拿得到,这里不传人。
    found = next((one for one in capabilities.providers(db, None, CAPABILITY) if one.id == choice.engine), None)
    if found is None:
        raise voice_defaults.UnknownVoiceEngine(choice.engine)
    if found.missing:
        raise voice_defaults.VoiceEngineNotReady(found.name, tr("punct_listSep").join(found.missing))
    if choice.cloned_voice or choice.engine == CLONE_ENGINE:
        raise voice_defaults.VoiceMissing(found.id, [])
    return voice_defaults.store_default(db, check_voice(db, choice, user_id=None))


def _clones_remotely(engine: str) -> bool:

    return clones_remotely(engine)


def cloned_voices(db: Session, workspace_id: str) -> list[VoiceOption]:
    """这个工作区配音库里**能复刻出去**的嗓子(声明过是谁的;没声明的不往外传,ADR 0028 §5)。"""
    from sqlalchemy import select


    rows = db.scalars(
        select(Voice)
        .where(Voice.workspace_id == workspace_id, Voice.consent_kind != UNDECLARED)
        .order_by(Voice.created_at)
    )
    return [VoiceOption(row.id, row.name, source="cloned") for row in rows]


def _engine_voices(db: Session, engine: str, *, user_id: str | None, model: str = "") -> list[VoiceOption]:
    """引擎**自己的**音色(不含配音库里的克隆音色)。

    每一家的清单只有一个产地:它自己的音色目录。这里只决定**问的时候带什么**(模型、这个人那条连接)——
    带什么必须和合成时同一条路径,否则下拉列的是 A 的音色、发出去的是 B 的请求。`model`:选择上已经写了模型时
    按它问(百炼的音色随模型变);空 = 这个人那条连接上配的那个。
    """

    if is_plugin(engine):
        from app.domain import capabilities

        provider = next((one for one in capabilities.plugin_providers(db, user_id, CAPABILITY) if one.id == engine), None)
        return _plugin_voices(db, provider) if provider is not None and not provider.missing else []
    if engine == QWEN_ENGINE:
        return _preset_voices()
    if engine == PODCAST_ENGINE:
        return list(podcast_engine().speakers)
    engine = adapter_id(engine)
    engine_cls = REMOTE_SPEECH_ADAPTERS.get(engine)
    if engine_cls is None:
        # 本机克隆念的是配音库里的嗓子(另一个下拉),认不出的引擎没有音色。
        return []
    context = _catalog_context(db, engine_cls, user_id=user_id, model=model)
    try:
        return engine_voices(engine, context)
    except SpeechCatalogError as exc:
        # 按账号现拉没成(火山):退回内置清单,用户照样能念;原因记日志,不让下拉坏掉。
        logger.info("%s live voice list unavailable: %s", engine, exc)
        return engine_voices(engine, VoiceCatalogContext(model=context.model))


def _catalog_context(db: Session, engine_cls: type, *, user_id: str | None, model: str = "") -> VoiceCatalogContext:
    """问一家音色目录时带上什么:音色随模型变的(百炼)带这个人配的模型,要钥匙的带**他自己**那条连接的附加字段
    (密字段跟着他的钥匙走,见 domain/providers/credentials)。"""

    if getattr(engine_cls, "MODEL_PREFIXES", ()):
        model = model or active_model_for(engine_cls, user_id)
    else:
        model = ""
    if not engine_cls.needs_key:
        return VoiceCatalogContext(model=model)
    connection = providers_selection.resolve_connection(
        db, connection_vendor_for_speech_engine(engine_cls.engine_id), user_id=user_id
    )
    return VoiceCatalogContext(model=model, connection_extra=connection.extra if connection else {})


def _preset_voices() -> list[VoiceOption]:
    """本机 Qwen3-TTS 的预置音色。语言是模型卡上写的每个音色的母语(它也念得了别的九种)。"""

    return [
        VoiceOption(speaker.id, speaker.label, source="preset",
                    languages=(speaker.native_language,) if speaker.native_language else ())
        for speaker in qwen_models.SPEAKERS
    ]


def local_engine_ready(engine_id: str) -> bool | None:
    """本机引擎跑不跑得起来:**解释器 import 得动 + 权重在盘上**,两样都要。

    True 跑得起来,False 已知跑不起来(没有运行环境、或权重没下),None 还没测过。
    只读已经测过的结果,不在请求里起探测(起子进程 import torch 要十几秒)。
    """

    ready, known = tts_models.runtime_status(engine_id)
    if known and not ready:
        return False
    if ready and not tts_models.is_installed(engine_id):
        return False
    return True if ready else None


def clone_engine_ready() -> bool | None:
    """本机克隆引擎(配音库的音色走它)跑不跑得起来。判据同上,只是引擎取配置里那个默认。"""

    return local_engine_ready(tts_config.get().engine)


def cloned_voice_status(db: Session, workspace_id: str, *, digital_human: bool = False) -> str:
    """这个工作区的配音库里有没有**能用的**克隆音色:`met` 有、而且克隆引擎跑得起来;`missing` 没有音色或引擎已知
    跑不起来;`unknown` 有音色、引擎还没测过。`digital_human`:要交给数字人的，只算声明过是谁的那几把(ADR 0028 §5)。

    模板的前置检查、建图时预填音色、配音节点说「用的是哪把嗓子」用的都是这一个判据。
    """
    from sqlalchemy import select


    if not workspace_id:
        return "missing"
    query = select(Voice.id).where(Voice.workspace_id == workspace_id)
    if digital_human:
        query = query.where(Voice.consent_kind != UNDECLARED)
    if db.scalar(query.limit(1)) is None:
        return "missing"
    ready = clone_engine_ready()
    return "missing" if ready is False else "met" if ready else "unknown"


def voice_note(db: Session, voice: VoiceRef, *, workspace_id: str, user_id: str | None) -> str:
    """「这次配音用的是哪把嗓子」—— 按**实际**念的那一把说的一句话(配音节点的 `voice_note`,完成通知里用)。

    用的不是克隆音色时,顺带说清楚配音库里有没有能用的克隆音色(判据和模板预填音色同一个,见
    cloned_voice_status):此前带货口播的那句是建图时写死的,之后在节点里换上克隆音色,通知照样说 Edge。
    """

    if voice.engine == CLONE_ENGINE:
        row = db.get(Voice, voice.cloned_voice) if voice.cloned_voice else None
        return tr("wfVoice_cloned", name=row.name if row is not None else voice.cloned_voice)
    entry = next((one for one in describe_engines(db, user_id) if one["id"] == voice.engine), None)
    label = str(entry["label"]) if entry is not None else voice.engine
    #: 带上工作区:CosyVoice 念的可能是配音库里的嗓子(ADR 0037),那时说它的名字,不说一串 id。
    named = {one.id: one.label for one in list_engine_voices(db, voice.engine, user_id=user_id, workspace_id=workspace_id)}
    spoken = str(named.get(voice.spoken, voice.spoken)).split("(")[0].strip() or voice.spoken
    has_clone = cloned_voice_status(db, workspace_id) != "missing"
    return tr("wfVoice_engineCloneReady" if has_clone else "wfVoice_engineNoClone", voice=spoken, engine=fragment(label))


def speaking_engines(db: Session, user_id: str | None, workspace_id: str) -> list[dict[str, Any]]:
    """念一句话能用的引擎,各带着自己的音色(id + 名字)—— 给**不看界面的那一方**(智能体)挑引擎用。

    和界面那份目录(describe_engines)同一个产地,只是换成读得懂的形状:名字、说明翻好,音色带上名字,克隆那一项
    的音色是**这个工作区**音色库里的(界面上那一项的音色另有一个下拉)。播客不在其中 —— 它不念一句话。
    """

    found: list[dict[str, Any]] = []
    for engine in describe_engines(db, user_id):
        if engine["id"] == PODCAST_ENGINE:
            continue
        if engine["id"] == CLONE_ENGINE:
            voices = [{"id": voice.id, "name": voice.name} for voice in list_voices(db, workspace_id)]
        else:
            voices = [{"id": str(voice), "name": builtin_voice_label(str(voice)) or str(voice)} for voice in engine["voices"]]
            if _clones_remotely(str(engine["id"])):
                #: 能复刻的引擎(CosyVoice)也念得了配音库里的嗓子(念它的远端副本,第一次要用户同意上传)。
                voices += [{"id": one.id, "name": one.label, "cloned": True} for one in cloned_voices(db, workspace_id)]
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

    return tr("punct_listSep").join(f"{one['id']} ({one['name']})" for one in engines) or "—"



def pick_speech(db: Session, *, engine: str, voice: str, user_id: str | None, workspace_id: str) -> tuple[str, str]:
    """「引擎 + 音色」定成确定的一对 `(引擎 id, 音色)`,给**点名不全**的一方(智能体)用。

    两格都空时先问这台机器的默认那一把(`domain/voices/defaults`,经 `voice_for_synthesis`);没有默认才
    退回原来的"必须点名"。能做的还有两件:

    - 引擎按名字或 id 认(和字幕配音同一个认法,`capabilities.resolve_named`),认不出就把能用的 id 都列出来 ——
      模型写成 `edge-tts` 时,下一次就能写对,而不是被一句「没有这个引擎」打发走,转头让用户去设置里配一个
      根本不用配的东西(真机反馈);
    - 只给了音色时按音色认出引擎:音色是某一家的(Edge 的 `zh-CN-XiaoxiaoNeural`、这个工作区克隆出来的音色),
      引擎就是那一家。认不出、或者好几家都有,就说出来让他点名。

    点名的引擎得**现在**就能用(没配连接、克隆没装都在这里说),而不是等人批准之后任务才失败。
    """
    from app.domain import capabilities

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
        #: 两格都没点名:先问默认那一对(唯一解析点见 domain/voices/defaults)。没有默认就照旧要求点名 ——
        #: 行为和这一格出现之前完全一样。经 voice_for_synthesis 走,是为了"默认"只有一份解析。
        try:
            defaulted = voice_for_synthesis(db, None, user_id=user_id, workspace_id=workspace_id)
        except VoiceError:
            defaulted = None
        if defaulted is not None:
            return defaulted.engine, defaulted.spoken
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


def voice_choice(db: Session, *, engine: str, voice: str, model: str = "", connection: str = "",
                 user_id: str | None) -> VoiceRef | None:
    """「引擎 + 一格音色」(界面以外的点名:智能体的卡、工作流节点、画板条目)→ 一个定好的 `VoiceRef`;两格都空 = `None`
    (交给默认,见 `voice_for_synthesis`)。

    那一格按引擎分两种意思:克隆引擎是配音库里的嗓子(`cloned_voice`),别的引擎是它自己的音色(`voice`)—— 能复刻的引擎
    (CosyVoice)例外,那一格是配音库里的嗓子时同样是 `cloned_voice`(ADR 0037;嗓子 id 是 32 位 hex,和引擎自己的音色名撞不上)。
    只给了音色、没给引擎就是配音库里的(那是「一把嗓子」最常见的来处)。只给了引擎、没给音色,等于没选。

    定好之后照音色目录补上 `extra` 和模型(`settle_voice`):点名的那一方只知道两串字,资源族、绑定的模型是目录的知识。
    """
    engine, voice = (engine or "").strip(), (voice or "").strip()
    if not voice:
        if engine:
            raise VoiceError("voiceErr_noVoiceSelected")
        return None
    engine = engine or CLONE_ENGINE
    library = engine == CLONE_ENGINE or (_clones_remotely(engine) and db.get(Voice, voice) is not None)
    choice = VoiceRef(engine, voice="" if library else voice, cloned_voice=voice if library else "",
                      model=(model or "").strip(), connection=(connection or "").strip())
    return settle_voice(db, choice, user_id=user_id)


def settle_voice(db: Session, choice: VoiceRef, *, user_id: str | None) -> VoiceRef:
    """照音色目录把选择补齐:`extra`(火山的资源族)原样从那一项带过来;那一项绑模型、选择上又没写模型时,写下这一刻
    问目录用的那个模型(ADR 0087 §3「模型绑定的音色必须带模型」)。

    目录里没有这一项(插件没答、百炼认不出的模型、火山没拉到账号清单)就原样交回 —— 这里只补,不拒;拒在写入时的 `check_voice`。
    """
    if choice.cloned_voice:
        return choice
    option, model = _option_of(db, choice, user_id=user_id)
    if option is None:
        return choice
    return replace(choice, extra=dict(option.extra), model=choice.model or (model if option.models else ""))


def check_voice(db: Session, choice: VoiceRef, *, user_id: str | None, workspace_id: str = "") -> VoiceRef:
    """**写入时**的校验(设默认、存朗读偏好、存人物资产的音色):返回补齐之后要存的那一把。

    - 引擎得是能力表认得的(拼错了、或者根本不是 `speech` 的一份实现,当场说);
    - 克隆音色要在这个工作区、而且这个引擎念得了它(本机克隆,或能复刻的远端引擎);
    - 引擎音色要在它的目录里(目录是空的 —— 插件没答、百炼认不出的模型 —— 就不拦:那时界面本来就让人手填 id);
    - 目录说这把嗓子只在某几个模型上能念,而选择上写的是别的模型:拒,不悄悄换模型。

    存之前就说,而不是等下一次合成才失败。远端副本的上传同意不在这里问(只有朗读偏好要,见 use_cases)。
    """
    if not known_engine(db, choice.engine):
        raise voice_defaults.UnknownVoiceEngine(choice.engine)
    if choice.cloned_voice:
        if choice.engine != CLONE_ENGINE and not _clones_remotely(choice.engine):
            raise VoiceError("voiceErr_clonedVoiceOnEngine", engine=choice.engine)
        row = db.get(Voice, choice.cloned_voice)
        if row is None or (workspace_id and row.workspace_id != workspace_id):
            raise VoiceError("voiceErr_voiceNotInWorkspace")
        return choice
    if choice.engine == CLONE_ENGINE:
        raise VoiceError("voiceErr_voiceNotInWorkspace")
    listed = _engine_voices(db, choice.engine, user_id=user_id, model=choice.model)
    option = next((one for one in listed if one.id == choice.voice), None)
    if listed and option is None:
        raise voice_defaults.VoiceNotInEngine(choice.voice, choice.engine)
    settled = settle_voice(db, choice, user_id=user_id)
    _refuse_model_mismatch(settled, option)
    return settled


def voice_for_synthesis(db: Session, choice: VoiceRef | None, *, user_id: str | None, workspace_id: str) -> VoiceRef:
    """**合成前**的那一把:点名了就用点名的,没点名问默认(`defaults.resolve_voice_default`,唯一解析点);都没有就说
    「没有选音色」。念字的入口(工作流、智能体、字幕配音、创作页、试听)都走这里,不各自拼。

    这一刻再查一遍不花钱的那几样:引擎现在能用(缺连接、本机引擎没装,当场说)、克隆音色在这个工作区(音色 id 可能来自
    任何地方:上游节点的输出、模型填的参数)、内置目录说的模型绑定还对得上。**不现拉账号清单** —— 每次合成都走这里。
    """
    choice = choice or resolve_voice_default(db, user_id)
    if choice is None:
        raise VoiceError("voiceErr_noVoiceSelected")
    require_engine(db, choice.engine, user_id=user_id)
    if choice.cloned_voice:
        if choice.engine != CLONE_ENGINE and not _clones_remotely(choice.engine):
            raise VoiceError("voiceErr_clonedVoiceOnEngine", engine=choice.engine)
        row = db.get(Voice, choice.cloned_voice)
        if row is None or row.workspace_id != workspace_id:
            raise VoiceError("voiceErr_voiceNotInWorkspace")
    elif choice.engine == CLONE_ENGINE:
        raise VoiceError("voiceErr_voiceNotInWorkspace")
    elif not is_plugin(choice.engine) and choice.engine not in (QWEN_ENGINE, PODCAST_ENGINE):
        _refuse_model_mismatch(choice, builtin_voice(adapter_id(choice.engine), choice.voice))
    return choice


def _refuse_model_mismatch(choice: VoiceRef, option: VoiceOption | None) -> None:
    """目录上这把嗓子只在某几个模型(族)上能念,而选择上写的是别的模型 —— 「这把嗓子用不了」,不悄悄换模型。"""
    if option is None or not option.models or not choice.model:
        return
    if not choice.model.strip().lower().startswith(tuple(model.lower() for model in option.models)):
        raise VoiceError("voiceErr_voiceNotForModel", voice=option.label, model=choice.model,
                         models=tr("punct_listSep").join(option.models))


def _option_of(db: Session, choice: VoiceRef, *, user_id: str | None) -> tuple[VoiceOption | None, str]:
    """这把嗓子在它引擎的目录里是哪一项,以及问目录时用的模型(百炼按模型给音色)。"""
    engine_cls = REMOTE_SPEECH_ADAPTERS.get(adapter_id(choice.engine)) if not is_plugin(choice.engine) else None
    model = choice.model
    if engine_cls is not None and getattr(engine_cls, "MODEL_PREFIXES", ()):
        model = model or active_model_for(engine_cls, user_id)
    listed = _engine_voices(db, choice.engine, user_id=user_id, model=model)
    return next((one for one in listed if one.id == choice.voice), None), model
