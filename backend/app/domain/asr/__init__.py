"""转写模型的两层,以及「这一次到底用哪个模型」的**唯一**解析点。

## 两层,谁也不是谁的替代

- **全局默认**(管理 → 引擎 → 转写模型):这台机器默认用哪一份权重。模型是这台机器上的资产
  (几个 GB,装一次所有人共用),和「默认克隆引擎」同一类 —— 所以是部署级设置,写它只给部署管理员。
- **按用途覆盖**(设置 → 智能体 → 语音对话 → 说话输入用哪一家):听写这一条路单独挑一家;
  留空就用全局默认。它是**覆盖**,不是另一份默认 —— 拿它替换全局默认会让"没说"变成"我讨厌的那个",
  反过来说"全局默认"也不该吃掉某一条路自己的选择。

实际生效的顺序(从上到下):

1. **这次调用点名的**提供方(剪辑页「用 ×× 重新转写」、工作流节点)。**听写那一格也在这里**:
   路由把「说话输入用哪一家」当作点名的 provider 传下来,所以覆盖压过下面所有默认;
2. **每个人自己**在「能力提供方 → 转写」定过的默认 —— 他做的选择,比部署的默认更具体;
3. 全局默认(管理 → 引擎 → 转写模型,本模块);
4. 不定时本来就会用的:第一个跑得起来的本机引擎(`capabilities.choose`)。

**有效值只在这里算一次**(`resolve_asr_model`)。听写和素材转写都经过 `transcription.transcriber`,
所以两边读到的永远是同一个答案 —— 谁要是自己在别处再拼一份,迟早出现"管理页写着一个、转写用的是
另一个",而用户看到的是「设了却没生效」。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.ai.runtime import asr_models
from app.core.i18n import LocalizedError, tr
from app.db.models import AsrConfig
from app.domain import capabilities

#: 单例行只有一个 id。
SINGLETON_ID = "default"


class AsrModelError(LocalizedError, RuntimeError):
    """设默认被拒。两个子类各自对应一个 HTTP 状态 —— 都是输入的问题,不是服务端故障。"""


class UnknownAsrModel(AsrModelError):
    """目录里没有这个 id。"""

    def __init__(self, model_id: str) -> None:
        super().__init__("routeErr_unknownAsrModel", model=model_id)


class AsrModelNotInstalled(AsrModelError):
    """盘上没有这一份权重 —— 设成默认也只是一句空话:下一次转写照样得先下几个 GB。"""

    def __init__(self, model: str) -> None:
        super().__init__("routeErr_asrModelNotInstalled", model=model)


@dataclass(frozen=True)
class ResolvedAsr:
    """这一次实际用的:哪一家(capability 提供方 id) + 哪一份权重。

    `provider_id` 空 = 交给 `capabilities.choose` 按默认挑(和这一版之前完全一致)。
    `model_id` 空 = 用这个引擎自己的权重(funasr / sherpa-onnx 只有一份;whisperx 读配置里的型号)。
    """

    provider_id: str
    model_id: str


def model_entry(model_id: str) -> asr_models.ModelEntry | None:
    """模型 id → 目录条目(不认识的回 None:目录会变,库里存的旧 id 不该让整条路炸掉)。"""
    return next((entry for entry in asr_models.CATALOG if entry.id == model_id), None)


def whisper_model_size(model_id: str) -> str:
    """whisperx 的某一档权重对应的型号名(worker 收的 `whisper_model`);不是 whisperx 就是空。"""
    entry = model_entry(model_id)
    if entry is None or entry.engine != "whisperx":
        return ""
    return str(entry.request.get("whisper_model") or "")


def default_model_id(db: Session) -> str:
    """这台机器设的默认模型 id;没设过是空串。"""
    row = db.get(AsrConfig, SINGLETON_ID)
    return row.default_model if row is not None else ""


def is_default(db: Session, model_id: str) -> bool:
    return bool(model_id) and default_model_id(db) == model_id


def set_default_model(db: Session, model_id: str) -> str:
    """把这一份权重定为这台机器的默认。

    **只许设已经安装的**:默认要是一句有内容的话 —— 设完下一次转写就得先下几个 GB 的"默认",
    和没设没有区别,只是屏幕上多了一句承诺。不认识的 id 直接拒。

    这里没有 `tts_models.forget_failures` 那种动作:转写那条线没有"按旧默认算出来的失败缓存"
    (失败一次就是任务上的一条结果,不跨默认缓存)—— 没有就不造。

    不提交,由入口提交(和 `capabilities.set_default` 同一套)。
    """
    entry = model_entry(model_id)
    if entry is None:
        raise UnknownAsrModel(model_id)
    if not asr_models.is_installed(entry):
        raise AsrModelNotInstalled(model=tr(entry.label))
    row = db.get(AsrConfig, SINGLETON_ID)
    if row is None:
        # 行只在这里建(归属见 domain/ownership.py)。
        row = AsrConfig(id=SINGLETON_ID)
        db.add(row)
    row.default_model = entry.id
    db.flush()
    return entry.id


def resolve_asr_model(
    db: Session,
    owner_user_id: str | None,
    *,
    explicit: str = "",
    capability: capabilities.Capability | None = None,
) -> ResolvedAsr:
    """这一次用哪一家、哪一份权重。**转写所有入口都从这里拿有效值。**

    优先级见模块说明。`explicit` 是调用方点名的提供方 id(空 = 没说)。`capability` 是转写那份
    契约(由调用方给):只有要读"这个人自己定过的默认"时才需要它 —— 本模块不认识 ``transcription``
    模块(那会是一个环:它 import 本模块)。
    """
    named = (explicit or "").strip()
    if named:
        return ResolvedAsr(named, _weight_in_the_same_engine(db, named))

    if capability is not None:
        personal = capabilities.default_id(db, owner_user_id, capability)
        # 老行可能指向已经删掉的连接:和 capabilities.choose 一样,不当作一个能用的默认。
        if personal and any(one.id == personal for one in capabilities.providers(db, owner_user_id, capability)):
            return ResolvedAsr(personal, _weight_in_the_same_engine(db, personal))

    entry = model_entry(default_model_id(db))
    if entry is not None:
        return ResolvedAsr(f"{capabilities.BUILTIN_PREFIX}{entry.engine}", entry.id)
    return ResolvedAsr("", "")


def _weight_in_the_same_engine(db: Session, provider_id: str) -> str:
    """选的是某一家引擎时,权重用哪一份:**同一个引擎族里**就跟这台机器的默认走。

    - 默认是 WhisperX Large v3、这一路选了 WhisperX → 用 Large v3(默认说的就是"这台机器上
      该用哪一档")。
    - 这一路选了 FunASR → FunASR 只有一份权重,没有"哪一档"可挑。
    - 默认是 FunASR、这一路选了 WhisperX → 和默认不是一个族,用 whisperx 自己配置里的型号 ——
      拿 FunASR 的默认去猜 whisperx 的分档是没有依据的。
    """
    if not provider_id.startswith(capabilities.BUILTIN_PREFIX):
        return ""
    engine = provider_id.removeprefix(capabilities.BUILTIN_PREFIX)
    entry = model_entry(default_model_id(db))
    return entry.id if entry is not None and entry.engine == engine else ""


__all__ = [
    "AsrModelError",
    "AsrModelNotInstalled",
    "ResolvedAsr",
    "SINGLETON_ID",
    "UnknownAsrModel",
    "default_model_id",
    "is_default",
    "model_entry",
    "resolve_asr_model",
    "set_default_model",
    "whisper_model_size",
]
