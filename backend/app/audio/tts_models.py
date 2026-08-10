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
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.child_process import ChildProcess, run_logged
from app.core.rate import DownloadRate
from app.core.config import settings
from app.core.text import strip_ansi

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
        # 11.01 GB —— 照 Hub 上 fishaudio/s2-pro 的文件清单实测(两个 4~5 GB 的 safetensors
        # + 1.87 GB 的 codec.pth),`snapshot_download` 是整仓拉。此前写的 4.0 GB 是拍出来的:
        # 卡片上那句「4.0 GB」是用户据以决定要不要下的数字,而 `_is_installed` 的 0.6 倍判据
        # 意味着只下了两成就会被判成"已安装",然后合成在运行时炸。
        expected_bytes=11_000_000_000,
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


@lru_cache(maxsize=8)
def _resolve_engine_python(engine_id: str) -> str | None:
    """探测本身。**只有这一处**会去起子进程试 import。

    带缓存是因为它不便宜:每个候选解释器一次子进程,最长各等两分钟。而配音面板、设置页、
    引擎列表都要问这个问题 —— 不缓存的话,光是打开一次面板就能起好几个 python。
    装完引擎之后由 `clear_runtime_probes()` 作废,答案不会停在"装之前"。
    """
    code = _probe_code(engine_id)
    if code is None:  # 依赖的资源(fish 检出/权重)不齐,谈不上就绪
        return None
    for python in candidate_pythons():
        if not python.is_file():
            continue
        try:
            probe = run_logged([str(python), "-c", code], capture_output=True, timeout=120, what="克隆引擎探测", level=logging.DEBUG)
        except (subprocess.SubprocessError, OSError):
            continue
        if probe.returncode == 0:
            return str(python)
    return None


def resolve_engine_python(engine_id: str) -> str | None:
    """能真的跑这个引擎的解释器,**没有就是没有**。

    这里曾经在找不到时回退到后端自己的解释器,注释写着"worker 的占位音在那儿也能生成一个
    合法 wav"—— 而那正是用户说的「根本克隆不了」:合成照跑、任务报成功、素材库里多一段正弦音。
    一个跑不了的引擎的正确答案是 None,不是"随便找个解释器凑合"。

    这也是**唯一**一处回答"哪个解释器能跑这个引擎"。此前 `probe_interpreter` 自己又实现了
    一遍:设置页问的是它,合成问的是另一个带兜底的 —— 同一个问题两处实现,于是两个答案。
    """
    return _resolve_engine_python(engine_id)


def clear_runtime_probes() -> None:
    """装完引擎、改完解释器路径之后叫一声,否则答案会停在"装之前"。"""
    _resolve_engine_python.cache_clear()


