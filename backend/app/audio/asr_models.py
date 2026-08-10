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
import sys
import subprocess
import threading
from functools import lru_cache
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.child_process import ChildProcess, run_logged
from app.core.config import settings

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
MANAGED_ASR_VENV = settings.data_dir / "asr" / "venv"


def managed_venv_python() -> Path:
    windows = os.name == "nt"
    return MANAGED_ASR_VENV / ("Scripts" if windows else "bin") / ("python.exe" if windows else "python")


# funasr aliases → their ModelScope cache directory names (funasr materialises
# under <modelscope_cache>/**/iic/<dir>). Sizes are approximate — used only for
# the percentage denominator.
_FUNASR_BUNDLE = ModelEntry(
    id="funasr-zh",
    engine="funasr",
    label="FunASR 中文套件",
    detail="Paraformer 识别 + VAD 断句 + 标点 + 说话人分离,中文转写默认引擎",
    sub_models=(
        SubModel("speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch", 1_000_000_000),
        SubModel("speech_fsmn_vad_zh-cn-16k-common-pytorch", 5_000_000),
        SubModel("punc_ct-transformer_cn-en-common-vocab471067-large", 1_150_000_000),
        SubModel("speech_campplus_sv_zh-cn_16k-common", 30_000_000),
    ),
    request={"provider": "funasr", "action": "warmup"},
)


def _whisperx_entry(size: str, label: str, detail: str, expected: int) -> ModelEntry:
    return ModelEntry(
        id=f"whisperx-{size}",
        engine="whisperx",
        label=label,
        detail=detail,
        sub_models=(SubModel(f"models--Systran--faster-whisper-{size}", expected),),
        request={"provider": "whisperx", "action": "warmup", "whisper_model": size},
    )


CATALOG: tuple[ModelEntry, ...] = (
    _FUNASR_BUNDLE,
    _whisperx_entry("small", "WhisperX Small", "多语种,速度与精度均衡(默认)", 500_000_000),
    _whisperx_entry("medium", "WhisperX Medium", "多语种,精度更高、更慢", 1_530_000_000),
    _whisperx_entry("large-v3", "WhisperX Large v3", "多语种最高精度,占用最大", 3_100_000_000),
)

