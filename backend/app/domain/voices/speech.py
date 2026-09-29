"""配音这项宿主能力的 id 与契约(ADR 0032 第四步)。

叶子模块:`engine_catalog`(界面挑引擎看的那份目录)和 `voices`(合成)都依赖它,它不依赖它们 —— 此前常量住在
engine_catalog 里,voices 要用就得回头 import 它,而 engine_catalog 又要 import voices,成了环。

内置引擎的 id 是 `builtin:<适配器名>`(`builtin:edge`);`ai` 层的适配器认裸名,`adapter_id` 摘前缀。插件连接的 id
没有前缀(`is_plugin`)。

配音是一项**宿主能力**(ADR 0032 第四步):本机克隆、Edge、OpenAI、火山、百炼这几家是内置提供方
(`builtin:clone`、`builtin:edge`……),认领 `speech` 的插件连接和它们并列。和别的能力不同,**配音没有默认**:
引擎和音色是成对选的(克隆音色的 id 换到 Edge 上就是错的),每个入口都点名(`defaultable=False`)。

**插件协议**(只经宿主调,普通工具,按 `op` 分两件事):

- `{"op": "voices"}` → `{"voices": [{"id": "…", "name": "…"}]}`:这个连接能念的音色,界面的音色下拉照它列;
- `{"op": "speak", "text": "…", "voice": <音色 id>, "speed": 1.0}` → `{"audio": <暂存目录里一份音频的相对路径>}`。

登记成素材、记出处、贴到时间线都是宿主的事。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai.providers import (
    BailianSpeechAdapter,
    CosyVoiceSpeechAdapter,
    EdgeSpeechAdapter,
    OpenAISpeechAdapter,
    VolcanoSpeechAdapter,
    connection_vendor_for_speech_engine,
)
from app.core.i18n import tr
from app.domain.capabilities import Builtin, Capability, CapabilityUnavailable
from app.domain.plugins.manifest import SPEECH

BUILTIN_PREFIX = "builtin:"
#: 「克隆音色」这一项。没选引擎时按它算。
CLONE_ENGINE = f"{BUILTIN_PREFIX}clone"
EDGE_ENGINE = f"{BUILTIN_PREFIX}{EdgeSpeechAdapter.engine_id}"
#: 播客引擎:一次产出一整段双人对话,不是"念一句话"那种 —— 念字的地方都不该列它,也不进配音能力。
PODCAST_ENGINE = f"{BUILTIN_PREFIX}volcano-podcast"


class SpeechProviderUnavailable(CapabilityUnavailable):
    """点名的配音引擎用不了(没这一家、没配好)。"""


def _clone_ready(_db: Session, _owner: str | None) -> tuple[str, ...]:
    from app.ai.runtime import config as tts_config
    from app.ai.runtime import tts_models

    ready, _checked = tts_models.runtime_status(tts_config.get().engine)
    return () if ready else (tr("ttsProviderNote_cloneMissing"),)


def _connection_ready(engine: str):
    """要钥匙的远端引擎:**这个人**配好了那条连接才算(钥匙归人)。"""

    def missing(db: Session, owner: str | None) -> tuple[str, ...]:
        return () if engine_ready(db, engine, True, owner) else (tr("speechHint_noConnection"),)

    return missing


CAPABILITY = Capability(
    name=SPEECH,
    label_key="capability_speech",
    description_key="capability_speech_desc",
    error=SpeechProviderUnavailable,
    unknown_key="speechErr_unknownEngine",
    incomplete_key="speechErr_engineNotReady",
    builtins=(
        Builtin(id=CLONE_ENGINE, name_key="ttsProvider_clone", ready=_clone_ready),
        Builtin(id=EDGE_ENGINE, name_key=EdgeSpeechAdapter.label_key),
        *(Builtin(id=f"{BUILTIN_PREFIX}{cls.engine_id}", name_key=cls.label_key, ready=_connection_ready(cls.engine_id))
          for cls in (OpenAISpeechAdapter, VolcanoSpeechAdapter, BailianSpeechAdapter, CosyVoiceSpeechAdapter)),
    ),
    auto_single=False,
    defaultable=False,
)


def register_uses() -> None:
    """宿主界面上用到配音的入口(ADR 0032 §4)。工作流节点由注册表现扫。"""
    from app.core.i18n import fragment
    from app.domain.capabilities import Use, register_use

    register_use(Use(SPEECH, "app", fragment("capUse_studioSpeech")))
    register_use(Use(SPEECH, "app", fragment("capUse_subtitleDub")))
    register_use(Use(SPEECH, "app", fragment("capUse_boardSpeak")))


def require_engine(db: Session, engine: str, *, user_id: str | None) -> None:
    """点名的引擎在不在这个人的候选里:内置的总在;插件连接得是他自己的、声明了 `speech` 的。
    配没配好由合成那一步说(那是任务的结果)。"""
    from app.domain import capabilities

    if engine.startswith(BUILTIN_PREFIX) and engine != PODCAST_ENGINE:
        if any(one.id == engine for one in CAPABILITY.builtins):
            return
    elif any(one.id == engine for one in capabilities.plugin_providers(db, user_id, CAPABILITY)):
        return
    raise SpeechProviderUnavailable(CAPABILITY.unknown_key, name=engine)


def known_engine(db: Session, engine: str) -> bool:
    """这个引擎认不认得:内置的念字引擎,或一个声明了 `speech` 的插件连接(谁的都行 —— 实体是工作区里的,
    连接归人;挑的那一刻再按人判能不能用)。播客不算:它不念一句话。"""
    if any(one.id == engine for one in CAPABILITY.builtins):
        return True
    if engine.startswith(BUILTIN_PREFIX):
        return False
    from app.db.models import PluginInstance
    from app.domain.plugins import instances as inst

    instance = db.get(PluginInstance, engine)
    return instance is not None and SPEECH in inst.manifest_for(db, instance).provides


def adapter_id(engine: str) -> str:
    """能力表里的内置引擎 id → `ai` 层适配器认的裸引擎名(`builtin:edge` → `edge`)。"""
    return engine.removeprefix(BUILTIN_PREFIX)


def is_plugin(engine: str) -> bool:
    """点名的是一个插件连接(不是内置引擎)。"""
    return bool(engine) and not engine.startswith(BUILTIN_PREFIX)


def engine_ready(db: Session | None, engine_id: str, needs_key: bool, user_id: str | None) -> bool:
    """这个引擎**现在**能不能用 —— 不出网就能回答。

    三种情况:本机克隆看装没装(上面已经探过);不要钥匙的(Edge)随时能用;要钥匙的要看
    **这个人**有没有配好那条连接 —— 钥匙归人(见 domain/provider_credentials),别人配过不算。
    """
    if not needs_key:
        return True
    if db is None:
        return False
    from app.domain.providers import resolve_connection

    vendor = connection_vendor_for_speech_engine(engine_id)
    connection = resolve_connection(db, vendor, user_id=user_id)
    return connection is not None and bool(connection.api_key or connection.extra)


__all__ = [
    "BUILTIN_PREFIX",
    "CAPABILITY",
    "CLONE_ENGINE",
    "EDGE_ENGINE",
    "PODCAST_ENGINE",
    "SPEECH",
    "SpeechProviderUnavailable",
    "adapter_id",
    "engine_ready",
    "is_plugin",
    "known_engine",
    "register_uses",
    "require_engine",
]
