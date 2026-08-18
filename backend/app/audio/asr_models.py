"""ASR model download manager.

funasr / whisperx download their weights *implicitly* inside the library on
first use (`AutoModel(...)`, `whisperx.load_model(...)`), printing progress bars
to stdout that the worker swallows — so a first transcribe silently blocks while
~2GB downloads. This module makes those downloads visible and manually
triggerable:

- a catalog of downloadable models (funasr bundle + whisperx sizes),
- install detection by probing the shared library caches on disk,
- deliberate download via the ASR worker's `warmup` action (runs in the external
  ASR interpreter, same as transcription), while a watcher thread polls the
  cache directory byte-size to report percentage, **speed and ETA**.

Progress is computed from bytes on disk vs. an expected total — robust and
cross-process (the download runs in a foreign interpreter), no tqdm parsing.
"""
from __future__ import annotations

import logging

import json
import os
import subprocess
import threading
from functools import lru_cache
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.audio import remote_size
from app.core import interpreter, pip_install, run_log
from app.core.child_process import ChildProcess, popen_text, run_logged
from app.core.rate import DownloadRate
from app.core.config import settings
from app.core.text import blame_line

logger = logging.getLogger(__name__)

WORKER_PATH = Path(__file__).with_name("asr_worker.py")
WARMUP_TIMEOUT_SECONDS = 3600
_POLL_SECONDS = 1.5
# A model counts as installed once its on-disk size reaches this fraction of the
# expected total — tolerates version drift and metadata files we don't count.
_INSTALLED_FRACTION = 0.6


@dataclass(frozen=True)
class SubModel:
    """One weight repo that a catalog entry pulls. `cache_dir` is the directory
    name the library materialises under its cache root."""

    cache_dir: str
    #: 体积**问源要**时用的那个仓库 id(见 audio/remote_size)。`cache_dir` 是库在本地
    #: 摊开成的目录名,不一定等于仓库 id —— HuggingFace 那边是 `models--A--B` 这种转写。
    repo: str
    #: 源:"modelscope" 或 "hf"。
    source: str
    #: 问不到时退回的估算。写死的数会随上游改文件而失准,所以它只是兜底。
    expected_bytes: int


@dataclass(frozen=True)
class ModelEntry:
    id: str
    engine: str  # "funasr" | "whisperx"
    label: str
    detail: str
    sub_models: tuple[SubModel, ...]
    # extra request params passed to the warmup worker (e.g. whisper_model)
    request: dict[str, Any]

    @property
    def expected_bytes(self) -> int:
        """问不到源时的兜底总量。**优先用 `measured_total`** —— 那才是实际要下多少。"""
        return sum(sub.expected_bytes for sub in self.sub_models)


#: 每个引擎的运行依赖。装到托管 venv 里 —— 重的那些(torch 2GB+)落在用户数据目录而不是安装包里。
#: 和 TTS 那边同一个做法(见 audio/tts_models.ensure_engine_runtime),理由也同一条:让用户
#: **不必**去设置里指定 Python 解释器。
ENGINE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "funasr": ("funasr", "torch", "torchaudio", "modelscope"),
    "whisperx": ("whisperx",),
}

#: 托管的 ASR 运行环境。和 TTS 那个分开:两边的依赖会打架(不同的 torch 版本),而共用一个
#: venv 意味着装一边可能弄坏另一边。
#:
#: **这句话此前只写在注释里,没有兑现**:funasr 和 whisperx 仍然共用同一个 venv,而它们
#: 正是"两边依赖会打架"的两边。克隆那边差点为此付账(fish 钉 torch==2.8,f5 装的是 2.13),
#: 所以这里也按引擎分开。
MANAGED_ASR_ROOT = settings.data_dir / "asr"

#: 分开之前那个共用的。**不留作兼容候选**,由 migrate_shared_venv 一次性搬走或删掉。
LEGACY_SHARED_VENV = MANAGED_ASR_ROOT / "venv"


def _venv_python(venv: Path) -> Path:
    windows = os.name == "nt"
    return venv / ("Scripts" if windows else "bin") / ("python.exe" if windows else "python")


