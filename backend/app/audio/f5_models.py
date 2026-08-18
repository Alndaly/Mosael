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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.audio import remote_size


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
    from app.domain import tts_config

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
_lock = threading.Lock()
_live: dict[str, dict[str, Any]] = {}


def measured_total(model: F5Model, *, blocking: bool = False) -> tuple[int, bool]:
    """(这份权重的总字节, 这个数是不是估算)。

    目录里那个 `expected_bytes` 是拍出来的 —— 十个社区模型全写着同一个 1_400_000_000,
    而它们的检查点从 1.2 GB 到 1.5 GB 都有。按源上的**实际文件**算(检查点 + vocab 两个,
    不是整仓:Jmica/F5TTS 整仓有四份检查点,而我们只取一份)。

    问不到就退回估算并说出来 —— 理由见 audio/remote_size 的模块说明。
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
    with _lock:
        live = dict(_live.get(model.id) or {})
    total, estimated = measured_total(model)
    return {
        "id": model.id,
        "label": model.label,
        "languages": list(model.languages),
        "note": model.note,
        "expected_bytes": total,
        "total_is_estimate": estimated,
        "installed": installed(model),
        "status": live.get("status", "installed" if installed(model) else "missing"),
        "progress": live.get("progress", 1.0 if installed(model) else 0.0),
        "message": live.get("message", ""),
        "error": live.get("error", ""),
    }


def list_status() -> list[dict[str, Any]]:
    return [status(model) for model in F5_MODELS]


def downloading() -> str:
    with _lock:
        for model_id, live in _live.items():
            if live.get("status") == "downloading":
                return model_id
    return ""


def set_live(model_id: str, **fields: Any) -> None:
    with _lock:
        live = dict(_live.get(model_id) or {})
        live.update(fields)
        _live[model_id] = live


def clear_live(model_id: str) -> None:
    with _lock:
        _live.pop(model_id, None)


def start_download(model_id: str) -> dict[str, Any]:
    """下一份权重。已经在盘上就直接返回状态 —— 重下 1.4 GB 不是用户点这个按钮的本意。"""
    model = get(model_id)
    if model is None:
        raise KeyError(model_id)
    if installed(model):
        return status(model)
    busy = downloading()
    if busy:
        raise RuntimeError(f"已有模型正在下载({busy}),请等它完成")
    set_live(model.id, status="downloading", progress=0.0, message="dlMsg_preparing", error="")
    threading.Thread(target=_run_download, args=(model.id,), daemon=True).start()
    return status(model)


def _run_download(model_id: str) -> None:
    from app.audio import tts_daemon, tts_models

    model = _BY_ID[model_id]
    try:
        # 拉权重要用**装了 huggingface_hub 的那个解释器** —— 也就是引擎自己的 venv。
        # 后端解释器里没有它,而为了下个模型去后端装一份 HF 客户端是另一条会漂移的路。
        python = tts_models.resolve_engine_python("f5-tts")
        if python is None:
            raise RuntimeError("请先在设置的「声音克隆」里安装 F5-TTS 运行环境")
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

        def report(event: dict) -> None:
            set_live(model_id, progress=float(event.get("progress") or 0.0), message=str(event.get("message") or ""))

        tts_daemon.pool().request(
            "f5-tts", python, request,
            on_progress=report, timeout=7200, env=tts_models._worker_env(python),
        )
        if not installed(model):
            raise RuntimeError("下载报成功,但检查点不在盘上")
        clear_live(model_id)
    except Exception as exc:  # noqa: BLE001 — 失败要落在状态上,否则界面永远停在"下载中"
        set_live(model_id, status="failed", error=str(exc)[:400], message="")
