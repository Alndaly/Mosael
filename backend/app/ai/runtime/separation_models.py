"""人声/背景音分离引擎的本地运行时:托管 venv、权重在哪、跑不跑得起来。

和 `asr_models` / `tts_models` 同一个形状,共用同一批底层件(`interpreter.base_python`、
`pip_install.install`、`run_logged`),**但有自己的 venv**。理由是 asr_models 里那句被违反过
一次才写下的话:

    两边的依赖会打架(不同的 torch 版本),而共用一个 venv 意味着装一边可能弄坏另一边。

demucs 又是一个 torch。塞进转写或克隆那个 venv,代价是把用户已经在用的引擎弄坏,而那种故障
出现的地方离原因很远(下次转写报一句 import 错误,没有人会联想到"因为装了分离")。

**这个 Module 跑在后端进程里**,只管"环境和权重";真正的分离跑在 `workers/separation.py`,
由这个 venv 的解释器起成子进程 —— 重活出进程,接缝画在进程边界(ADR-0001)。
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core import interpreter, pip_install
from app.core.child_process import run_logged
from app.core.config import settings
from app.core.text import blame_line

logger = logging.getLogger(__name__)

#: 引擎 id → 装进它自己 venv 的依赖。
#:
#: demucs 走 PyPI;torch 不写死版本 —— 钉死会在新 Python 上装不出来,而这一层不需要复现性,
#: 它需要的是"能跑"。CPU 也能跑,只是慢;有 MPS/CUDA 时 demucs 自己会用。
ENGINE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    #: demucs>=4.0.1 才有 demucs.api(worker 用的是它,不是命令行) —— 钉下限不钉上限。
    "demucs": ("demucs>=4.0.1", "torch", "torchaudio"),
}

#: 托管的分离运行环境。和 asr / tts 的根目录分开,理由见模块说明。
MANAGED_SEPARATION_ROOT = settings.data_dir / "separation"

#: 权重落在哪。demucs 默认写 `~/.cache/torch/hub/checkpoints`,而那是**用户主目录**里的东西 ——
#: 应用装的东西要落在应用自己的数据目录,卸载时才有一个地方可以整个删掉。
#: 这个路径通过 TORCH_HOME 交给 worker。
TORCH_HOME = MANAGED_SEPARATION_ROOT / "torch"

#: 默认模型。htdemucs 是 demucs v4 的默认包,四分离(人声/鼓/贝斯/其它),约 300MB。
#: 我们只要人声和"其余全部",后者由 worker 把另外三条相加 —— 见 workers/separation.py。
DEFAULT_MODEL = "htdemucs"


# ---------------------------------------------------------------------------
# 安装状态(只在内存里;盘上有没有那个解释器才是静息时的事实源)
# ---------------------------------------------------------------------------
@dataclass
class _Live:
    status: str = "idle"  # "installing" | "failed"
    message: str = ""
    #: message 是 key 时的模板参数(见 core/i18n.t)。翻译在出口做。
    params: dict[str, str] = field(default_factory=dict)


class _Store:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._live: dict[str, _Live] = {}

    def get(self, engine: str) -> _Live | None:
        with self._lock:
            live = self._live.get(engine)
            return None if live is None else _Live(**live.__dict__)

    def set(self, engine: str, live: _Live) -> None:
        with self._lock:
            self._live[engine] = live

    def clear(self, engine: str) -> None:
        with self._lock:
            self._live.pop(engine, None)


_store = _Store()


def managed_venv_dir(engine: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in engine)
    return MANAGED_SEPARATION_ROOT / f"venv-{safe}"


def managed_venv_python(engine: str) -> Path:
    #: 和 asr_models._venv_python 同一个写法(Windows 下是 Scripts/python.exe)。
    windows = os.name == "nt"
    venv = managed_venv_dir(engine)
    return venv / ("Scripts" if windows else "bin") / ("python.exe" if windows else "python")


@lru_cache(maxsize=4)
def runtime_ready(engine: str) -> bool:
    """这个引擎现在跑得起来吗。

    判据是**解释器在不在**,不是"权重下没下":权重是第一次分离时 demucs 自己拉的,而没有
    解释器就连拉都开始不了。两件事分开问,是因为它们完全可以一真一假(见 asr_models.runtime_ready
    那段:三行「已安装」配一句「未找到可用的转写环境」,两句话都没说谎)。

    缓存住:这个函数会被"能力可用吗"问很多遍。装完调 `runtime_ready.cache_clear()`。
    """
    return managed_venv_python(engine).is_file()


def ensure_runtime(engine: str) -> None:
    """建 venv、装依赖。已经好了就什么都不做 —— 不碰用户自带的环境。"""
    if runtime_ready(engine):
        return
    requirements = ENGINE_REQUIREMENTS.get(engine)
    if not requirements:
        raise RuntimeError(f"不认识的分离引擎:{engine}")

    venv_dir = managed_venv_dir(engine)
    venv_python = managed_venv_python(engine)
    if not venv_python.is_file():
        # **不能用 sys.executable**:打包版里它是应用自己,`-m venv` 会把后端再启动一遍
        # (asr_models 里记着这笔账:然后把 uvicorn「端口已占用」当成创建失败的原因端给用户)。
        base = interpreter.base_python()
        if not base:
            raise RuntimeError("找不到可用于创建运行环境的 Python 解释器")
        venv_dir.parent.mkdir(parents=True, exist_ok=True)
        created = run_logged(
            [base, "-m", "venv", str(venv_dir)],
            capture_output=True,
            text=True,
            timeout=600,
            what="创建音频分离运行环境",
        )
        if created.returncode != 0 or not venv_python.is_file():
            raise RuntimeError(
                f"创建运行环境失败:{blame_line(created.stderr or created.stdout, fallback='没有留下原因')}"
            )

    # 和转写、克隆走同一个安装器,包括设置页那个 pip 镜像 —— 同一台机器上不该"一个走镜像、
    # 一个直连 PyPI",而那个设置项写的就是「装引擎依赖时用的 pip 索引」。
    from app.ai.runtime import config as runtime_config

    try:
        pip_install.install(
            venv_python,
            requirements,
            what="安装音频分离运行依赖",
            index_url=runtime_config.get().pip_index_url,
        )
    except pip_install.PipInstallError as exc:
        raise RuntimeError(f"安装 {engine} 运行依赖失败:{exc}") from exc
    runtime_ready.cache_clear()


# ---------------------------------------------------------------------------
# 给设置页的那一面
# ---------------------------------------------------------------------------
def list_status() -> list[dict[str, Any]]:
    """每个分离引擎现在是什么状态。

    **装没装是从盘上看出来的,不是记在内存里的** —— 内存那份只在"正在装"和"刚失败"时有话说。
    重启之后内存清空,而解释器还在盘上:这时状态该是"已安装",不是"未知"。
    """
    return [_status_dict(engine) for engine in ENGINE_REQUIREMENTS]


def _status_dict(engine: str) -> dict[str, Any]:
    live = _store.get(engine)
    ready = runtime_ready(engine)
    status = "installed" if ready else "missing"
    if live is not None and live.status in {"installing", "failed"} and not ready:
        status = live.status
    return {
        "engine": engine,
        "label": f"sepEngine_{engine}",
        "status": status,
        "runtime_ready": ready,
        "message": live.message if live else "",
        "message_params": dict(live.params) if live else {},
    }


def start_install(engine: str) -> dict[str, Any]:
    """在后台线程里装。**不阻塞请求** —— 建 venv 加装 torch 是几分钟到几十分钟的事。"""
    if engine not in ENGINE_REQUIREMENTS:
        raise KeyError(engine)
    if runtime_ready(engine):
        return _status_dict(engine)
    live = _store.get(engine)
    if live is not None and live.status == "installing":
        raise RuntimeError("这个引擎已经在安装中")
    _store.set(engine, _Live(status="installing", message="dlMsg_creatingRuntime"))
    threading.Thread(target=_run_install, args=(engine,), daemon=True).start()
    return _status_dict(engine)


def _run_install(engine: str) -> None:
    try:
        _store.set(engine, _Live(status="installing", message="dlMsg_installingDeps", params={"engine": engine}))
        ensure_runtime(engine)
    except Exception as exc:  # noqa: BLE001 — 失败要留在状态里给用户看,不是吞掉
        logger.warning("安装分离引擎 %s 失败:%s", engine, exc)
        #: 原因**原样带出来**:pip 说不清时用户至少能把那句话搜一下。
        _store.set(engine, _Live(status="failed", message=str(exc)))
        return
    _store.clear(engine)