_BY_ID = {entry.id: entry for entry in CATALOG}


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
    (cache layouts drift across library versions, so we glob by dir name)."""
    for root in _cache_roots(engine):
        direct = root / cache_dir
        if direct.is_dir():
            return direct
        # iic/<dir> and hub/**/<dir> layouts
        for match in root.rglob(cache_dir):
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
    return _measure(entry) >= int(entry.expected_bytes * _INSTALLED_FRACTION)


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


def clear_runtime_probes() -> None:
    """装好环境之后把探测缓存清掉 —— 只有一处要清,因为只有一份缓存。"""
    _resolve_python.cache_clear()
    runtime_ready.cache_clear()


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
    base = {
        "id": entry.id,
        "engine": entry.engine,
        "label": entry.label,
        "detail": entry.detail,
        "expected_bytes": entry.expected_bytes,
        # **两件事分开报**:文件在不在(status)、跑不跑得起来(runtime_ready)。
        # 把它们合成一个"已安装"是这一页此前说谎的原因。
        "runtime_ready": runtime_ready(entry.engine),
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
            "message": live.message,
        }
    if live is not None and live.status == "failed":
        return {**base, "status": "failed", "downloaded_bytes": _measure(entry),
                "total_bytes": entry.expected_bytes, "message": live.message}
    if installed:
        ready = base["runtime_ready"]
        return {**base, "status": "installed", "downloaded_bytes": _measure(entry),
                "total_bytes": entry.expected_bytes,
                "message": "已安装,转写即刻可用" if ready else "模型已在磁盘上,但还没有能运行它的 Python 环境"}
    return {**base, "status": "missing", "downloaded_bytes": _measure(entry),
            "total_bytes": entry.expected_bytes, "message": "未下载"}


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
def candidate_pythons() -> list[Path]:
    """可能装了 funasr/whisperx 的解释器,按优先级。**这是唯一一份名单。**

    托管 venv 排在最前:那是应用自己建、自己装的那个(见 audio/asr_models.ensure_engine_runtime),
    最可能是对的。用户显式指定的次之,后端自己的解释器兜底。

    收在一处是因为它被问过两遍:转写走这里,模型页那个「跑不跑得起来」也走这里。此前两边各拼
    一份,而托管 venv 只加进了后者 —— 于是模型页显示「已安装」、一点转写就报"没有运行环境",
    同一个问题两个答案。
    """
    candidates: list[Path] = [managed_venv_python()]
    if settings.asr_python:
        candidates.append(Path(settings.asr_python).expanduser())
    import sys

    candidates.append(Path(sys.executable))
    return candidates


@lru_cache(maxsize=8)
def _resolve_python(engine: str) -> str:
    """装了 `engine` 的那个解释器。**全项目唯一的探测实现**,也是唯一那份缓存。

    此前有两份:这里一份、service.resolve_asr_runtime 一份,各带各的 lru_cache。两份实现意味着
    两个答案 —— 托管 venv 加进了这一份、漏了那一份,于是模型页说「已安装」而转写说"没有环境"。
    合成一份之后,加候选、改判据都只有一个地方。

    探测要起子进程,所以缓存;装完环境后调 `clear_runtime_probes()`。
    """
    for python in candidate_pythons():
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

    venv_python = managed_venv_python()
    if not venv_python.is_file():
        _store.set(key, _Live(status="downloading", message="创建运行环境…"))
        MANAGED_ASR_VENV.parent.mkdir(parents=True, exist_ok=True)
        created = run_logged(
            [sys.executable, "-m", "venv", str(MANAGED_ASR_VENV)],
            capture_output=True, text=True, timeout=600, what="创建转写运行环境")
        if created.returncode != 0 or not venv_python.is_file():
            raise RuntimeError(f"创建运行环境失败:{(created.stderr or created.stdout)[-300:]}")

    _store.set(key, _Live(status="downloading", message=f"安装 {engine} 运行依赖(数 GB,首次较慢)…"))
    # --upgrade 让重试能修好装了一半的环境;超时给足 —— torch 在慢网络下很久。
    result = run_logged(
        [str(venv_python), "-m", "pip", "install", "--upgrade", *requirements],
        capture_output=True, text=True, timeout=7200, what="安装转写运行依赖")
    if result.returncode != 0:
        raise RuntimeError(f"安装 {engine} 运行依赖失败:{(result.stderr or result.stdout)[-300:]}")
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
    if _store.downloading():
        raise RuntimeError("已有模型正在下载,请等待其完成(共用 CPU/带宽,串行下载)")
    # 分母先留空:接下来可能是"装运行环境"(pip,量纲完全不同),真正开始拉模型时再填上。
    _store.set(model_id, _Live(status="downloading", message="准备中…"))
    threading.Thread(target=_run_download, args=(model_id,), daemon=True).start()
    return _status_dict(entry)


def _fmt_eta(seconds: float | None) -> str:
    if not seconds or seconds <= 0:
        return ""
    m, s = divmod(int(seconds), 60)
    return f"剩余 {m}分{s:02d}秒" if m else f"剩余 {s}秒"


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
    last_bytes, last_time = _measure(entry), started
    proc = subprocess.Popen(
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

    while proc.poll() is None:
        time.sleep(_POLL_SECONDS)
        now = time.monotonic()
        current = _measure(entry)
        dt = max(now - last_time, 1e-3)
        speed = max(0.0, (current - last_bytes) / dt)
        remaining = max(0, entry.expected_bytes - current)
        eta = remaining / speed if speed > 100 else None
        # Some backends (HuggingFace) finalize large blobs atomically, so bytes
        # jump only at the end — fall back to an elapsed-time heartbeat so the UI
        # never looks frozen.
        elapsed = int(now - started)
        message = _fmt_eta(eta) or f"下载中(已用 {elapsed // 60}分{elapsed % 60:02d}秒)"
        _store.set(model_id, _Live(
            status="downloading", downloaded=current, total=entry.expected_bytes,
            speed=speed, eta=eta, message=message))
        last_bytes, last_time = current, now

    stderr = child.finish(600)
    if proc.returncode == 0 and _is_installed(entry):
        _store.clear(model_id)  # disk detection now reports "installed"
    else:
        _store.set(model_id, _Live(status="failed", message=(stderr or "下载进程异常退出")[:400]))
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
    if not entry.expected_bytes:
        return 0.0
    return min(_measure(entry) / entry.expected_bytes, 0.99)


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
