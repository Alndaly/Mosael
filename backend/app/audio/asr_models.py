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

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import settings

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
    total = 0
    try:
        for child in path.rglob("*"):
            try:
                if child.is_file():
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


def _status_dict(entry: ModelEntry) -> dict[str, Any]:
    live = _store.get(entry.id)
    installed = _is_installed(entry)
    base = {
        "id": entry.id,
        "engine": entry.engine,
        "label": entry.label,
        "detail": entry.detail,
        "expected_bytes": entry.expected_bytes,
    }
    if live is not None and live.status == "downloading":
        return {
            **base,
            "status": "downloading",
            "downloaded_bytes": live.downloaded,
            "total_bytes": live.total or entry.expected_bytes,
            "speed_bps": live.speed,
            "eta_seconds": live.eta,
            "message": live.message,
        }
    if live is not None and live.status == "failed":
        return {**base, "status": "failed", "downloaded_bytes": _measure(entry),
                "total_bytes": entry.expected_bytes, "message": live.message}
    if installed:
        return {**base, "status": "installed", "downloaded_bytes": _measure(entry),
                "total_bytes": entry.expected_bytes, "message": "已安装,转写即刻可用"}
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
def _resolve_python(engine: str) -> str:
    """Path to an interpreter that has `engine` installed. Reuses the ASR
    runtime probe but pins the provider to this entry's engine."""
    from app.audio.service import _candidate_pythons  # local: avoid cycle

    for python in _candidate_pythons():
        if not python.is_file():
            continue
        probe = subprocess.run([str(python), "-c", f"import {engine}"], capture_output=True, timeout=120)
        if probe.returncode == 0:
            return str(python)
    raise RuntimeError(f"未找到安装了 {engine} 的 Python 解释器,请设置 MIBU_ASR_PYTHON")


def start_download(model_id: str) -> dict[str, Any]:
    """Kick off a deliberate download in a background thread. State is tracked in
    the in-memory store (polled via GET /asr/models); disk detection recovers
    the true state after a restart, so no persistent Job is needed."""
    entry = _BY_ID.get(model_id)
    if entry is None:
        raise KeyError(model_id)
    if _is_installed(entry):
        return _status_dict(entry)
    if _store.downloading():
        raise RuntimeError("已有模型正在下载,请等待其完成(共用 CPU/带宽,串行下载)")
    _store.set(model_id, _Live(status="downloading", total=entry.expected_bytes, message="准备下载…"))
    threading.Thread(target=_run_download, args=(model_id,), daemon=True).start()
    return _status_dict(entry)


def _fmt_eta(seconds: float | None) -> str:
    if not seconds or seconds <= 0:
        return ""
    m, s = divmod(int(seconds), 60)
    return f"剩余 {m}分{s:02d}秒" if m else f"剩余 {s}秒"


def _run_download(model_id: str) -> None:
    entry = _BY_ID[model_id]
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    output_path = settings.data_dir / f"asr-warmup-{model_id}.json"
    try:
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

    stderr = (proc.stderr.read() if proc.stderr else "")[-600:]
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