def probe_interpreter(engine_id: str) -> dict[str, Any]:
    """设置页要的形状。答案来自上面那一处,不另算一遍。"""
    python = resolve_engine_python(engine_id)
    return {"worker_ready": bool(python), "worker_python": python or ""}


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
        # **实测越过估计值 = 这个估计已经被证伪**,那一刻起就不该再拿它当分母:界面会画出一根
        # 满的条(用户截图里是 `5.2 GB / 4.0 GB`、100%,而它还在下),而"满"说的是"下完了"。
        # 和装运行环境那一阶段同一条规矩:没有诚实的分母就不报分母,只报下了多少、在做什么。
        total = 0 if live.total and live.downloaded > live.total else live.total
        return {**base, "status": "downloading", "downloaded_bytes": live.downloaded,
                # **不回落到权重大小**:装运行环境那一阶段没有可报的总量(跑的是 pip),
                # 顶一个权重的字节数上去,界面就会画出"0 MB / 1.5 GB"这种量错了东西的进度条。
                # 光在 _Live 里置 0 不够 —— 这个 `or` 会把它填回来,转写那边就是这么被填回来的。
                "total_bytes": total, "speed_bps": live.speed,
                "eta_seconds": live.eta, "message": live.message}
    if live is not None and live.status == "failed":
        return {**base, "status": "failed", "downloaded_bytes": _measure(engine),
                "total_bytes": engine.expected_bytes, "message": live.message}
    if _is_installed(engine):
        # 权重齐了不等于跑得起来:pip 包可能压根没装(权重是别的工具下的,或者托管 venv 被删了)。
        # 此前这里一律说「已安装,声音克隆可用」,而合成那边探测解释器失败 —— 页面说可用,
        # 一点就说不可用。两句话得出自同一次判断。
        ready = resolve_engine_python(engine.id) is not None
        return {**base, "status": "installed", "runtime_ready": ready,
                "downloaded_bytes": _measure(engine), "total_bytes": engine.expected_bytes,
                "message": "已安装,声音克隆可用" if ready
                else "权重已下好,但还没有解释器装了它 —— 再点一次「下载」会把运行环境补上"}
    return {**base, "status": "missing", "runtime_ready": False, "downloaded_bytes": _measure(engine),
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


#: HuggingFace 连不上时抛的那几个名字。命中就多说一句 —— 这台机器上镜像下不动、
#: 而直连官方是通的,而用户没有任何线索能想到去动「模型下载源」。
_HUB_UNREACHABLE = ("LocalEntryNotFoundError", "ConnectionError", "ReadTimeout", "ProxyError",
                    "check your connection", "Max retries exceeded")


def _explain_failure(stderr: str) -> str:
    """把子进程的最后一句话变成卡片上那句话。

    此前这里是 `stderr or "下载未完成,可能引擎未安装"` —— 而 worker 把异常吞了、退出码 0、
    stderr 空,于是永远走后半句。那是一句**猜测**,还猜错了方向:用户会去重装引擎,
    而真正坏掉的是下载源。
    """
    # 先去掉终端颜色码:子进程以为自己在终端里,而这句话的去处是浏览器。
    text = strip_ansi(stderr or "").strip()
    if not text:
        return "下载没有完成,而子进程没有留下原因 —— 请重试一次;若仍然如此请反馈。"
    # traceback 的最后一行就是异常本身,比尾部 400 个字符可读得多。
    last = next((line.strip() for line in reversed(text.splitlines()) if line.strip()), text)
    if any(marker in text for marker in _HUB_UNREACHABLE):
        from app.domain import tts_config

        endpoint = tts_config.get().hf_endpoint
        # 截断只截**错误本身**,不截后面那半句 —— 那是整条消息里唯一能行动的部分。
        return (
            f"连不上模型下载源({endpoint}):{_clip(last, 220)}"
            " —— 在上面的「模型下载源」换一个(镜像下不动时,官方直连往往反而是通的)再重试。"
        )
    return _clip(last, 400)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[:limit]}…"


