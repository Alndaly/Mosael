"""本机识别 NSFW 预览图要的那份权重(ADR 0038 §9「本地识别怎么带」):Marqo/nsfw-image-detection-384,Apache-2.0,
22.4 MB 的一个 safetensors 文件。

**不进安装包,第一次用时下载**:地址钉死在 HuggingFace 的一个版本上(`REVISION`),走设置里选的那个 HuggingFace 源
(官方 / 镜像,见 runtime/config);下完按固定的 SHA-256 校验,对不上就拒装 —— 和降噪引擎同一套(InstallStore 记进度、
download_to_path 下载、校验通过才挪到正式位置),所以「在不在」只看正式位置上有没有这个文件。落在
`<数据目录>/nsfw-classifier/`,卸载时一个目录删掉。

下载是部署级的动作(往这台机器上放东西),路由只给部署管理员;识别本身在 domain/model_nsfw_local。
"""

from __future__ import annotations

import hashlib
import logging
import threading
from pathlib import Path
from typing import Any

from app.ai.runtime.errors import RuntimeSetupError, failure_message
from app.ai.runtime.install_state import FAILED, InstallProgress, InstallStore
from app.core.config import settings

logger = logging.getLogger(__name__)

NSFW_CLASSIFIER = "nsfw-classifier"
REPO = "Marqo/nsfw-image-detection-384"
#: 钉死的版本(HuggingFace 上这个仓库 2024-11-27 的那一次提交)
REVISION = "0c26ec22111b83f106d72a55f611ec35962bcb65"
#: 那个文件的 SHA-256 和大小(HuggingFace 的 LFS 指针上写的;下载后实算核对过)
SHA256 = "6bf2e0f64a1d20169736c2836e3a787b12379fdc08ba87f7d94a7a3d58eeefce"
SIZE_BYTES = 22_404_720

_store = InstallStore()


def root() -> Path:
    return settings.data_dir / NSFW_CLASSIFIER


def weights_path() -> Path:
    return root() / f"model-{REVISION[:12]}.safetensors"


def ready() -> bool:
    """下好了没有。判据是正式位置上有没有这个文件 —— 它只会以校验过的样子出现在那里(见 `_install`)。"""
    return weights_path().is_file()


def status() -> dict[str, Any]:
    """给界面的那几个字段:`status`(installed / missing / installing / failed)、失败时那句话、多大。"""
    fields = _store.status_fields(NSFW_CLASSIFIER, ready=ready())
    fields["size_bytes"] = SIZE_BYTES
    return fields


def start_install() -> dict[str, Any]:
    """在后台线程里下。**不阻塞请求**;已经有了就直接回状态,正在下就拒(InstallStore)。"""
    if ready():
        return status()
    _store.begin(NSFW_CLASSIFIER, "dlMsg_downloading")
    threading.Thread(target=_run_install, daemon=True, name="nsfw-classifier-install").start()
    return status()


def _run_install() -> None:
    try:
        _install()
    except Exception as exc:  # noqa: BLE001 — 失败要留在状态里给用户看,不是吞掉
        logger.warning("下载本机识别的权重失败:%s", exc)
        _store.set(NSFW_CLASSIFIER, InstallProgress(FAILED, *failure_message(exc)))
        return
    _store.clear(NSFW_CLASSIFIER)


def download_url() -> str:
    from app.ai.runtime import config

    return f"{config.get().hf_endpoint.rstrip('/')}/{REPO}/resolve/{REVISION}/model.safetensors"


def _install() -> Path:
    from app.ai.media_transfer import download_to_path

    target = weights_path()
    staging = target.with_name(f"{target.name}.download")
    try:
        download_to_path(download_url(), staging, timeout=600)
        digest = _sha256(staging)
        if digest != SHA256:
            # 不说「下载失败」—— 下载是成功的,只是下来的东西不是核对过的那一个。
            raise RuntimeSetupError("runtimeErr_checksumMismatch", digest=digest[:12])
        # 校验通过才挪到正式位置:ready 只看这个路径,半截或被换过的文件永远到不了这里。
        staging.replace(target)
    finally:
        staging.unlink(missing_ok=True)
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
