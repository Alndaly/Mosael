"""配音默认那一把嗓子(`VoiceRef`)的读、写,以及「这一次到底用哪一把」的**唯一**解析点。

## 默认是一把嗓子,不是一次单选

配音的引擎和音色是**成对**选的:克隆音色的 id 换到 Edge 上就是错的,Edge 的 `zh-CN-XiaoxiaoNeural`
换到火山也一样;音色绑模型的(百炼)还要连模型一起记。所以这张单例表存一个 `VoiceRef`(ADR 0087),设的时候
整把一起校验 —— 一个只有引擎的"默认"在真正念的时候仍然得让人再点一次音色,那不是默认,只是一句承诺。

## 两层,谁也不是谁的替代(和转写 / 降噪同一条规则)

- **部署默认**(本模块,`VoiceDefaultConfig`):这台机器默认那一对。引擎装没装、默认念什么声音,对所有
  用户是同一件事,所以写它只给部署管理员 —— 和装引擎同一道门。
- **按人选的**(设置 → 能力提供方 → 配音):某个人自己定过的那一台**引擎**(通用那一条存的是提供方 id)。
  他做的选择比部署的默认更具体,所以压过它。它是**覆盖**,不是另一份默认。

实际生效的顺序(从上到下):

1. **这次入口点名的**那一把(工作流节点的引擎 + 音色、智能体卡上定好的那一对、界面上选的);
2. **这个人自己**在「能力提供方 → 配音」定过的引擎 —— 部署默认的音色只在**同一家引擎**时跟着用
   (克隆音色的 id 换到 Edge 上就是错的,不能硬套);换了别家时音色留空,交给现有的「必须点名音色」;
3. 部署默认那一把(本模块);
4. 空:交给现有的"必须点名"逻辑(`speechErr_pickEngineAndVoice` / `voiceErr_noVoiceSelected`),
   行为和这一格出现之前完全一样。

**有效值只在这里算一次**(`resolve_voice_default`)。所有念字的入口都经过
`engine_catalog.voice_for_synthesis`,没点名时它先问这里 —— 谁要是自己在别处再拼一份,迟早出现
设置页写着一对、念出来的是另一对,而用户看到的是「设了却没生效」。

**部署默认只收内置引擎**(和降噪同一条):插件连接需要某个人自己的授权和钥匙,不是这台机器的资产。
「按人选的那一家」仍然可以是插件。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError, tr
from app.db.models import VoiceDefaultConfig
from app.domain import capabilities
from app.domain.voices.speech import CAPABILITY
from app.domain.voices.voice_ref import VoiceRef

#: 单例行只有一个 id。
SINGLETON_ID = "default"


class VoiceDefaultError(LocalizedError, RuntimeError):
    """设默认被拒。子类各自对应一个 HTTP 状态 —— 都是输入的问题,不是服务端故障。"""


class UnknownVoiceEngine(VoiceDefaultError):
    """能力表里没有这个提供方 id(拼错了,或者根本不是 `speech` 的一份实现)。"""

    def __init__(self, engine: str) -> None:
        super().__init__("speechErr_unknownEngine", name=engine)


class VoiceEngineNotReady(VoiceDefaultError):
    """这台机器上用不了这个引擎(没装本机引擎、要钥匙的那家还没配连接)—— 缺什么原样说出来。"""

    def __init__(self, engine: str, missing: str) -> None:
        super().__init__("speechErr_engineNotReady", plugin=engine, missing=missing)


class VoiceMissing(VoiceDefaultError):
    """只给了引擎,没给音色 —— 默认必须是一对。"""

    def __init__(self, engine: str, voices: list[str]) -> None:
        sample = tr("punct_listSep").join(voices[:6]) or "—"
        super().__init__("speechErr_pickVoice", engine=engine, voices=sample)


class VoiceNotInEngine(VoiceDefaultError):
    """音色不属于那个引擎(火山的音色拿到 Edge 上就是错的)—— 设的时候就说,不等下一次合成。"""

    def __init__(self, voice: str, engine: str) -> None:
        super().__init__("routeErr_voiceNotInEngine", voice=voice, engine=engine)


def default_voice(db: Session) -> VoiceRef | None:
    """这台机器设的默认那一把嗓子;没设过是 `None`。"""
    row = db.get(VoiceDefaultConfig, SINGLETON_ID)
    return VoiceRef.stored(row.voice) if row is not None else None


def is_default(db: Session, engine: str, voice: str = "") -> bool:
    """这一对(或只问引擎时,这个引擎)是不是这台机器的默认。"""
    stored = default_voice(db)
    if not engine or stored is None or stored.engine != engine:
        return False
    return not voice or stored.voice == voice


def store_default(db: Session, voice: VoiceRef | None) -> VoiceRef | None:
    """把已经校验过的那一把写进单例行;`None` = 清掉,回到"每个入口各自点名"。不提交,由入口提交。

    **校验不在这里**:音色属于哪个引擎、适不适用那个模型要问音色目录(`engine_catalog.set_default_voice`),那是画在
    引擎目录那一层的知识;本模块只认存储和解析,所以那一层反过来调这里。这样两个模块不是互相 import
    的环(见 tests/test_import_layering.py)。
    """
    row = db.get(VoiceDefaultConfig, SINGLETON_ID)
    if row is None:
        if voice is None:
            return None
        #: 行只在这里建(归属见 domain/ownership.py)。
        row = VoiceDefaultConfig(id=SINGLETON_ID)
        db.add(row)
    row.voice = voice.to_json() if voice is not None else {}
    db.flush()
    return voice


def resolve_voice_default(db: Session, owner_user_id: str | None) -> VoiceRef | None:
    """调用方没点名嗓子时,这一次用哪一把;`None` = 交给现有的"必须点名"兜底。

    优先级见模块说明。**点名了的不经过这里**:调用方手里有一个 `VoiceRef` 就用它,不拿默认补其中哪一格 ——
    半个默认会把「只点了音色」的克隆请求悄悄换到另一家引擎上。
    """
    deployed = default_voice(db)
    if owner_user_id:
        personal = capabilities.default_id(db, owner_user_id, CAPABILITY)
        #: 老行可能指向已经删掉的连接 / 引擎:和 choose 一样,不当作一个能用的默认。
        if personal and any(one.id == personal for one in capabilities.providers(db, owner_user_id, CAPABILITY)):
            #: 这个人的引擎和部署的不是同一家:嗓子不能硬套过去(克隆音色的 id 换到 Edge 上就是错的),交给"必须点名"。
            return deployed if deployed is not None and deployed.engine == personal else None

    #: 部署默认只可能是内置引擎(写入时就这么收);库里的旧值如果已经不在能力表里,当作没设。
    #: 音色不在磁盘上 / 账号里已经删了不在这里查 —— 那要问各家(火山按账号现拉),而解析每一步都要快;
    #: 真念的时候由合成那一步说,和降噪"默认事后被卸载"同一条(不静默回退)。
    if deployed is not None and any(one.id == deployed.engine for one in CAPABILITY.builtins):
        return deployed
    return None


__all__ = [
    "SINGLETON_ID",
    "UnknownVoiceEngine",
    "VoiceDefaultError",
    "VoiceEngineNotReady",
    "VoiceMissing",
    "VoiceNotInEngine",
    "default_voice",
    "is_default",
    "resolve_voice_default",
    "store_default",
]