def managed_venv_dir(engine: str) -> Path:
    safe = engine.replace("/", "-").replace("..", "-")
    return MANAGED_ASR_ROOT / f"venv-{safe}"


def managed_venv_python(engine: str) -> Path:
    return _venv_python(managed_venv_dir(engine))


def _engines_a_venv_can_run(python: Path) -> list[str]:
    """这个解释器能跑哪些转写引擎。"""
    able: list[str] = []
    for engine in ENGINE_REQUIREMENTS:
        try:
            probe = run_logged([str(python), "-c", f"import {engine}"], capture_output=True, timeout=180,
                               what="迁移前探测转写引擎", level=logging.DEBUG)
        except (subprocess.SubprocessError, OSError):
            continue
        if probe.returncode == 0:
            able.append(engine)
    return able


def migrate_shared_venv() -> None:
    """把分开之前那个共用 venv 搬到它实际服务的引擎名下,搬完删掉旧路径。

    和克隆那边同一条规矩(见 domain/tts_config.migrate_shared_venv):**不留兼容候选** ——
    留着就是两条路并存,而一个环境同时被两个引擎装东西,正是"装一边弄坏另一边"的机制本身。
    """
    import shutil

    legacy = LEGACY_SHARED_VENV
    python = _venv_python(legacy)
    if not legacy.is_dir():
        return
    able = _engines_a_venv_can_run(python) if python.is_file() else []
    if not able:
        logger.info("删掉跑不了任何转写引擎的旧共用 venv:%s", legacy)
        shutil.rmtree(legacy, ignore_errors=True)
        return
    preferred = settings.asr_provider.strip().lower()
    target_engine = preferred if preferred in able else able[0]
    target = managed_venv_dir(target_engine)
    if target.exists():
        shutil.rmtree(legacy, ignore_errors=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    legacy.rename(target)
    logger.info("旧的共用 venv 归给 %s:%s → %s", target_engine, legacy, target)


# funasr aliases → their ModelScope cache directory names (funasr materialises
# under <modelscope_cache>/**/iic/<dir>). Sizes are approximate — used only for
# the percentage denominator.
_FUNASR_BUNDLE = ModelEntry(
    id="funasr",
    engine="funasr",
    label="asrLabel_funasr",
    detail="asrDetail_funasr",
    sub_models=(
        # SenseVoice:按官方说明「超过 40 万小时数据训练,支持超过 50 种语言,识别效果上优于 Whisper」,
        # 标点与逆文本规整都在模型内部。体积现在**问 ModelScope 要**(见 audio/remote_size);
        # 这里的数字只是问不到时的兜底,而它注定会随上游改文件而失准。
        SubModel("SenseVoiceSmall", "iic/SenseVoiceSmall", "modelscope", 937_000_000),
        # VAD 断句与说话人分离是**独立阶段**,与识别模型无关:它们按音频切段/聚类,换识别模型照样用。
        # 说话人分离不能丢 —— 转写面板的说话人标签、按人筛选都靠它。
        SubModel("speech_fsmn_vad_zh-cn-16k-common-pytorch",
                 "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch", "modelscope", 5_000_000),
        SubModel("speech_campplus_sv_zh-cn_16k-common",
                 "iic/speech_campplus_sv_zh-cn_16k-common", "modelscope", 30_000_000),
    ),
    request={"provider": "funasr", "action": "warmup"},
)


def _whisperx_entry(size: str, label: str, detail: str, expected: int) -> ModelEntry:
    return ModelEntry(
        id=f"whisperx-{size}",
        engine="whisperx",
        label=label,
        detail=detail,
        sub_models=(SubModel(f"models--Systran--faster-whisper-{size}",
                             f"Systran/faster-whisper-{size}", "hf", expected),),
        request={"provider": "whisperx", "action": "warmup", "whisper_model": size},
    )


CATALOG: tuple[ModelEntry, ...] = (
    _FUNASR_BUNDLE,
    _whisperx_entry("small", "WhisperX Small", "asrDetail_whisperSmall", 500_000_000),
    _whisperx_entry("medium", "WhisperX Medium", "asrDetail_whisperMedium", 1_530_000_000),
    _whisperx_entry("large-v3", "WhisperX Large v3", "asrDetail_whisperLarge", 3_100_000_000),
)

_BY_ID = {entry.id: entry for entry in CATALOG}


def measured_total(entry: ModelEntry, *, blocking: bool = False) -> tuple[int, bool]:
    """(这个条目要下的总字节, 这个数是不是估算)。

    此前用的是目录里写死的估算,而它同时当着卡片体积、进度分母、和"装好了没有"的判据 ——
    上游改一次文件三样一起失准。按源上的**实际文件**算(见 audio/remote_size);
    任何一份问不到,整个总量就退回估算并说出来 —— 报一个残缺的总数比报估算更糟:
    它看起来精确,而进度条会提前走满。
    """
    total = 0
    for sub in entry.sub_models:
        files = (remote_size.files_for if blocking else remote_size.cached_files)(sub.source, sub.repo)
        size = remote_size.total_bytes(files)
        if not size:
            return entry.expected_bytes, True
        total += size
    return total, False


# ---------------------------------------------------------------------------
# Cache probing
# ---------------------------------------------------------------------------
def _cache_roots(engine: str) -> list[Path]:
    roots: list[Path] = []
    if engine == "funasr":
        env = os.environ.get("MODELSCOPE_CACHE")
        if env:
            roots.append(Path(env))
        roots.append(Path.home() / ".cache" / "modelscope")
    else:
        env = os.environ.get("HF_HUB_CACHE") or os.environ.get("HUGGINGFACE_HUB_CACHE")
        if env:
            roots.append(Path(env))
        hf_home = os.environ.get("HF_HOME")
        if hf_home:
            roots.append(Path(hf_home) / "hub")
        roots.append(Path.home() / ".cache" / "huggingface" / "hub")
    return [root for root in roots if root.is_dir()]


def _dir_size(path: Path) -> int:
    """目录占的磁盘,**符号链接不跟**。

    HuggingFace 缓存里 `snapshots/<rev>/model.bin` 是指回 `blobs/<sha>` 的符号链接;`is_file()`
    和 `stat()` 默认都跟着链接走,于是每个 blob 被数两遍 —— 实测正是整两倍(du 说 464MB,这里
    报 972MB)。

    后果不只是数字难看:`_is_installed` 的判据是"实测 ≥ 期望的某个比例",量翻倍意味着**下到
    一半的模型也会被判成已安装**,而它要到运行时才炸。
    """
    total = 0
    try:
        for child in path.rglob("*"):
            try:
                if child.is_symlink() or not child.is_file():
                    continue
                total += child.stat().st_size
            except OSError:
                continue
    except OSError:
        return total
    return total


def _find_sub_dir(engine: str, cache_dir: str) -> Path | None:
    """Locate a sub-model's directory anywhere under the engine's cache roots
    (cache layouts drift across library versions, so we glob by dir name).

    **命名空间前缀那一种也要认**:同一个模型在不同版本的 modelscope 下可能落成
    `hub/models/iic/<dir>`,也可能落成 `models/iic--<dir>/snapshots/master`。只按裸名找的话,
    后一种会被当成"没下载" —— 实测 SenseVoice 就是这样:901MB 已经在盘上,界面却还写着未下载,
    点下载又拉一遍。这不是某个模型的特例,是布局漂移本身,所以在这里认,而不是给某个 id 开后门。
    """
    for root in _cache_roots(engine):
        direct = root / cache_dir
        if direct.is_dir():
            return direct
        # iic/<dir> 与 hub/**/<dir>
        for match in root.rglob(cache_dir):
            if match.is_dir():
                return match
        # models/<namespace>--<dir>
        for match in root.rglob(f"*--{cache_dir}"):
            if match.is_dir():
                return match
    return None


def _measure(entry: ModelEntry) -> int:
    """Current on-disk bytes across all of an entry's sub-model directories."""
    total = 0
    for sub in entry.sub_models:
        found = _find_sub_dir(entry.engine, sub.cache_dir)
        if found is not None:
            total += _dir_size(found)
    return total


def _is_installed(entry: ModelEntry) -> bool:
    # 判据用实测总量:上游把文件改大之后,拿旧估算当分母会把"才下了一半"判成"已安装"。
    total, _estimated = measured_total(entry)
    return _measure(entry) >= int(total * _INSTALLED_FRACTION)


# ---------------------------------------------------------------------------
# Live download state (in-memory; disk detection is the source of truth at rest)
# ---------------------------------------------------------------------------
@dataclass
class _Live:
    status: str = "idle"  # "downloading" | "failed"
    downloaded: int = 0
    total: int = 0
    speed: float = 0.0  # bytes/sec
    eta: float | None = None  # seconds remaining
    message: str = ""
    #: message 是 key 时的模板参数(见 core/i18n.t)。翻译在出口做,这里只负责把值带出来。
    params: dict[str, str] = field(default_factory=dict)


class _Store:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._live: dict[str, _Live] = {}

    def get(self, model_id: str) -> _Live | None:
        with self._lock:
            live = self._live.get(model_id)
            return None if live is None else _Live(**live.__dict__)

    def set(self, model_id: str, live: _Live) -> None:
        with self._lock:
            self._live[model_id] = live

    def clear(self, model_id: str) -> None:
        with self._lock:
            self._live.pop(model_id, None)

    def downloading(self) -> bool:
        with self._lock:
            return any(live.status == "downloading" for live in self._live.values())


_store = _Store()


def resolve_engine_python(engine: str) -> str | None:
    """装了这个引擎的解释器;没有就 None。调用方据此决定是报错还是换一个引擎试。"""
    try:
        return _resolve_python(engine)
    except Exception:  # noqa: BLE001 — "没有"就是答案,原因由调用方另行呈现
        return None


#: 探测过的结果。**列状态只读这里,永远不等** —— 探测要起子进程 import funasr(它会把
#: torch 一起拉起来),而列模型是一次纯读的请求。用户那一页停在「正在连接后端…」就是这个。
#: 克隆那边同一套(见 audio/tts_models),判据也是同一句:这个接口要回答的问题,不需要起
#: 子进程就能回答。
_PROBED: dict[str, bool] = {}
_PROBING: set[str] = set()
_PROBE_LOCK = threading.Lock()


def probe_in_background(engine: str) -> None:
    with _PROBE_LOCK:
        if engine in _PROBED or engine in _PROBING:
            return
        _PROBING.add(engine)

    def run() -> None:
        ok = False
        try:
            ok = runtime_ready(engine)
        finally:
            with _PROBE_LOCK:
                _PROBING.discard(engine)
                _PROBED[engine] = ok

    threading.Thread(target=run, daemon=True).start()


def refresh_runtime_status(engine: str) -> bool:
    """现在就探一次并记下来(装完之后调,以及测试里要确定答案时)。"""
    ok = runtime_ready(engine)
    with _PROBE_LOCK:
        _PROBED[engine] = ok
    return ok


def runtime_status(engine: str) -> tuple[bool, bool]:
    """(跑得起来吗, 测过了吗)。没测过就在后台起一次,先把已知的给出去。"""
    with _PROBE_LOCK:
        if engine in _PROBED:
            return _PROBED[engine], True
    probe_in_background(engine)
    return False, False


def clear_runtime_probes() -> None:
    """装好环境之后把探测缓存清掉 —— 只有一处要清,因为只有一份缓存。"""
    # getattr:测试会把探测换成普通函数(没有 cache_clear)。清缓存是清理动作,不是判据,
    # 不该因为"被替换过"就炸。
    getattr(_resolve_python, "cache_clear", lambda: None)()
    getattr(runtime_ready, "cache_clear", lambda: None)()
    with _PROBE_LOCK:
        _PROBED.clear()


@lru_cache(maxsize=4)
def runtime_ready(engine: str) -> bool:
    """有没有一个解释器能 `import <engine>` —— 也就是**跑不跑得起来**。

    这和"模型文件在不在盘上"是两件独立的事,而它们完全可以一真一假:模型缓存在
    `~/.cache/modelscope`、`~/.cache/huggingface` 里,别的工具下过就在那儿;而这个应用的解释器
    里可能从来没装过 funasr/whisperx。用户撞到的正是这一种:三行「已安装」,一转写就报
    「未找到可用的转写环境」—— 两句话都没说谎,只是在回答不同的问题。

    缓存住:探测要起一次子进程,而这个函数在列表页每行都会被问一遍。装好环境之后调
    `runtime_ready.cache_clear()`。
    """
    try:
        _resolve_python(engine)
    except Exception:  # noqa: BLE001 — 探测失败就是"跑不起来",原因由调用方另行呈现
        return False
    return True


def _status_dict(entry: ModelEntry) -> dict[str, Any]:
    live = _store.get(entry.id)
    installed = _is_installed(entry)
    total, estimated = measured_total(entry)
    base = {
        "id": entry.id,
        "engine": entry.engine,
        "label": entry.label,
        "detail": entry.detail,
        "expected_bytes": total,
        "total_is_estimate": estimated,
        # **两件事分开报**:文件在不在(status)、跑不跑得起来(runtime_ready)。
        # 把它们合成一个"已安装"是这一页此前说谎的原因。
        # **不等探测**:它要起子进程 import funasr。没测过就先说"还没测",后台去问。
        "runtime_ready": runtime_status(entry.engine)[0],
        "runtime_checked": runtime_status(entry.engine)[1],
    }
    if live is not None and live.status == "downloading":
        return {
            **base,
            "status": "downloading",
            "downloaded_bytes": live.downloaded,
            # **不回落到模型大小**:装运行环境那一阶段没有可报的总量(跑的是 pip),
            # 顶一个模型的字节数上去,界面就会画出"0 MB / 500 MB"这种量错了东西的进度条。
            "total_bytes": live.total,
            "speed_bps": live.speed,
            "eta_seconds": live.eta,
            "message": live.message, "message_params": live.params,
        }
    if live is not None and live.status == "failed":
        return {**base, "status": "failed", "downloaded_bytes": _measure(entry),
                "total_bytes": total, "message": live.message, "message_params": live.params}
    if installed:
        ready = base["runtime_ready"]
        return {**base, "status": "installed", "downloaded_bytes": _measure(entry),
                "total_bytes": total,
                "message": "modelMsg_asrReady" if ready else "modelMsg_asrNoRuntime"}
    return {**base, "status": "missing", "downloaded_bytes": _measure(entry),
            "total_bytes": total, "message": "modelMsg_notDownloaded"}


def list_status() -> list[dict[str, Any]]:
    return [_status_dict(entry) for entry in CATALOG]


def get_status(model_id: str) -> dict[str, Any]:
    entry = _BY_ID.get(model_id)
    if entry is None:
        raise KeyError(model_id)
    return _status_dict(entry)


def any_downloading() -> bool:
    return _store.downloading()


# ---------------------------------------------------------------------------
# Download orchestration
# ---------------------------------------------------------------------------
def candidate_pythons(engine: str) -> list[Path]:
    """可能装了 funasr/whisperx 的解释器,按优先级。**这是唯一一份名单。**

    托管 venv 排在最前:那是应用自己建、自己装的那个(见 audio/asr_models.ensure_engine_runtime),
    最可能是对的。用户显式指定的次之,后端自己的解释器兜底。

    收在一处是因为它被问过两遍:转写走这里,模型页那个「跑不跑得起来」也走这里。此前两边各拼
    一份,而托管 venv 只加进了后者 —— 于是模型页显示「已安装」、一点转写就报"没有运行环境",
    同一个问题两个答案。
    """
    candidates: list[Path] = [managed_venv_python(engine)]
    if settings.asr_python:
        candidates.append(Path(settings.asr_python).expanduser())
    # 见 core/interpreter:打包版里"自己"是应用的 exe,拿它探测会再起一个后端。
    mine = interpreter.self_python()
    if mine:
        candidates.append(Path(mine))
    return candidates


@lru_cache(maxsize=8)
def _resolve_python(engine: str) -> str:
    """装了 `engine` 的那个解释器。**全项目唯一的探测实现**,也是唯一那份缓存。

    此前有两份:这里一份、service.resolve_asr_runtime 一份,各带各的 lru_cache。两份实现意味着
    两个答案 —— 托管 venv 加进了这一份、漏了那一份,于是模型页说「已安装」而转写说"没有环境"。
    合成一份之后,加候选、改判据都只有一个地方。

    探测要起子进程,所以缓存;装完环境后调 `clear_runtime_probes()`。
    """
    for python in candidate_pythons(engine):
        if not python.is_file():
            continue
        probe = run_logged([str(python), "-c", f"import {engine}"], capture_output=True, timeout=120, what="转写引擎探测", level=logging.DEBUG)
        if probe.returncode == 0:
            return str(python)
    raise RuntimeError(f"未找到安装了 {engine} 的 Python 解释器,请设置 OPEN_STUDIO_ASR_PYTHON")


def ensure_engine_runtime(engine: str, *, progress_key: str | None = None) -> None:
    """确保有一个解释器能 `import <engine>`;没有就建一个托管 venv 并装进去。

    这一步的存在,就是为了让用户**不必**去设置里指定 Python 解释器 —— 和 TTS 那边同一个做法
    (见 audio/tts_models.ensure_engine_runtime)。此前 ASR 没有这条路:模型下好了、页面写着
    「已安装」,而转写照样报「未找到可用的转写环境」,唯一的出路是自己去装 funasr 再设环境变量。

    已经跑得起来就直接返回 —— **不碰用户自带的环境**。

    `progress_key` 是这次进度写在**哪一行**上(模型 id)。此前这里按引擎名写,而界面按模型 id 读,
    于是这两句阶段文字一次都没显示过 —— 用户看到的是一条不动的进度条配一句"准备下载…"。

    这一阶段**不报字节**:跑的是 pip(装 torch 等),它一个字节都不会落进模型缓存目录,而进度是按
    那个目录的增长算的。借用模型的 2.2GB 当分母,结果就是永远 0 MB / 2.2 GB。两件事量纲不同,
    就别共用一个进度条 —— 只报"在做哪一步"。
    """
    if runtime_ready(engine):
        return
    key = progress_key or engine
    requirements = ENGINE_REQUIREMENTS.get(engine)
    if not requirements:
        raise RuntimeError(f"不认识的转写引擎:{engine}")

    # **装,一律进这个引擎自己的目录。** 共用的那个只在探测里读(见 candidate_pythons)。
    venv_dir = managed_venv_dir(engine)
    venv_python = managed_venv_python(engine)
    if not venv_python.is_file():
        _store.set(key, _Live(status="downloading", message="dlMsg_creatingRuntime"))
        venv_dir.parent.mkdir(parents=True, exist_ok=True)
        # **不能用 sys.executable**:打包版里它是应用自己,`-m venv` 会把后端再启动一遍,
        # 然后把 uvicorn "端口已占用" 的日志当成"创建失败的原因"端给用户。
        base = interpreter.base_python()
        if not base:
            raise RuntimeError("找不到可用于创建运行环境的 Python 解释器")
        created = run_logged(
            [base, "-m", "venv", str(venv_dir)],
            capture_output=True, text=True, timeout=600, what="创建转写运行环境")
        if created.returncode != 0 or not venv_python.is_file():
            raise RuntimeError(f"创建运行环境失败:{(created.stderr or created.stdout)[-300:]}")

    _store.set(key, _Live(status="downloading", message="dlMsg_installingDeps", params={"engine": engine}))
    # **和克隆走同一个安装器**,包括设置页那个 pip 镜像 —— 此前这里没带,于是同一台机器上
    # 「声音克隆走镜像、转写直连 PyPI」,而设置项写的是「装引擎依赖时用的 pip 索引」。
    # 超时给足:torch 在慢网络下很久。
    #
    # 这个设置存在 tts_config 里(历史上克隆先有了它),但它管的是 pip 而不是克隆 ——
    # 两个引擎装依赖用的是同一个索引。在函数里 import:core/audio 不该在模块层依赖 domain。
    from app.domain import tts_config

    try:
        pip_install.install(
            venv_python,
            requirements,
            what="安装转写运行依赖",
            index_url=tts_config.get().pip_index_url,
        )
    except pip_install.PipInstallError as exc:
        raise RuntimeError(f"安装 {engine} 运行依赖失败:{exc}") from exc
    clear_runtime_probes()


def start_download(model_id: str) -> dict[str, Any]:
    """Kick off a deliberate download in a background thread. State is tracked in
    the in-memory store (polled via GET /asr/models); disk detection recovers
    the true state after a restart, so no persistent Job is needed."""
    entry = _BY_ID.get(model_id)
    if entry is None:
        raise KeyError(model_id)
    # **"文件都在了"不等于"没事可做"**:还可能缺运行环境,而那正是这个按钮此时要装的东西。
    # 这里一律早返回的话,那个按钮点了没有任何反应 —— 比报错更让人摸不着头脑。
    if _is_installed(entry) and runtime_ready(entry.engine):
        return _status_dict(entry)
    # **并行是允许的**(同 tts_models.start_download):每个引擎有自己的 venv,下载跑在各自的
    # 一次性子进程里,同时装不会互相弄坏。只拒绝"这一个已经在下了"。
    live = _store.get(model_id)
    if live is not None and live.status == "downloading":
        raise RuntimeError(f"{entry.label} 已经在下载中")
    # 分母先留空:接下来可能是"装运行环境"(pip,量纲完全不同),真正开始拉模型时再填上。
    _store.set(model_id, _Live(status="downloading", message="dlMsg_preparingShort"))
    threading.Thread(target=_run_download, args=(model_id,), daemon=True).start()
    return _status_dict(entry)


def _fmt_eta(seconds: float | None) -> tuple[str, dict[str, str]]:
    """(key, 参数)—— **不拼句子**:拼进去那句话就只有一种语言了(见 core/i18n.t)。"""
    if not seconds or seconds <= 0:
        return "", {}
    m, s = divmod(int(seconds), 60)
    return ("dlMsg_etaMinutes", {"m": str(m), "s": f"{s:02d}"}) if m else ("dlMsg_etaSeconds", {"s": str(s)})


def _run_download(model_id: str) -> None:
    """Wrapped so the "downloading" flag can never outlive the thread that set it.

    start_download refuses while _store.downloading() is true. Anything escaping the body
    below — a worker that cannot be spawned, a disk error, a bug — used to leave that flag
    set for the life of the process, so EVERY later download was rejected with
    「已有模型正在下载」 and only a restart cleared it.
    """
    try:
        _download_body(model_id)
    except Exception as exc:  # noqa: BLE001 — the flag must be released whatever happened
        logger.exception("model download failed")
        _store.set(model_id, _Live(status="failed", message=str(exc)[:400]))


def _download_body(model_id: str) -> None:
    entry = _BY_ID[model_id]
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    output_path = settings.data_dir / f"asr-warmup-{model_id}.json"
    try:
        # **先把环境建好**。此前这里直接探测解释器、没有就报错 —— 于是缺环境的机器上,
        # 这一页显示着「已安装」,而点任何一个按钮都失败。
        ensure_engine_runtime(entry.engine, progress_key=model_id)
        python = _resolve_python(entry.engine)
    except Exception as exc:  # noqa: BLE001
        _store.set(model_id, _Live(status="failed", message=str(exc)[:400]))
        return

    started = time.monotonic()
    last_bytes = _measure(entry)
    proc = popen_text(
        [python, str(WORKER_PATH), str(output_path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(entry.request))
    proc.stdin.close()
    # The child's stdout/stderr must be drained while we poll. Hub downloads write tqdm
    # progress bars continuously (service.py notes this for the transcribe path); once one of
    # those pipes fills, the child blocks writing it, poll() never returns, and the UI shows
    # "下载中" with frozen byte counts forever. There is no timeout here on purpose — a
    # multi-gigabyte download over a slow link is legitimately long — so draining is the whole
    # defence.
    child = ChildProcess(proc)
    threading.Thread(target=lambda: [None for _ in child.raw_lines()], daemon=True).start()

    # 速度按**最近一段**算,不是按最近一次采样:下载器成块写盘,单窗口读数会在 0 和几百 MB/s
    # 之间跳,而 ETA 在跳到 0 的那一瞬就消失。和克隆那条下载路共用一份实现(core.rate)。
    rate = DownloadRate()
    rate.update(last_bytes, at=started)
    # **分母问源要**,不用目录里那个写死的估算。用户已经在等这次下载,所以这里可以阻塞去问
    # (超时 6 秒);问不到就退回估算 —— 那正是此前一直在用的数,不会更糟。
    download_total, _estimated = measured_total(entry, blocking=True)
    while proc.poll() is None:
        time.sleep(_POLL_SECONDS)
        now = time.monotonic()
        current = _measure(entry)
        speed = rate.update(current, at=now)
        eta = rate.eta(remaining=max(0, download_total - current))
        # Some backends (HuggingFace) finalize large blobs atomically, so bytes
        # jump only at the end — fall back to an elapsed-time heartbeat so the UI
        # never looks frozen.
        elapsed = int(now - started)
        key, params = _fmt_eta(eta)
        if not key:
            key, params = "dlMsg_elapsed", {"m": str(elapsed // 60), "s": f"{elapsed % 60:02d}"}
        _store.set(model_id, _Live(
            status="downloading", downloaded=current, total=download_total,
            speed=speed, eta=eta, message=key, params=params))

    stderr = child.finish(600)
    if proc.returncode == 0 and _is_installed(entry):
        _store.clear(model_id)  # disk detection now reports "installed"
    else:
        # 此前是 `stderr[:400]` —— 按**位置**裁的又一处(克隆那边裁的是尾巴)。开头 400 字符
        # 通常是进度条和一堆下载提示,真正的异常在后面。挑结论行(core/text.blame_line),
        # 完整输出落盘 —— 否则"进程没了"这种报错除了让用户重跑一遍之外无法诊断。
        path = run_log.save(
            f"模型 {model_id} · 引擎 {entry.engine}\n退出码 {proc.returncode}\n\n{stderr or '(子进程什么都没说)'}\n",
            kind="worker", what=f"asr-{model_id}",
        )
        reason = blame_line(stderr or "") or "dlMsg_processDied"
        if path is not None and reason != "dlMsg_processDied":
            reason = f"{reason[:400]}\n完整日志:{path}"
        logger.warning("下载 %s 失败(完整输出见 %s)", model_id, path)
        _store.set(model_id, _Live(status="failed", message=reason))
    try:
        output_path.unlink(missing_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Lazy-transcribe integration: report the first-use download in the job
# ---------------------------------------------------------------------------
def entry_for_transcribe(provider: str) -> ModelEntry | None:
    """The catalog entry a transcribe run will (lazily) download, if missing."""
    if provider == "funasr":
        return _FUNASR_BUNDLE
    return _BY_ID.get(f"whisperx-{settings.asr_whisper_model}")


def measure_fraction(entry: ModelEntry) -> float:
    total, _estimated = measured_total(entry)
    if not total:
        return 0.0
    return min(_measure(entry) / total, 0.99)


def is_installed(model_id_or_entry: str | ModelEntry) -> bool:
    entry = model_id_or_entry if isinstance(model_id_or_entry, ModelEntry) else _BY_ID.get(model_id_or_entry)
    return bool(entry and _is_installed(entry))


__all__ = [
    "CATALOG",
    "ModelEntry",
    "list_status",
    "get_status",
    "start_download",
    "any_downloading",
    "entry_for_transcribe",
    "measure_fraction",
    "is_installed",
]
