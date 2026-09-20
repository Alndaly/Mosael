"""要装的降噪引擎:DeepFilterNet 的独立二进制。

**为什么是二进制,不是 Python 包**(ADR-0017 修订):`deepfilternet` 0.5.6 在 import 时要
`torchaudio.backend.common`,新版 torchaudio 已经删了它,而 Python 3.13 上装不出够老的 torch ——
实测 import 就失败。官方同一个版本发布了 Rust 写的 `deep-filter` 命令行,模型编译在里面,
不要 torch、不要 venv,一个 30 MB 左右的文件。

**装是设置里显式的一步**(同分离):往这台机器上下载并运行一个可执行文件,不该藏在"点一下
降噪"后面。下载按**固定的 SHA-256** 校验,对不上就拒装 —— 发布页上的文件被换掉时,宁可装
不上,也不去运行一个没见过的东西。

这个 Module 跑在后端进程里,只管"文件在不在、装不装";降噪本身由适配器起子进程去跑。
"""

from __future__ import annotations

import hashlib
import logging
import os
import platform
import sys
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.ai.runtime.install_state import FAILED, InstallProgress, InstallStore
from app.core.config import settings

logger = logging.getLogger(__name__)

DEEPFILTER = "deepfilternet"
DEEPFILTER_VERSION = "0.5.6"
_RELEASE_URL = "https://github.com/Rikorose/DeepFilterNet/releases/download/v{version}/{asset}"


@dataclass(frozen=True)
class _Binary:
    asset: str
    sha256: str
    size: int


#: (平台, 架构) → 发布页上的那个文件。哈希是下载后**实算**的,不是抄的(发布页没给)。
_DEEPFILTER_BINARIES: dict[tuple[str, str], _Binary] = {
    ("darwin", "arm64"): _Binary(
        "deep-filter-0.5.6-aarch64-apple-darwin",
        "4601e7f4e4c03e59a4c5b5000216ef3add3e808799cfccd95e14e83ea4611081",
        27_877_081,
    ),
    ("darwin", "x86_64"): _Binary(
        "deep-filter-0.5.6-x86_64-apple-darwin",
        "d3be84003acb7c23e738ad7f70a158ec779a8d233a82e7fa3e717d112eb5b50f",
        29_933_512,
    ),
    ("win32", "amd64"): _Binary(
        "deep-filter-0.5.6-x86_64-pc-windows-msvc.exe",
        "75e11fa16445f560cb6b021521ddb89e89270d13b83089705d98776f58fd7915",
        26_912_256,
    ),
    ("linux", "x86_64"): _Binary(
        "deep-filter-0.5.6-x86_64-unknown-linux-musl",
        "70775e251eee44c0f2451a1e833326cf8bcbbe304d3e7cd12851e6fce72ef7da",
        36_417_296,
    ),
}

#: 装到哪。应用自己的数据目录 —— 卸载时有一个地方可以整个删掉。
MANAGED_DENOISE_ROOT = settings.data_dir / "denoise"

_store = InstallStore()


def _this_platform() -> tuple[str, str]:
    machine = platform.machine().lower()
    return sys.platform, {"aarch64": "arm64", "x86-64": "x86_64"}.get(machine, machine)


def deepfilter_binary_spec() -> _Binary | None:
    """这台机器该下哪个文件;没有对应的发布就是 None。"""
    return _DEEPFILTER_BINARIES.get(_this_platform())


def deepfilter_path() -> Path:
    suffix = ".exe" if sys.platform == "win32" else ""
    return MANAGED_DENOISE_ROOT / f"deep-filter-{DEEPFILTER_VERSION}{suffix}"


@lru_cache(maxsize=1)
def deepfilter_ready() -> bool:
    """装好了没有。判据是文件在不在 —— 它只会以校验过的样子出现在这个路径上(见 _install)。

    缓存住:"能用吗"会被问很多遍。装完 `deepfilter_ready.cache_clear()`。
    """
    return deepfilter_path().is_file()


def runtime_ready(engine: str) -> bool:
    return engine == DEEPFILTER and deepfilter_ready()


# ---------------------------------------------------------------------------
# 给设置页的那一面
# ---------------------------------------------------------------------------
INSTALLABLE = (DEEPFILTER,)


def install_status(engine: str) -> dict[str, Any]:
    """这个引擎装没装。这台机器没有对应的发布时是 `unsupported` —— 摆一个装不上的按钮不如直说。"""
    if engine == DEEPFILTER and deepfilter_binary_spec() is None:
        return {"status": "unsupported", "message": "", "message_params": {}}
    ready = runtime_ready(engine)
    fields = _store.status_fields(engine, ready=ready)
    spec = deepfilter_binary_spec()
    fields["size_bytes"] = spec.size if spec else 0
    return fields


def start_install(engine: str) -> dict[str, Any]:
    """在后台线程里装。**不阻塞请求**。"""
    if engine not in INSTALLABLE:
        raise KeyError(engine)
    if deepfilter_binary_spec() is None:
        raise RuntimeError("这个平台没有 DeepFilterNet 的发布文件")
    if runtime_ready(engine):
        return install_status(engine)
    _store.begin(engine, "dlMsg_downloading")
    threading.Thread(target=_run_install, args=(engine,), daemon=True).start()
    return install_status(engine)


def _run_install(engine: str) -> None:
    try:
        _install_deepfilter()
    except Exception as exc:  # noqa: BLE001 — 失败要留在状态里给用户看,不是吞掉
        logger.warning("安装降噪引擎 %s 失败:%s", engine, exc)
        _store.set(engine, InstallProgress(FAILED, str(exc)))
        return
    _store.clear(engine)


def _install_deepfilter() -> Path:
    from app.ai.media_transfer import download_to_path

    spec = deepfilter_binary_spec()
    if spec is None:
        raise RuntimeError("这个平台没有 DeepFilterNet 的发布文件")
    target = deepfilter_path()
    staging = target.with_name(f"{target.name}.download")
    url = _RELEASE_URL.format(version=DEEPFILTER_VERSION, asset=spec.asset)
    try:
        download_to_path(url, staging, timeout=600)
        digest = _sha256(staging)
        if digest != spec.sha256:
            # 不说"下载失败"—— 下载是成功的,只是下来的东西不是我们核对过的那一个。
            raise RuntimeError(f"下载到的文件校验不符(SHA-256 {digest[:12]}…),已丢弃,没有安装")
        if os.name != "nt":
            staging.chmod(0o755)
        # 校验通过才挪到正式位置:deepfilter_ready 只看这个路径,半截或被换过的文件永远到不了这里。
        staging.replace(target)
    finally:
        staging.unlink(missing_ok=True)
    deepfilter_ready.cache_clear()
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
