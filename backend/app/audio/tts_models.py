"""TTS engine model manager + external-interpreter resolution.

Mirrors app/audio/asr_models.py: a catalog of downloadable TTS engine weights,
install detection by probing the HuggingFace cache, deliberate download via the
worker's warmup action (runs in the external TTS interpreter), byte-poll
progress with speed + ETA. The heavy engines (f5-tts / fish-speech) live in a
separate Python resolved from OPEN_STUDIO_TTS_PYTHON.
"""
from __future__ import annotations

import logging

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.child_process import ChildProcess
from app.core.config import settings

logger = logging.getLogger(__name__)

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
    #: 装进托管 venv 的 pip 依赖。fish-speech 的 fish_speech 包不在 PyPI(靠 git 检出),
    #: 所以这里只列它运行所需的第三方依赖。
    pip_requirements: tuple[str, ...] = ()


CATALOG: tuple[TtsEngine, ...] = (
    TtsEngine(
        id="f5-tts",
        label="F5-TTS",
        detail="零样本声音克隆,给一段参考音频即可合成同音色语音(推荐)",
        cache_dirs=("models--SWivid--F5-TTS", "models--charactr--vocos-mel-24khz"),
        expected_bytes=1_500_000_000,
        module="f5_tts",
        pip_requirements=("f5-tts",),
    ),
    TtsEngine(
        id="fish-speech",
        label="Fish Speech S2 Pro",
        detail="零样本克隆,支持情感标签;一键下载源码 + 权重,占用更大",
        cache_dirs=("models--fishaudio--s2-pro",),
        expected_bytes=4_000_000_000,
        module="fish_speech",
        pip_requirements=("torch", "torchaudio", "transformers", "huggingface_hub", "hydra-core", "loguru"),
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
    # Fish Speech reuses a local weights dir (configured / app-managed), not the
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
        env["OPEN_STUDIO_FISH_REPO_DIR"] = cfg.resolved_fish_repo
    if cfg.resolved_fish_model:
        env["OPEN_STUDIO_FISH_MODEL_DIR"] = cfg.resolved_fish_model
    return env


def candidate_pythons() -> list[Path]:
    """探测顺序:用户显式覆盖 → App 托管 venv → 本进程解释器。

    托管 venv 排在自动位:用户点过「下载」之后就该直接可用,不必再去设置里填路径——
    那个输入框只是留给"我自己装好了、想用我的环境"的高级用法。
    """
    from app.domain import tts_config

    candidates: list[Path] = []
    configured = tts_config.get().python_path
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.append(tts_config.managed_venv_python())
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


def _source_fields(engine: TtsEngine) -> dict[str, Any]:
    """Fish Speech needs a source checkout separate from its weights — report that piece on
    its own so the card can show it. f5-tts needs no source (pip package)."""
    if engine.id != "fish-speech":
        return {"needs_source": False, "source_ready": False, "source_dir": ""}
    from app.domain import tts_config

    repo = tts_config.get().resolved_fish_repo
    return {"needs_source": True, "source_ready": bool(repo), "source_dir": repo}


def _status_dict(engine: TtsEngine) -> dict[str, Any]:
    live = _store.get(engine.id)
    base = {"id": engine.id, "label": engine.label, "detail": engine.detail,
            "expected_bytes": engine.expected_bytes, **_source_fields(engine)}
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


_FISH_SOURCE_URL = "https://github.com/fishaudio/fish-speech"


def ensure_engine_runtime(engine_id: str) -> None:
    """确保托管 venv 存在、且装好了该引擎的依赖。已就绪则直接返回。

    这一步的存在,就是为了让用户**不必**去设置里指定 Python 解释器:点「下载」时由后端把环境
    建好。重的依赖(torch 等 2.5–3.5GB)落在用户数据目录而不是安装包里——预装会让安装包涨到
    约 4GB,而多数用户根本不用声音克隆。

    失败一律抛 RuntimeError 并带上可读原因;调用方把它落到下载状态上显示给用户。
    """
    from app.domain import tts_config

    engine = _BY_ID[engine_id]
    if not engine.pip_requirements:
        return
    # 已经有解释器能 import 它了(托管 venv 装过,或用户自带环境)→ 什么都不用做。
    if probe_interpreter(engine_id)["worker_ready"]:
        return

    venv_python = tts_config.managed_venv_python()
    if not venv_python.is_file():
        base = tts_config.base_python()
        if not base:
            raise RuntimeError(
                "找不到可用于创建运行环境的 Python。请重装应用,或在设置里手动指定一个 TTS 解释器。"
            )
        _store.set(engine_id, _Live(status="downloading", total=engine.expected_bytes, message="创建运行环境…"))
        tts_config.MANAGED_TTS_VENV.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [base, "-m", "venv", str(tts_config.MANAGED_TTS_VENV)],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode != 0 or not venv_python.is_file():
            raise RuntimeError(f"创建运行环境失败:{(result.stderr or result.stdout)[-300:]}")

    _store.set(
        engine_id,
        _Live(status="downloading", total=engine.expected_bytes, message=f"安装 {engine.label} 运行依赖(数 GB,首次较慢)…"),
    )
    # 装到托管 venv 里。--upgrade 让重试能修好装了一半的环境;超时给足——torch 在慢网络下很久。
    # pip 镜像来自设置页(与「模型下载源」分开:那个管 HF 权重,这个管 Python 包)。
    # 直连 PyPI 拉 2.5–3.5GB 在国内常常慢到不可用,所以这一项值得单独可切。
    pip_args = [str(venv_python), "-m", "pip", "install", "--upgrade"]
    index_url = tts_config.get().pip_index_url
    if index_url:
        pip_args += ["--index-url", index_url]
    result = subprocess.run(
        [*pip_args, *engine.pip_requirements],
        capture_output=True, text=True, timeout=7200, env=_worker_env(),
    )
    if result.returncode != 0:
        raise RuntimeError(f"安装 {engine.label} 运行依赖失败:{(result.stderr or result.stdout)[-300:]}")


def _ensure_fish_source() -> None:
    """Clone the official Fish Speech source into the managed dir (its ``fish_speech`` package
    and ``tools.server.*`` modules aren't on PyPI, so real synthesis needs the checkout).
    No-op if already present; raises with a readable hint on failure."""
    from app.domain import tts_config

    repo = tts_config.MANAGED_FISH_REPO
    if (repo / tts_config.FISH_REPO_MARKER).is_file():
        return
    _store.set("fish-speech", _Live(status="downloading", total=_BY_ID["fish-speech"].expected_bytes,
                                    message="拉取 Fish Speech 源码…"))
    repo.parent.mkdir(parents=True, exist_ok=True)
    if repo.is_dir() and any(repo.iterdir()):
        # A prior half-clone — wipe so `git clone` into it succeeds.
        import shutil

        shutil.rmtree(repo, ignore_errors=True)
    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", _FISH_SOURCE_URL, str(repo)],
            capture_output=True, text=True, timeout=600,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("未找到 git,无法拉取 Fish Speech 源码") from exc
    except subprocess.SubprocessError as exc:
        raise RuntimeError(f"拉取 Fish Speech 源码失败:{exc}") from exc
    if result.returncode != 0 or not (repo / tts_config.FISH_REPO_MARKER).is_file():
        raise RuntimeError(f"拉取 Fish Speech 源码失败:{(result.stderr or '')[-300:]}")


def _download_python() -> str:
    """First existing candidate interpreter — the TTS env that has huggingface_hub, used to
    run the weights snapshot. Falls back to this process's interpreter."""
    import sys

    for python in candidate_pythons():
        if python.is_file():
            return str(python)
    return sys.executable


def _run_download(engine_id: str) -> None:
    """Wrapped so the "downloading" flag can never outlive the thread that set it.

    start_download refuses while _store.downloading() is true. Anything escaping the body
    below — a worker that cannot be spawned, a disk error, a bug — used to leave that flag
    set for the life of the process, so EVERY later download was rejected with
    「已有模型正在下载」 and only a restart cleared it.
    """
    try:
        _download_body(engine_id)
    except Exception as exc:  # noqa: BLE001 — the flag must be released whatever happened
        logger.exception("model download failed")
        _store.set(engine_id, _Live(status="failed", message=str(exc)[:400]))


def _download_body(engine_id: str) -> None:
    engine = _BY_ID[engine_id]
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    # 先备好运行环境(建 venv + 装引擎依赖),再拉权重。顺序不能反:权重是用那个环境里的
    # huggingface_hub 拉的,环境不在就只能退回本后端解释器,拉下来也跑不了合成。
    ensure_engine_runtime(engine_id)
    output_path = settings.data_dir / f"tts-warmup-{engine_id}.wav"

    env = _worker_env()
    progress_dir: Path | None = None
    if engine_id == "fish-speech":
        from app.domain import tts_config

        try:
            _ensure_fish_source()
        except RuntimeError as exc:
            _store.set(engine.id, _Live(status="failed", message=str(exc)[:400]))
            return
        # Snapshot weights into the managed model dir (flat: codec.pth at root) and measure it
        # for live progress — resolved_fish_model won't resolve until codec.pth lands.
        progress_dir = tts_config.MANAGED_FISH_MODEL
        progress_dir.mkdir(parents=True, exist_ok=True)
        env["OPEN_STUDIO_FISH_MODEL_DIR"] = str(progress_dir)
        python = _download_python()
    else:
        python = resolve_tts_python(engine.module)

    def measure() -> int:
        return _dir_size(progress_dir) if progress_dir is not None else _measure(engine)

    started = time.monotonic()
    last_bytes, last_time = measure(), started
    proc = subprocess.Popen(
        [python, str(WORKER_PATH), str(output_path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
    )
    assert proc.stdin is not None
    proc.stdin.write(json.dumps({"action": "warmup", "engine": engine.id}))
    proc.stdin.close()
    # Drain both pipes while polling — an undrained one fills, the child blocks writing it,
    # poll() never returns, and the download appears frozen forever. See ChildProcess.
    child = ChildProcess(proc)
    threading.Thread(target=lambda: [None for _ in child.raw_lines()], daemon=True).start()

    while proc.poll() is None:
        time.sleep(_POLL_SECONDS)
        now = time.monotonic()
        current = measure()
        dt = max(now - last_time, 1e-3)
        speed = max(0.0, (current - last_bytes) / dt)
        remaining = max(0, engine.expected_bytes - current)
        eta = remaining / speed if speed > 100 else None
        elapsed = int(now - started)
        message = _fmt_eta(eta) or f"下载中(已用 {elapsed // 60}分{elapsed % 60:02d}秒)"
        _store.set(engine.id, _Live(status="downloading", downloaded=current, total=engine.expected_bytes,
                                    speed=speed, eta=eta, message=message))
        last_bytes, last_time = current, now

    stderr = child.finish(600)
    if engine_id == "fish-speech":
        # Managed dirs just changed on disk — drop the cached resolution so probe/synthesis
        # pick them up without a restart.
        from app.domain import tts_config

        tts_config.refresh()
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
