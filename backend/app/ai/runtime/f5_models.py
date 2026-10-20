"""F5-TTS 的**模型**目录 —— 和引擎分开的那一层。

此前代码里写着两个常量:

    F5_CHECKPOINT = "F5TTS_v1_Base/model_1250000.safetensors"
    F5_VOCAB      = "F5TTS_v1_Base/vocab.txt"

于是「F5-TTS 支持什么语言」这个问题,被回答成了「引擎支持什么语言」。而真相是:**引擎什么语言
都支持,支持范围由权重决定**。v1_Base 在中英语料上训练、vocab 里没有假名,所以它念不了日文;
换一份日语微调的权重,同一个引擎、同一个 venv、同一段代码就念得了。

运行时其实早就准备好了 —— worker 那边一直是
`F5TTS(ckpt_file=…, vocab_file=…)`,只是这两个值被钉死了。这里把它们变成一张表,于是:

  ・语言能力挂在**模型**上(`languages`),判据只有这一处;
  ・换语言 = 多下一份权重,不是改代码;
  ・合成时按文本的书写系统挑模型,挑不到就明说要下哪一个,而不是拿中英模型硬念。

**路径不加模型 id 那一层**:每个模型在仓库里本来就有自己的目录前缀(`F5TTS_v1_Base/`、
`JA_21999120/`),天然不撞车。多加一层的话,已经下好 base 的机器要重下 1.35 GB。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import logging

from app.ai.runtime import remote_size
from app.ai.runtime.tts_models import bytes_on_disk
from app.core.rate import DownloadRate

from app.ai.runtime.download_state import DownloadProgress, DownloadStore
from app.ai.runtime.errors import RuntimeSetupError, failure_message

logger = logging.getLogger(__name__)

#: 量一次盘的间隔。和引擎权重、转写模型那两条路取同一个值 —— 三处报的是同一种东西,
#: 刷新快慢不该各不相同。
_POLL_SECONDS = 1.5

#: 第三方库报"连不上下载源"的几种说法。和 tts_models 的 `_HUB_UNREACHABLE` 是同一条判据:
#: 那边解析子进程的 stderr,这边拿到的是一个异常 —— 判据一样,来源不同。
_HUB_UNREACHABLE = (
    "LocalEntryNotFoundError",
    "ConnectionError",
    "ReadTimeout",
    "ProxyError",
    "check your connection",
    "Max retries exceeded",
)


def _failure_from(exc: BaseException) -> tuple[str, dict[str, str], str]:
    """一次下载失败 → (卡片上那句话的 key/原话, 模板参数, 「详情」里的原文)。

    **原文不进主句。** 第三方库的英文异常(截图里是 `LocalEntryNotFoundError: An error occurred…`)
    此前被拼进卡片那一句,而卡片只显示两行 —— 一截就只剩「An error…」,人话和能行动的那半句
    都被挤没了。现在它留在 `error` 里:界面的「详情」读的就是这一栏。

    三类原因:我们自己抛的带 key(翻得出人话);连不上下载源的那几种(说清去哪儿换源);
    其余第三方库的原文(翻不了,只当详情,不摆进主句)。
    """
    from app.core.i18n import is_message_key

    message, params = failure_message(exc)
    raw = str(exc).strip()
    if is_message_key(message):
        return message, params, raw
    if any(marker in message for marker in _HUB_UNREACHABLE):
        from app.ai.runtime import config as tts_config

        return "runtimeErr_hubUnreachable", {"endpoint": str(tts_config.get().hf_endpoint)}, raw
    return "runtimeErr_f5DownloadFailed", {}, raw


@dataclass(frozen=True)
class F5Model:
    id: str
    #: 界面文案的 i18n key(见 core/i18n)。
    label: str
    #: 这份权重认得的书写系统。**判据的唯一来源** —— 别处不要再写"F5 支持什么"。
    languages: tuple[str, ...]
    hf_repo: str
    #: 仓库内路径,同时也是落到托管目录后的相对路径。
    checkpoint: str
    vocab: str
    expected_bytes: int
    #: ModelScope 上的同一份(有就优先走它:实测比 HF 快两个数量级)。空 = 只有 HF。
    modelscope_repo: str = ""
    note: str = ""
    #: 文件直接落在托管目录根下。**只有基础模型是这样** —— 它的仓库路径自带 `F5TTS_v1_Base/`
    #: 前缀,而且已经有机器下好了,改布局等于让它们重下 1.35 GB。
    #: 其余模型一律落进自己的子目录:它们的 vocab **全叫 `vocab.txt`**,共用一个目录就会
    #: 互相覆盖 —— 装了法语再装德语,其中一个从此配着别人的 vocab 念(测试抓到过)。
    shared_root: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def local_dir(self) -> str:
        return "" if self.shared_root else self.id

    @property
    def local_checkpoint(self) -> str:
        return self.checkpoint if self.shared_root else f"{self.id}/{self.checkpoint}"

    @property
    def local_vocab(self) -> str:
        return self.vocab if self.shared_root else f"{self.id}/{self.vocab}"


#: 出厂就认得的模型。加一门语言 = 在这里加一行 + 用户点一次下载,不改任何逻辑。
#: 来源是 F5-TTS 官方 `src/f5_tts/infer/SHARED.md` 里的社区微调清单,文件名逐个核对过仓库
#: 的真实文件列表(文档和仓库不一致过,所以不照抄)。
F5_MODELS: tuple[F5Model, ...] = (
    F5Model(
        id="base",
        label="f5Model_base",
        languages=("zh", "en"),
        hf_repo="SWivid/F5-TTS",
        checkpoint="F5TTS_v1_Base/model_1250000.safetensors",
        vocab="F5TTS_v1_Base/vocab.txt",
        expected_bytes=1_350_000_000,
        modelscope_repo="AI-ModelScope/F5-TTS",
        note="f5ModelNote_base",
        shared_root=True,
    ),
    F5Model(
        id="ja",
        label="f5Model_ja",
        languages=("ja",),
        hf_repo="Jmica/F5TTS",
        checkpoint="JA_21999120/model_21999120.pt",
        vocab="JA_21999120/vocab_japanese.txt",
        expected_bytes=1_400_000_000,
        note="f5ModelNote_community",
    ),
    # 下面几门语言来自 F5-TTS 官方 SHARED.md 的社区微调清单。**文件名以仓库的真实文件列表为准**:
    # 文档里有 `model_*.safetensors` 这种通配符,也有和仓库对不上的路径(日语那条就是)。
    # 一律优先 .safetensors:它不执行 pickle,而这些权重来自第三方账号。
    F5Model(
        id="fr",
        label="f5Model_fr",
        languages=("fr",),
        hf_repo="RASPIAUDIO/F5-French-MixedSpeakers-reduced",
        checkpoint="model_last_reduced.pt",  # 这个仓库只有 .pt
        vocab="vocab.txt",
        expected_bytes=1_400_000_000,
        note="f5ModelNote_community",
    ),
    F5Model(
        id="de",
        label="f5Model_de",
        languages=("de",),
        hf_repo="hvoss-techfak/F5-TTS-German",
        checkpoint="model_f5tts_german.safetensors",
        vocab="vocab.txt",
        expected_bytes=1_400_000_000,
        note="f5ModelNote_community",
    ),
    F5Model(
        id="es",
        label="f5Model_es",
        languages=("es",),
        hf_repo="jpgallegoar/F5-Spanish",
        # 仓库里有 1200000 和 1250000 两份,取新的那份(文档写的是通配符)。
        checkpoint="model_1250000.safetensors",
        vocab="vocab.txt",
        expected_bytes=1_400_000_000,
        note="f5ModelNote_community",
    ),
    F5Model(
        id="it",
        label="f5Model_it",
        languages=("it",),
        hf_repo="alien79/F5-TTS-italian",
        checkpoint="model_159600.safetensors",
        vocab="vocab.txt",
        expected_bytes=1_400_000_000,
        note="f5ModelNote_community",
    ),
    F5Model(
        id="ru",
        label="f5Model_ru",
        languages=("ru",),
        hf_repo="hotstone228/F5-TTS-Russian",
        checkpoint="model_last.safetensors",
        vocab="vocab.txt",
        expected_bytes=1_400_000_000,
        note="f5ModelNote_community",
    ),
    F5Model(
        id="hi",
        label="f5Model_hi",
        languages=("hi",),
        hf_repo="SPRINGLab/F5-Hindi-24KHz",
        checkpoint="model_2500000.safetensors",
        vocab="vocab.txt",
        expected_bytes=1_400_000_000,
        note="f5ModelNote_community",
    ),
    F5Model(
        id="ar",
        label="f5Model_ar",
        languages=("ar",),
        hf_repo="silma-ai/silma-tts",
        checkpoint="model.pt",  # 这个仓库只有 .pt
        vocab="vocab.txt",
        expected_bytes=1_400_000_000,
        note="f5ModelNote_community",
    ),
    F5Model(
        id="fi",
        label="f5Model_fi",
        languages=("fi",),
        hf_repo="AsmoKoskinen/F5-TTS_Finnish_Model",
        checkpoint="model_common_voice_fi_vox_populi_fi_20241206.safetensors",
        vocab="vocab.txt",
        expected_bytes=1_400_000_000,
        note="f5ModelNote_community",
    ),
)

_BY_ID = {model.id: model for model in F5_MODELS}

#: 默认模型。**不叫 "F5TTS_v1_Base"** —— 用 id 指代,换默认时只改这一行。
DEFAULT_MODEL_ID = "base"


def get(model_id: str) -> F5Model | None:
    return _BY_ID.get(model_id)


def root() -> Path:
    from app.ai.runtime import config as tts_config

    return tts_config.MANAGED_F5_MODEL


def checkpoint_path(model: F5Model) -> Path:
    return root() / model.local_checkpoint


def installed(model: F5Model) -> bool:
    """权重在盘上吗。**只看检查点** —— vocab 是几十 KB,缺了会在加载时报错并被当作一次失败,
    而把它算进"装没装"会让一次网络抖动看起来像"整个模型没下"。"""
    return checkpoint_path(model).is_file()


def installed_languages() -> set[str]:
    """这台机器上,克隆引擎**现在**念得了的书写系统。

    注意是"现在":用户下了日语模型它就变,所以任何判断都要现算,不能在启动时缓存下来 ——
    缓存住的话,用户下完模型仍会被告知"念不了",而那正是这套东西要修的毛病。
    """
    languages: set[str] = set()
    for model in F5_MODELS:
        if installed(model):
            languages.update(model.languages)
    return languages


def for_language(script: str) -> F5Model | None:
    """念得了这套书写系统、而且**已经装好**的模型;没有就 None。

    空 script(中英文,或拿不到硬证据)一律回默认模型 —— 它就是为这种情况准备的。
    """
    if not script:
        return _BY_ID.get(DEFAULT_MODEL_ID)
    for model in F5_MODELS:
        if script in model.languages and installed(model):
            return model
    return None


def missing_for_language(script: str) -> F5Model | None:
    """能念这套书写系统、但**还没下载**的那个模型 —— 用来告诉用户"下这个就行"。"""
    if not script:
        return None
    for model in F5_MODELS:
        if script in model.languages and not installed(model):
            return model
    return None


#: 下载状态。一次只下一个:这些文件都是 GB 级,并发下只会互相抢带宽。
#: 和转写模型、克隆引擎同一份实现(见 runtime/download_state)。
_store = DownloadStore()

#: 上一次失败发生的时刻(UTC ISO)。只服务界面那句「最后一次 …」——
#: DownloadProgress 是引擎权重、转写模型、语言包三条下载路共用的记录,不为这一条链的显示
#: 去改它的形状。清掉 / 重试 / 成功时一并丢掉,免得下一次失败还挂着上一次的时间。
_failed_at: dict[str, str] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _unfinished_attempt(model: F5Model) -> str:
    """盘上有没有**上一次没下完**的痕迹:那一刻的 UTC ISO;没有就是空串。

    下载跑在另一个进程里(常驻的 f5-tts worker),而状态记录在**这个**进程的内存里 ——
    后端重启 / dev 的 `--reload` 会把记录清空、线程一起杀掉,盘上那半截却还在。只看内存的话,
    界面这时会回到「下载这个模型」,像从来没点过;而用户看到的是"加载一会儿就没了"。
    盘上的痕迹(半截文件、hf 的锁、哪怕只有一个 `.cache/huggingface` 目录)就是"试过、没下完"。

    只认这个模型自己的目录:基础模型落在根下,量它自己的仓库前缀那一层,不能把别的语言包
    算成它的痕迹。
    """
    base = root()
    target = (base / model.local_dir) if model.local_dir else (base / model.checkpoint.split("/", 1)[0])
    try:
        if not target.is_dir():
            return ""
        latest = 0.0
        found = False
        for entry in target.rglob("*"):
            if not entry.is_file():
                continue
            found = True
            latest = max(latest, entry.stat().st_mtime)
        if not found:
            return ""
        return datetime.fromtimestamp(latest, timezone.utc).isoformat(timespec="seconds")
    except OSError:
        return ""


def measured_total(model: F5Model, *, blocking: bool = False) -> tuple[int, bool]:
    """(这份权重的总字节, 这个数是不是估算)。

    目录里那个 `expected_bytes` 是拍出来的 —— 十个社区模型全写着同一个 1_400_000_000,
    而它们的检查点从 1.2 GB 到 1.5 GB 都有。按源上的**实际文件**算(检查点 + vocab 两个,
    不是整仓:Jmica/F5TTS 整仓有四份检查点,而我们只取一份)。

    问不到就退回估算并说出来 —— 理由见 ai/runtime/remote_size 的模块说明。
    """
    source, repo = (("modelscope", model.modelscope_repo) if model.modelscope_repo
                    else ("hf", model.hf_repo))
    files = (remote_size.files_for if blocking else remote_size.cached_files)(source, repo)
    size = remote_size.total_bytes(files, (model.checkpoint, model.vocab))
    # 0 不是"这份权重是空的",是**路径没对上**(社区仓库改过文件名)。当成问不到 ——
    # 否则界面上会出现一个 0 字节的模型,而进度条的分母成了 0。
    if not size:
        return model.expected_bytes, True
    return size, False


def status(model: F5Model) -> dict[str, Any]:
    live = _store.get(model.id) or DownloadProgress(status="", progress=-1.0)
    total, estimated = measured_total(model)
    downloading_now = live.status == "downloading"
    on_disk = installed(model)
    # 内存里没有记录、盘上却有上一次的痕迹 = 上一次被杀了(应用退出 / 后端重启 / dev 热重载)。
    # 这时候不能报 missing —— 那会让界面回到「下载这个模型」,像从来没点过。
    interrupted_at = "" if live.status or on_disk else _unfinished_attempt(model)
    return {
        "id": model.id,
        "label": model.label,
        "languages": list(model.languages),
        "note": model.note,
        "expected_bytes": total,
        "total_is_estimate": estimated,
        "installed": on_disk,
        "status": live.status or ("failed" if interrupted_at else ("installed" if on_disk else "missing")),
        "progress": live.progress if live.progress >= 0 else (1.0 if on_disk else 0.0),
        # 和引擎权重、转写模型那两条路报同样的东西 —— 三处报的是同一种事,形状不同只会让
        # 界面各写一套(而"三处两种做法"正是这条路进度不动的由来)。
        "downloaded_bytes": live.downloaded,
        # **未知总量给 None,不给 0。** 0 会被界面当成分母,画出「0% · 0 MB / 5.4 GB」这种
        # "从来没动过"的样子;而它和"卡住了"在用户眼里是同一件事。下载中有多少报多少,
        # 量不到(还没开始量 / 源上问不到)就明说不知道。
        "total_bytes": (live.total or None) if downloading_now else (live.total or total),
        "speed_bps": live.speed,
        "eta_seconds": live.eta,
        # 失败时 message 是 i18n key 或第三方库的原话,message_params 是它的槽;
        # 出口(routes/voices.list_f5_models)连同 label / note 一起翻。
        "message": "runtimeErr_f5DownloadInterrupted" if interrupted_at else live.message,
        "message_params": live.params,
        "error": live.error,
        # 终态那一行说「最后一次 …」用:失败发生的时刻(下载中 / 没下过就是空)。
        # 被杀的这一次没有内存记录,用盘上最后一次写入的时刻。
        "failed_at": _failed_at.get(model.id, "") or interrupted_at,
    }


def list_status() -> list[dict[str, Any]]:
    return [status(model) for model in F5_MODELS]


def downloading() -> str:
    """正在下的那一份权重(没有就是空串)。"""
    return _store.busy_key()


def set_live(model_id: str, **fields: Any) -> None:
    _store.merge(model_id, **fields)


def clear_live(model_id: str) -> None:
    _store.clear(model_id)


def start_download(model_id: str) -> dict[str, Any]:
    """下一份权重。已经在盘上就直接返回状态 —— 重下 1.4 GB 不是用户点这个按钮的本意。"""
    model = get(model_id)
    if model is None:
        raise KeyError(model_id)
    if installed(model):
        return status(model)
    # **这条不放开并行**,和引擎/转写模型那两条不一样:它们各自起一次性子进程,而语言权重是
    # 向**常驻的那个 f5-tts 进程**要的(要用它 venv 里的 huggingface_hub)。同一个进程的
    # 管道现在有锁(见 tts_daemon._Worker),并发请求不会串,但也只会排队 —— 那是假的并行,
    # 界面上两个都写着"下载中"而实际一个一个来,比老老实实说"等它下完"更误导。
    busy = downloading()
    if busy:
        raise RuntimeSetupError("runtimeErr_f5LanguageBusy", busy=busy)
    # **整条记录换新,不是只改几个字段。** 上一次失败留下的字节数 / 总量 / 原因要是还挂在
    # 记录上,重试的第一眼就会显示上一次的进度和上一次的失败原因 —— 用户看到的是"重试了,
    # 可它还是上次那个数"。
    _failed_at.pop(model.id, None)
    _store.set(model.id, DownloadProgress(status="downloading", progress=0.0, message="dlMsg_preparing"))
    threading.Thread(target=_run_download, args=(model.id,), daemon=True).start()
    return status(model)


class _ByteWatcher:
    """下载期间在旁边数盘上的字节,把进度报出去。

    **不指望被观测方主动汇报**:worker 那边一次下载只报三次(每个文件开始前),中间隔着
    几个 GB。引擎权重和转写模型那两条路早就是这么量的,这里是第三处 —— 同一件事此前
    三处有两种做法,而那个例外正是"点了没反应"的那条。
    """

    def __init__(self, model: F5Model, model_id: str, stage: dict[str, str]) -> None:
        self._model = model
        self._model_id = model_id
        self._stage = stage
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="f5-download-watch")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        """叫停,并**等这一拍走完**(有上限)。只放下事件不等的话,一次刚好在量的读写会在
        「失败」写进去之后才落盘 —— 把原因覆盖回「准备下载…」,状态还是 failed,而原因没了。"""
        self._stop.set()
        self._thread.join(timeout=1.0)

    def _measure(self) -> int:
        # 只量这个模型自己的目录。基础模型 shared_root=True 落在根下,那就量检查点本身 ——
        # 量整个根目录会把别的语言包一起算进来,进度于是从一开始就是满的。
        target = root() / self._model.local_dir if self._model.local_dir else checkpoint_path(self._model)
        # **和其他两条路同一份量法**(`tts_models.bytes_on_disk`),问的是"下载到哪了",所以
        # include_unfinished=True:没下完的块要算进去。F5 走 `hf_hub_download(local_dir=…)`,
        # 未完成的检查点同样躺在 `<target>/.cache/huggingface/download/*.incomplete` 下,数落定
        # 的文件等于主权重全程不动。这不是行为变化:这里的进度一直就是数整个目录的。
        return bytes_on_disk(target, include_unfinished=True)

    def _run(self) -> None:
        total, _estimated = measured_total(self._model, blocking=True)
        rate = DownloadRate()
        started = time.monotonic()
        rate.update(self._measure(), at=started)
        while not self._stop.wait(_POLL_SECONDS):
            # stop() 之后这一拍如果还在路上,就别再写了 —— 终态的原因不该被一句「准备下载…」
            # 盖掉。没有记录(直接构造这个观察者的测试)时照旧报:这个类本身不依赖调用方先建记录。
            if self._stop.is_set():
                return
            now = time.monotonic()
            current = self._measure()
            speed = rate.update(current, at=now)
            eta = rate.eta(remaining=max(0, total - current))
            if self._stop.is_set():
                return
            set_live(
                self._model_id,
                progress=min(current / total, 0.99) if total else 0.0,
                downloaded=current,
                total=total,
                speed=speed,
                eta=eta,
                message=self._stage["message"],
            )


def _run_download(model_id: str) -> None:
    from app.ai.runtime import tts_daemon, tts_models

    model = _BY_ID[model_id]
    try:
        # 拉权重要用**装了 huggingface_hub 的那个解释器** —— 也就是引擎自己的 venv。
        # 后端解释器里没有它,而为了下个模型去后端装一份 HF 客户端是另一条会漂移的路。
        python = tts_models.resolve_engine_python("f5-tts")
        if python is None:
            raise RuntimeSetupError("runtimeErr_f5RuntimeMissing")
        request = {
            "action": "fetch_model",
            "engine": "f5-tts",
            "hf_repo": model.hf_repo,
            "modelscope_repo": model.modelscope_repo,
            "checkpoint": model.checkpoint,
            "vocab": model.vocab,
            "target": str(root()),
            "subdir": model.local_dir,
        }
        root().mkdir(parents=True, exist_ok=True)

        # worker 只在**每个文件开始前**报一次(两个文件:检查点、vocab),所以它报出来的进度是
        # 0.1 → 0.5 → 1.0 三跳。而那 0.1 之后要下 1.3–5.4 GB,几分钟到几十分钟一动不动 ——
        # 用户看到的就是「点了下载,加载一会儿就没反应了」。
        #
        # 所以进度**在这边量**:数盘上多了多少字节,和引擎权重、转写模型那两条路同一个做法
        # (见 tts_models._download_body)。worker 的事件只用来更新那句阶段文字。
        stage = {"message": "dlMsg_preparing"}

        def report(event: dict) -> None:
            stage["message"] = str(event.get("message") or stage["message"])

        watcher = _ByteWatcher(model, model_id, stage)
        watcher.start()
        try:
            tts_daemon.pool().request(
                "f5-tts", python, request,
                on_progress=report, timeout=7200, env=tts_models._worker_env(python),
            )
        finally:
            watcher.stop()
        if not installed(model):
            raise RuntimeSetupError("runtimeErr_f5CheckpointMissing")
        _failed_at.pop(model_id, None)
        clear_live(model_id)
    except Exception as exc:  # noqa: BLE001 — 失败要落在状态上,否则界面永远停在"下载中"
        # **失败要带着能读懂的原因落地。** 此前这里只写 `str(exc)` 到 error 字段、把 message
        # 清空 —— 而界面只看 status,于是"下载中"一消失就变回「下载这个文件」按钮,失败原因
        # 一个字都没露出来。用户看到的正是:加载一会儿没了,像根本没开始。
        #
        # 原因分三种:我们自己抛的带 key(翻得出人话);连不上下载源的那几种(能说清去哪儿
        # 换源);其余第三方库的原文(翻不了 —— 它进 `error`,不进主句)。
        message, params, raw = _failure_from(exc)
        _failed_at[model_id] = _now_iso()
        set_live(model_id, status="failed", message=message, params=params, error=raw[:400])
