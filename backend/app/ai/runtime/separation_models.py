"""人声/背景音分离引擎的本地运行时:托管 venv、权重在哪、跑不跑得起来。

和 `asr_models` / `tts_models` 同一个形状,共用同一批底层件(`interpreter.base_python`、
`pip_install.install`、`run_logged`、`runtime/download_state.ProbeCache`),**但有自己的 venv**。
理由是 asr_models 里那句被违反过一次才写下的话:

    两边的依赖会打架(不同的 torch 版本),而共用一个 venv 意味着装一边可能弄坏另一边。

demucs 又是一个 torch。塞进转写或克隆那个 venv,代价是把用户已经在用的引擎弄坏,而那种故障
出现的地方离原因很远(下次转写报一句 import 错误,没有人会联想到"因为装了分离")。

**"装没装"的判据是 import 得进来,不是解释器在不在。** 这一条是补回来的:此前只看
`venv/bin/python` 这个文件存不存在,于是一个 pip 装到一半断掉的 venv —— 解释器建好了、依赖
没齐 —— 在设置页上写着「已安装」,而 `ensure_runtime` 看到"已安装"就早返回、永远不去修它。
用户看到的是三个字「已安装」配一句「这个运行环境里没有 demucs:No module named 'numpy'」,
两句话都没说谎,只是在回答不同的问题。转写那边为同一件事付过账(见 asr_models.runtime_ready),
所以这里用同一个判据:起子进程 `import <引擎真正要用的模块>`。

**这个 Module 跑在后端进程里**,只管"环境和权重";真正的分离跑在 `workers/separation.py`,
由这个 venv 的解释器起成子进程 —— 重活出进程,接缝画在进程边界(ADR-0001)。
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.ai.runtime.download_state import ProbeCache
from app.ai.runtime.install_state import FAILED, INSTALLING, InstallProgress, InstallStore
from app.core import interpreter, pip_install
from app.core.child_process import run_logged
from app.core.config import settings
from app.core.text import blame_line

logger = logging.getLogger(__name__)

#: 探测子进程的超时。import demucs 会连着把 torch 拉起来,冷启动在慢盘上要十几秒。
_PROBE_TIMEOUT_SECONDS = 180


@dataclass(frozen=True)
class SeparationEngineSpec:
    """一个分离引擎:装什么、探什么。

    `module` 和 `requirements` 写在**一起**,因为它们是同一件事的两半 —— 装完之后要能 import
    的就是它。分成两张按引擎 id 对齐的表,迟早有人只改其中一张。
    """

    id: str
    #: 探测时 import 的模块。写 worker 真正用的那个(`demucs.api`,不是 `demucs`)——
    #: 判据要和运行时用的东西一致,否则"探得过、跑不了"照样存在。
    module: str
    requirements: tuple[str, ...]


#: 引擎 id → 它的 venv 里装什么、探什么。
#:
#: demucs 走 PyPI;torch 不写死版本 —— 钉死会在新 Python 上装不出来,而这一层不需要复现性,
#: 它需要的是"能跑"。CPU 也能跑,只是慢;有 MPS/CUDA 时 demucs 自己会用。
ENGINES: dict[str, SeparationEngineSpec] = {
    #: demucs>=4.0.1 才有 demucs.api(worker 用的是它,不是命令行) —— 钉下限不钉上限。
    "demucs": SeparationEngineSpec("demucs", "demucs.api", ("demucs>=4.0.1", "torch", "torchaudio")),
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


#: 安装进度(内存那一半;盘上那个 venv 跑不跑得起来才是静息时的事实源)。
_store = InstallStore()

#: 探过没探过(见 runtime/download_state.ProbeCache)。装完之后 clear_runtime_probes()。
_probes = ProbeCache()


def managed_venv_dir(engine: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in engine)
    return MANAGED_SEPARATION_ROOT / f"venv-{safe}"


def managed_venv_python(engine: str) -> Path:
    #: 和 asr_models._venv_python 同一个写法(Windows 下是 Scripts/python.exe)。
    windows = os.name == "nt"
    venv = managed_venv_dir(engine)
    return venv / ("Scripts" if windows else "bin") / ("python.exe" if windows else "python")


@lru_cache(maxsize=4)
def probe_runtime(engine: str) -> tuple[bool, str]:
    """(import 得进来吗, 进不来时子进程说的那句话)。

    **唯一的探测实现**,也是唯一那份缓存 —— 守着这句话的是
    `tests/test_runtime_readiness_is_an_import_probe.py`(它同时钉住"判据是 import 得进来")。
    带上原因是因为"跑不起来"有很多种,而用户能拿来
    搜一下的只有那一句(`No module named 'numpy'`);把它扔掉,设置页就只剩一个没有下文的
    「未安装」。

    探测要起子进程,所以缓存;装完之后调 `clear_runtime_probes()`。
    """
    spec = ENGINES.get(engine)
    if spec is None:
        return False, f"不认识的分离引擎:{engine}"
    python = managed_venv_python(engine)
    if not python.is_file():
        return False, ""
    try:
        probe = run_logged(
            [str(python), "-c", f"import {spec.module}"],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            what="音频分离引擎探测",
            level=logging.DEBUG,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return False, str(exc)
    if probe.returncode == 0:
        return True, ""
    return False, blame_line(probe.stderr or probe.stdout, fallback="")


def runtime_ready(engine: str) -> bool:
    """这个引擎现在跑得起来吗 —— 也就是它那个 venv 里 `import` 得进来吗。

    和"权重下没下"是两件独立的事:权重是第一次分离时 demucs 自己拉的,而 import 不进来就连
    拉都开始不了。**这里不判断权重**,只判断环境。
    """
    return probe_runtime(engine)[0]


def runtime_blame(engine: str) -> str:
    """跑不起来时子进程说的那句话(跑得起来就是空串)。"""
    return probe_runtime(engine)[1]


def probe_in_background(engine: str) -> None:
    _probes.probe_in_background(engine, lambda: runtime_ready(engine))


def refresh_runtime_status(engine: str) -> bool:
    """现在就探一次并记下来(装完之后调,以及测试里要确定答案时)。"""
    return bool(_probes.remember(engine, runtime_ready(engine)))


def runtime_status(engine: str) -> tuple[bool, bool]:
    """(跑得起来吗, 测过了吗)。没测过就在后台起一次,先把已知的给出去。

    列状态是一次纯读的请求,而探测要起子进程 import torch —— 十几秒。**永远不等**:
    "还没测过"和"测过了、跑不起来"是两回事,把前者说成后者就是拿未知冒充结论。
    """
    value, known = _probes.known(engine)
    if known:
        return bool(value), True
    probe_in_background(engine)
    return False, False


def clear_runtime_probes() -> None:
    """装好环境之后把探测缓存清掉 —— 只有一处要清,因为只有一份缓存。"""
    # getattr:测试会把探测换成普通函数(没有 cache_clear)。清缓存是清理动作,不是判据,
    # 不该因为"被替换过"就炸。
    getattr(probe_runtime, "cache_clear", lambda: None)()
    _probes.invalidate()


def ensure_runtime(engine: str) -> None:
    """建 venv、装依赖,直到这个引擎**真的 import 得进来**。

    跑得起来就什么都不做 —— 不碰用户自带的环境。跑不起来就一路补到底,**包括解释器已经在、
    依赖却不全的那种**:此前这里的判据是"解释器这个文件在不在",于是半装的 venv 走到这一行
    直接返回,谁也不去修它,而分离每次都在同一个地方炸(见模块说明)。pip 装齐过的包会跳过,
    所以对已经装好的机器,这一步的代价只是一次 pip 的空转。
    """
    spec = ENGINES.get(engine)
    if spec is None:
        raise RuntimeError(f"不认识的分离引擎:{engine}")
    if runtime_ready(engine):
        return

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
            spec.requirements,
            what="安装音频分离运行依赖",
            index_url=runtime_config.get().pip_index_url,
        )
    except pip_install.PipInstallError as exc:
        raise RuntimeError(f"安装 {engine} 运行依赖失败:{exc}") from exc

    # **装完要再探一次**,而且要认这次的答案:pip 退 0 不等于 import 得进来(装错轮子、
    # 平台不匹配、依赖被别的包降级),而那正是这次要修的那种故障。
    clear_runtime_probes()
    if not refresh_runtime_status(engine):
        reason = runtime_blame(engine) or "没有留下原因"
        raise RuntimeError(f"装完 {engine} 之后它仍然跑不起来:{reason}")


# ---------------------------------------------------------------------------
# 给设置页的那一面
# ---------------------------------------------------------------------------
def list_status() -> list[dict[str, Any]]:
    """每个分离引擎现在是什么状态。

    **装没装是从盘上那个 venv 里问出来的**,不是记在内存里的 —— 内存那份只在"正在装"和
    "刚失败"时有话说。重启之后内存清空,而环境还在盘上:这时状态该是"已安装"。

    问要起子进程,所以这里**不等**:没探过就先报 `runtime_checked=false`,界面据此接着轮询
    (见 frontend/features/settings/pollWhileUnsettled)。
    """
    return [_status_dict(engine) for engine in ENGINES]


def _status_dict(engine: str) -> dict[str, Any]:
    ready, checked = runtime_status(engine)
    row = {
        "engine": engine,
        "label": f"sepEngine_{engine}",
        "runtime_ready": ready,
        #: 「还没测过」是第三种答案,不是 false 的一种写法(同转写、克隆那两页)。
        "runtime_checked": checked,
        **_store.status_fields(engine, ready=ready),
    }
    #: 解释器在、却 import 不进来 —— 半装的环境。说清楚它是坏的、且「安装」按钮能修好它,
    #: 比一个光秃秃的「未安装」诚实:用户明明记得自己装过。
    if checked and not ready and not row["message"] and managed_venv_python(engine).is_file():
        row["message"] = "sepMsg_brokenRuntime"
        row["message_params"] = {}
    return row


def start_install(engine: str) -> dict[str, Any]:
    """在后台线程里装。**不阻塞请求** —— 建 venv 加装 torch 是几分钟到几十分钟的事。"""
    if engine not in ENGINES:
        raise KeyError(engine)
    #: 这里**现探**(不是读缓存):用户刚点了按钮,等一次探测好过给一个凭旧答案的早返回。
    if refresh_runtime_status(engine):
        return _status_dict(engine)
    _store.begin(engine, "dlMsg_creatingRuntime")
    threading.Thread(target=_run_install, args=(engine,), daemon=True).start()
    return _status_dict(engine)


def _run_install(engine: str) -> None:
    try:
        _store.set(engine, InstallProgress(INSTALLING, "dlMsg_installingDeps", {"engine": engine}))
        ensure_runtime(engine)
    except Exception as exc:  # noqa: BLE001 — 失败要留在状态里给用户看,不是吞掉
        logger.warning("安装分离引擎 %s 失败:%s", engine, exc)
        #: 原因**原样带出来**:pip 说不清时用户至少能把那句话搜一下。
        _store.set(engine, InstallProgress(FAILED, str(exc)))
        return
    _store.clear(engine)
