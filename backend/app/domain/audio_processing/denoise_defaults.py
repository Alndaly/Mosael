"""降噪引擎的两层,以及「这一次到底用哪一家」的**唯一**解析点。

## 两层,谁也不是谁的替代(和转写的 `domain/asr` 同一条规则)

- **部署默认**(管理 → 引擎 → 降噪):这台机器默认用哪一种。降噪引擎是这台机器上的资产 ——
  装没装、默认用哪个,对所有用户是同一件事,所以写它只给部署管理员。
- **按人选的**(设置 → 能力提供方 → 降噪):某个人自己定过的那一家。他做的选择比部署的默认更
  具体,所以压过它。它是**覆盖**,不是另一份默认 —— 拿它替换部署默认会让"没说"变成"我讨厌的
  那一个",反过来部署默认也不该吃掉某一条路自己的选择。

实际生效的顺序(从上到下):

1. **这次调用点名的**提供方 id(工作流节点、「用××降噪」、智能体工具);
2. **这个人自己**在「能力提供方 → 降噪」定过的默认;
3. 部署默认(本模块,管理 → 引擎 → 降噪);
4. 不定时本来就会用的:第一个跑得起来、不顺手去掉配乐的内置引擎(`capabilities.choose`)。

**有效值只在这里算一次**(`resolve_denoise_engine`)。所有降噪入口都经过
`domain/assets/denoise.ready_adapter`,所以那边读到的永远是同一个答案 —— 谁要是自己在别处再拼
一份,迟早出现"管理页写着一个、降噪用的是另一个",而用户看到的是「设了却没生效」。

**插件连接只属于某个人**(需要他的授权、他的钥匙),所以部署默认只收内置引擎的提供方 id;
「按人选的那一家」仍然可以是插件。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai.runtime import denoise_models
from app.core.i18n import LocalizedError, tr
from app.db.models import DenoiseConfig
from app.domain import capabilities

#: 单例行只有一个 id。
SINGLETON_ID = "default"


class DenoiseDefaultError(LocalizedError, RuntimeError):
    """设默认被拒。子类各自对应一个 HTTP 状态 —— 都是输入的问题,不是服务端故障。"""


class UnknownDenoiseEngine(DenoiseDefaultError):
    """能力表里没有这个提供方 id(拼错了,或者根本不是 `audio_denoise` 的一份实现)。"""

    def __init__(self, engine: str) -> None:
        super().__init__("routeErr_unknownDenoiseEngine", engine=engine)


class DenoiseEngineNotInstalled(DenoiseDefaultError):
    """盘上没有这个引擎(要下载的那一类)—— 设成默认也只是一句空话。"""

    def __init__(self, engine: str) -> None:
        super().__init__("routeErr_denoiseEngineNotInstalled", engine=engine)


class DenoiseEngineNotReady(DenoiseDefaultError):
    """不需要下载、但这台机器上用不了(比如 ffmpeg 不带 RNNoise 滤镜)—— 缺什么原样说出来。"""

    def __init__(self, engine: str, missing: str) -> None:
        super().__init__("routeErr_denoiseEngineNotReady", engine=engine, missing=missing)


def _denoise_capability() -> capabilities.Capability:
    """能力契约。**在函数里取**:audio_capabilities 会反过来用本模块的解析结果(见 denoise_adapter),
    写在模块顶上就是一个环。"""
    from app.domain.audio_capabilities import DENOISE

    return DENOISE


def _installable(provider_id: str) -> bool:
    """这一家是不是"要下载才装得上"的那一类 —— 决定被拒时该说"先下载"还是"缺什么"。"""
    return provider_id.removeprefix(capabilities.BUILTIN_PREFIX) in denoise_models.INSTALLABLE


def default_engine(db: Session) -> str:
    """这台机器设的默认引擎(提供方 id);没设过是空串。"""
    row = db.get(DenoiseConfig, SINGLETON_ID)
    return row.default_engine if row is not None else ""


def is_default(db: Session, provider_id: str) -> bool:
    return bool(provider_id) and default_engine(db) == provider_id


def set_default_engine(db: Session, engine: str) -> str:
    """把这一家定为这台机器的默认。

    **只许设已经装好、这台机器上跑得起来的**:默认要是一句有内容的话 —— 设完下一次降噪就得先
    下载的"默认",和没设没有区别,只是屏幕上多了一句承诺。不认识的 id 直接拒。

    只收内置引擎(见模块说明:插件连接属于某个人,不是这台机器的资产)。

    不提交,由入口提交(和 `capabilities.set_default` 同一套)。
    """
    capability = _denoise_capability()
    #: 旧 id / 大小写先按能力表归一 —— 和 pick、resolve 用的是同一份解析。
    wanted = capabilities.canonical_id(capability, engine)
    candidates = capabilities.providers(db, None, capability)
    found = next((one for one in candidates if one.id == wanted), None)
    if found is None:
        raise UnknownDenoiseEngine(wanted)
    if found.missing:
        #: 缺什么原样给:要下载的说"先下载",别的说它缺的那一项(RNNoise 是 ffmpeg 的滤镜)。
        if _installable(found.id):
            raise DenoiseEngineNotInstalled(found.name)
        raise DenoiseEngineNotReady(found.name, tr("punct_listSep").join(found.missing))
    row = db.get(DenoiseConfig, SINGLETON_ID)
    if row is None:
        #: 行只在这里建(归属见 domain/ownership.py)。
        row = DenoiseConfig(id=SINGLETON_ID)
        db.add(row)
    row.default_engine = found.id
    db.flush()
    return found.id


def resolve_denoise_engine(db: Session, owner_user_id: str | None, *, explicit: str = "") -> str:
    """这一次用哪一家(提供方 id);空串 = 交给 `capabilities.choose` 按内置兜底挑。

    优先级见模块说明。`explicit` 是调用方点名的提供方 id(空 = 没说)。不认识的 id **不在这里
    退回默认** —— 把点名的那一家交下去,由 `capabilities.pick` 带着「哪一家、现在能用哪几家」拒绝,
    和素材转写点名的规矩是同一套。
    """
    named = (explicit or "").strip()
    if named:
        return named

    capability = _denoise_capability()
    if owner_user_id:
        personal = capabilities.default_id(db, owner_user_id, capability)
        #: 老行可能指向已经删掉的连接/引擎:和 choose 一样,不当作一个能用的默认。
        if personal and any(one.id == personal for one in capabilities.providers(db, owner_user_id, capability)):
            return personal

    deployed = default_engine(db)
    #: 部署默认只可能是内置引擎(写入时就这么收);库里的旧值如果已经不在能力表里,当作没设。
    if deployed and any(one.id == deployed for one in capability.builtins):
        return deployed
    return ""


__all__ = [
    "DenoiseDefaultError",
    "DenoiseEngineNotInstalled",
    "DenoiseEngineNotReady",
    "SINGLETON_ID",
    "UnknownDenoiseEngine",
    "default_engine",
    "is_default",
    "resolve_denoise_engine",
    "set_default_engine",
]
