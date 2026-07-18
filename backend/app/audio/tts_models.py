"""TTS engine model manager + external-interpreter resolution.

Mirrors app/audio/asr_models.py: a catalog of downloadable TTS engine weights,
install detection by probing the HuggingFace cache, deliberate download via the
worker's warmup action (runs in the external TTS interpreter), byte-poll
progress with speed + ETA. The heavy engines (f5-tts / fish-speech) live in a
separate Python resolved from MIBU_TTS_PYTHON.
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

WORKER_PATH = Path(__file__).with_name("tts_worker.py")
_POLL_SECONDS = 1.5
_INSTALLED_FRACTION = 0.6


@dataclass(frozen=True)
class TtsEngine:
    id: str  # engine id used by the worker: "f5-tts" | "fish-speech"
    label: str
    detail: str
    cache_dirs: tuple[str, ...]  # HF cache dir names to sum for install/progress
    expected_bytes: int
    module: str  # importable python module that proves the engine is installed


CATALOG: tuple[TtsEngine, ...] = (
    TtsEngine(
        id="f5-tts",
        label="F5-TTS",
        detail="零样本声音克隆,给一段参考音频即可合成同音色语音(推荐)",
        cache_dirs=("models--SWivid--F5-TTS", "models--charactr--vocos-mel-24khz"),
        expected_bytes=1_500_000_000,
        module="f5_tts",
    ),
    TtsEngine(
        id="fish-speech",
        label="Fish Speech S2 Pro",
        detail="零样本克隆,支持情感标签,占用更大",
        cache_dirs=("models--fishaudio--s2-pro",),
        expected_bytes=4_000_000_000,
        module="fish_speech",
    ),
)

_BY_ID = {engine.id: engine for engine in CATALOG}


def _hf_roots() -> list[Path]:
    roots: list[Path] = []
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


def _measure(engine: TtsEngine) -> int:
    # Fish Speech reuses a local weights dir (configured / sibling mibu-video), not the
    # HF hub cache — measure that so a reused setup reads as installed, not "missing".
    if engine.id == "fish-speech":
        from app.domain import tts_config

        model = tts_config.get().resolved_fish_model
        if model and Path(model).is_dir():
            return _dir_size(Path(model))
    total = 0
    for name in engine.cache_dirs:
        for root in _hf_roots():
            found = root / name
            if found.is_dir():
                total += _dir_size(found)
                break
    return total


def _is_installed(engine: TtsEngine) -> bool:
    return _measure(engine) >= int(engine.expected_bytes * _INSTALLED_FRACTION)


# ---------------------------------------------------------------------------
# Interpreter resolution (mirrors ASR)
# ---------------------------------------------------------------------------
def _worker_env() -> dict[str, str]:
    """Env for the TTS worker subprocess: point HuggingFace at the configured
    mirror so first-use model downloads work (e.g. hf-mirror in CN), and pass the
    resolved Fish Speech source-checkout + weights dirs the worker runs from."""
    from app.domain import tts_config

    cfg = tts_config.get()
    env = dict(os.environ)
    env["HF_ENDPOINT"] = cfg.hf_endpoint
    if cfg.resolved_fish_repo:
        env["MIBU_FISH_REPO_DIR"] = cfg.resolved_fish_repo
    if cfg.resolved_fish_model:
        env["MIBU_FISH_MODEL_DIR"] = cfg.resolved_fish_model
    return env


def candidate_pythons() -> list[Path]:
    from app.domain import tts_config

    candidates: list[Path] = []
    configured = tts_config.get().python_path
    if configured:
        candidates.append(Path(configured).expanduser())
    repo_root = Path(__file__).resolve().parents[3]
    candidates.append(repo_root.parent / "mibu-video" / "backend" / ".venv" / "bin" / "python")
    import sys

    candidates.append(Path(sys.executable))
    return candidates


def _probe_code(engine_id: str) -> str | None:
    """Python one-liner proving the engine is importable, or None if a required
    resource (Fish Speech checkout / weights) is missing → not ready."""
    if engine_id != "fish-speech":
        return "import f5_tts"
    from app.domain import tts_config

    cfg = tts_config.get()
    repo, model = cfg.resolved_fish_repo, cfg.resolved_fish_model
    if not repo or not model:
        return None
    # fish_speech lives in the source checkout, not a pip package — put it on sys.path first.
    return f"import sys; sys.path.insert(0, {repo!r}); import fish_speech"


def probe_interpreter(engine_id: str) -> dict[str, Any]:
    """Whether some candidate interpreter can import the engine (i.e. real
    synthesis is available). Returns {worker_ready, worker_python}."""
    code = _probe_code(engine_id)
    if code is None:
        return {"worker_ready": False, "worker_python": ""}
    for python in candidate_pythons():
        if not python.is_file():
            continue
        try:
            probe = subprocess.run([str(python), "-c", code], capture_output=True, timeout=60)
        except (subprocess.SubprocessError, OSError):
            continue
        if probe.returncode == 0:
            return {"worker_ready": True, "worker_python": str(python)}
    return {"worker_ready": False, "worker_python": ""}


def resolve_tts_python(engine_module: str | None = None) -> str:
    """First interpreter that can import the engine; else this interpreter (the
    worker's placeholder fallback still produces a valid wav there)."""
    import sys

    for python in candidate_pythons():
        if not python.is_file():
            continue
        if engine_module is None:
            return str(python)
        probe = subprocess.run([str(python), "-c", f"import {engine_module}"], capture_output=True, timeout=120)
        if probe.returncode == 0:
            return str(python)
    return sys.executable


# ---------------------------------------------------------------------------
# Live download state
# ---------------------------------------------------------------------------
@dataclass
class _Live:
    status: str = "idle"
    downloaded: int = 0
    total: int = 0
    speed: float = 0.0
    eta: float | None = None
    message: str = ""


class _Store:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._live: dict[str, _Live] = {}

    def get(self, key: str) -> _Live | None:
        with self._lock:
            live = self._live.get(key)
            return None if live is None else _Live(**live.__dict__)

    def set(self, key: str, live: _Live) -> None:
        with self._lock:
            self._live[key] = live

    def clear(self, key: str) -> None:
        with self._lock:
            self._live.pop(key, None)

    def downloading(self) -> bool:
        with self._lock:
            return any(live.status == "downloading" for live in self._live.values())


_store = _Store()


def _status_dict(engine: TtsEngine) -> dict[str, Any]:
    live = _store.get(engine.id)
    base = {"id": engine.id, "label": engine.label, "detail": engine.detail, "expected_bytes": engine.expected_bytes}
    if live is not None and live.status == "downloading":
        return {**base, "status": "downloading", "downloaded_bytes": live.downloaded,
                "total_bytes": live.total or engine.expected_bytes, "speed_bps": live.speed,
                "eta_seconds": live.eta, "message": live.message}
    if live is not None and live.status == "failed":
        return {**base, "status": "failed", "downloaded_bytes": _measure(engine),
                "total_bytes": engine.expected_bytes, "message": live.message}
    if _is_installed(engine):
        return {**base, "status": "installed", "downloaded_bytes": _measure(engine),
                "total_bytes": engine.expected_bytes, "message": "已安装,声音克隆可用"}
    return {**base, "status": "missing", "downloaded_bytes": _measure(engine),
            "total_bytes": engine.expected_bytes, "message": "未下载"}


def list_status() -> list[dict[str, Any]]:
    return [_status_dict(engine) for engine in CATALOG]


def get_status(engine_id: str) -> dict[str, Any]:
    engine = _BY_ID.get(engine_id)
    if engine is None:
        raise KeyError(engine_id)
    return _status_dict(engine)


def is_installed(engine_id: str) -> bool:
    engine = _BY_ID.get(engine_id)
    return bool(engine and _is_installed(engine))


def _fmt_eta(seconds: float | None) -> str:
    if not seconds or seconds <= 0:
        return ""
    m, s = divmod(int(seconds), 60)
    return f"剩余 {m}分{s:02d}秒" if m else f"剩余 {s}秒"


def start_download(engine_id: str) -> dict[str, Any]:
    engine = _BY_ID.get(engine_id)
    if engine is None:
        raise KeyError(engine_id)
    if _is_installed(engine):
        return _status_dict(engine)
    if _store.downloading():
        raise RuntimeError("已有引擎正在下载,请等待其完成")
    _store.set(engine.id, _Live(status="downloading", total=engine.expected_bytes, message="准备下载…"))
    threading.Thread(target=_run_download, args=(engine.id,), daemon=True).start()
    return _status_dict(engine)


def _run_download(engine_id: str) -> None:
    engine = _BY_ID[engine_id]
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    output_path = settings.data_dir / f"tts-warmup-{engine_id}.wav"
    python = resolve_tts_python(engine.module)
    started = time.monotonic()
    last_bytes, last_time = _measure(engine), started
    proc = subprocess.Popen(
        [python, str(WORKER_PATH), str(output_path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=_worker_env(),
    )
    assert proc.stdin is not None
    proc.stdin.write(json.dumps({"action": "warmup", "engine": engine.id}))
    proc.stdin.close()

    while proc.poll() is None:
        time.sleep(_POLL_SECONDS)
        now = time.monotonic()
        current = _measure(engine)
        dt = max(now - last_time, 1e-3)
        speed = max(0.0, (current - last_bytes) / dt)
        remaining = max(0, engine.expected_bytes - current)
        eta = remaining / speed if speed > 100 else None
        elapsed = int(now - started)
        message = _fmt_eta(eta) or f"下载中(已用 {elapsed // 60}分{elapsed % 60:02d}秒)"
        _store.set(engine.id, _Live(status="downloading", downloaded=current, total=engine.expected_bytes,
                                    speed=speed, eta=eta, message=message))
        last_bytes, last_time = current, now

    stderr = (proc.stderr.read() if proc.stderr else "")[-600:]
    if _is_installed(engine):
        _store.clear(engine.id)
    else:
        _store.set(engine.id, _Live(status="failed", message=(stderr or "下载未完成,可能引擎未安装")[:400]))
    for path in (output_path, Path(str(output_path) + ".json")):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


__all__ = ["CATALOG", "list_status", "get_status", "start_download", "is_installed", "resolve_tts_python"]