def forget_failures() -> None:
    """丢掉所有"失败"状态,不动正在下的那些。

    改了下载源 / 解释器之后叫一声:上一次失败说的是**改之前**那套配置,而它长得像当前状态 ——
    用户照着它去排查一个已经不存在的设置(实测:源已经换成 ModelScope,卡片还在说 hf-mirror)。
    """
    for engine in CATALOG:
        live = _store.get(engine.id)
        if live is not None and live.status == "failed":
            _store.clear(engine.id)


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
    _store.set(engine.id, _Live(status="downloading", message="准备下载…"))
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
        _store.set(engine_id, _Live(status="downloading", message="创建运行环境…"))
        tts_config.MANAGED_TTS_VENV.parent.mkdir(parents=True, exist_ok=True)
        result = run_logged(
            [base, "-m", "venv", str(tts_config.MANAGED_TTS_VENV)],
            capture_output=True, text=True, timeout=600, what="创建克隆运行环境")
        if result.returncode != 0 or not venv_python.is_file():
            raise RuntimeError(f"创建运行环境失败:{(result.stderr or result.stdout)[-300:]}")

    _store.set(
        engine_id,
        # 这一阶段**不报字节**:跑的是 pip(装 torch 等),它一个字节都不会落进权重缓存,
        # 而进度是按那个目录的增长算的。借用权重的 1.5GB 当分母,结果就是永远 0 MB / 1.5 GB。
        # 两件事量纲不同,就别共用一个进度条 —— 只报"在做哪一步"。
        _Live(status="downloading", message=f"安装 {engine.label} 运行依赖(数 GB,首次较慢)…"),
    )
    # 装到托管 venv 里。--upgrade 让重试能修好装了一半的环境;超时给足——torch 在慢网络下很久。
    # pip 镜像来自设置页(与「模型下载源」分开:那个管 HF 权重,这个管 Python 包)。
    # 直连 PyPI 拉 2.5–3.5GB 在国内常常慢到不可用,所以这一项值得单独可切。
    pip_args = [str(venv_python), "-m", "pip", "install", "--upgrade"]
    index_url = tts_config.get().pip_index_url
    if index_url:
        pip_args += ["--index-url", index_url]
    result = run_logged(
        [*pip_args, *engine.pip_requirements],
        capture_output=True, text=True, timeout=7200, env=_worker_env(), what="安装克隆运行依赖")
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
    # 同上:拉的是 git 源码,不是权重 —— 没有分母就别摆一个。
    _store.set("fish-speech", _Live(status="downloading", message="拉取 Fish Speech 源码…"))
    repo.parent.mkdir(parents=True, exist_ok=True)
    if repo.is_dir() and any(repo.iterdir()):
        # A prior half-clone — wipe so `git clone` into it succeeds.
        import shutil

        shutil.rmtree(repo, ignore_errors=True)
    try:
        result = run_logged(
            ["git", "clone", "--depth", "1", _FISH_SOURCE_URL, str(repo)],
            capture_output=True, text=True, timeout=600, what="拉取 Fish Speech 源码")
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
        # 预热是**去下权重**:优先能跑引擎的那个解释器,没有就退到第一个存在的候选
        # (装了 f5-tts 但还没下权重时,它就是那一个)。跑不起来由预热自己的状态去报。
        python = resolve_engine_python(engine.id) or _download_python()

    def measure() -> int:
        return _dir_size(progress_dir) if progress_dir is not None else _measure(engine)

    started = time.monotonic()
    last_bytes = measure()
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

    # 速度按**最近一段**算,不是按最近 1.5 秒:下载器成块写盘,单窗口读数会在 0 和几百 MB/s
    # 之间跳,而 ETA 在跳到 0 的那一瞬就消失 —— 用户看到的那一眼恰好是 0 的那一眼。
    rate = DownloadRate()
    rate.update(last_bytes, at=started)
    while proc.poll() is None:
        time.sleep(_POLL_SECONDS)
        now = time.monotonic()
        current = measure()
        speed = rate.update(current, at=now)
        eta = rate.eta(remaining=max(0, engine.expected_bytes - current))
        elapsed = int(now - started)
        message = _fmt_eta(eta) or f"下载中(已用 {elapsed // 60}分{elapsed % 60:02d}秒)"
        _store.set(engine.id, _Live(status="downloading", downloaded=current, total=engine.expected_bytes,
                                    speed=speed, eta=eta, message=message))

    stderr = child.finish(600)
    if engine_id == "fish-speech":
        # Managed dirs just changed on disk — drop the cached resolution so probe/synthesis
        # pick them up without a restart.
        from app.domain import tts_config

        tts_config.refresh()
    clear_runtime_probes()  # 刚装完,探测结果必须重算
    if _is_installed(engine):
        _store.clear(engine.id)
    else:
        reason = _explain_failure(stderr)
        logger.warning("下载 %s 失败:%s", engine.id, (stderr or "(子进程什么都没说)")[-1200:])
        _store.set(engine.id, _Live(status="failed", message=reason))
    for path in (output_path, Path(str(output_path) + ".json")):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


__all__ = ["CATALOG", "list_status", "get_status", "start_download", "is_installed",
           "resolve_engine_python", "clear_runtime_probes"]
