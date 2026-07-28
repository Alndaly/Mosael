"""Runtime config for voice cloning (TTS). DB singleton (TtsConfig id='default')
overrides the OPEN_STUDIO_TTS_* env fallback so engine / interpreter / download source /
Fish Speech source+weights dirs are editable from Settings. Cached; call refresh()
after a write."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings

_WINDOWS = __import__("sys").platform == "win32"

SINGLETON_ID = "default"

#: pip 索引预设。装引擎依赖要拉 2.5–3.5GB,国内直连 PyPI 常常慢到不可用,所以给常见镜像。
#: 空 = 官方 PyPI;不在表里的值当作用户自填的 index URL 直接用。
PIP_INDEXES = {
    "pypi": "",
    "tsinghua": "https://pypi.tuna.tsinghua.edu.cn/simple",
    "aliyun": "https://mirrors.aliyun.com/pypi/simple/",
    "tencent": "https://mirrors.cloud.tencent.com/pypi/simple",
}

# Model-download source → the HF endpoint the worker/download subprocess should use.
HF_ENDPOINTS = {
    "hf": "https://huggingface.co",
    "hf-mirror": "https://hf-mirror.com",
    "modelscope": "https://huggingface.co",  # f5-tts pulls from HF; modelscope is a fish path
}

# App 托管的 TTS 运行环境:两个引擎(f5-tts / fish-speech)共用这一个 venv。
#
# 用户**不需要**自己准备 Python。点「下载」时后端用随 App 分发的独立解释器在这里建 venv 并
# 装引擎包,再拉模型权重。设置页那个「TTS 解释器」输入框因此降级为高级覆盖项——留空是常态。
#
# 为什么不把引擎包直接打进安装包:f5-tts / fish-speech 都要 torch + torchaudio + transformers,
# 实测 2.5–3.5 GB。预装会让安装包从 ~700MB 涨到约 4GB,而绝大多数用户根本不用声音克隆。
# 随包只带一个 ~40MB 的解释器,重的部分按需落到用户数据目录,是同样"零配置"下便宜十倍的做法。
MANAGED_TTS_VENV = settings.data_dir / "tts" / "venv"

# App-managed Fish Speech install: the one-click download fetches the official source
# checkout + s2-pro weights here, so real synthesis works on a fresh machine without any
# manual path config (Settings paths still override).
MANAGED_FISH_REPO = settings.data_dir / "tts" / "fish-speech-src"
MANAGED_FISH_MODEL = settings.data_dir / "tts" / "fish-speech-s2-pro"


def managed_venv_python() -> Path:
    """托管 venv 里的解释器路径(不保证存在)。"""
    return MANAGED_TTS_VENV / ("Scripts" if _WINDOWS else "bin") / ("python.exe" if _WINDOWS else "python")


def base_python() -> str:
    """用来**创建**托管 venv 的解释器。找不到可用的返回空串。

    打包版的后端是 PyInstaller 冻结二进制,`sys.executable` 指向它自己,建不了 venv——所以壳
    会把随包分发的独立解释器路径经 OPEN_STUDIO_TTS_BASE_PYTHON 注入进来。开发时退回本后端的
    venv 解释器(它是真 Python,建得了 venv);都没有再退到系统 python3。
    """
    import os
    import shutil
    import sys

    injected = os.environ.get("OPEN_STUDIO_TTS_BASE_PYTHON", "").strip()
    if injected and Path(injected).is_file():
        return injected
    if not getattr(sys, "frozen", False) and Path(sys.executable).is_file():
        return sys.executable
    found = shutil.which("python3") or shutil.which("python")
    return found or ""
# Marker files that prove each managed dir is a real checkout / real weights (not a
# half-cloned or empty dir): a module the worker actually imports, and the codec weights.
# (fish_speech is an implicit-namespace package — no root __init__.py — so anchor deeper.)
FISH_REPO_MARKER = "fish_speech/utils/schema.py"
FISH_MODEL_MARKER = "codec.pth"


def _resolve(configured: str, defaults: tuple[Path, ...], *, marker: str | None = None) -> str:
    """Configured path wins; else the first default that exists (and, when `marker` is
    given, actually contains that file). Empty string if nothing resolves."""
    if configured.strip():
        return str(Path(configured).expanduser())
    for default in defaults:
        if default.is_dir() and (marker is None or (default / marker).is_file()):
            return str(default)
    return ""


@dataclass(frozen=True)
class TtsRuntimeConfig:
    engine: str
    python_path: str
    source: str
    fish_repo_dir: str
    fish_model_dir: str
    #: 装引擎依赖时用的 pip 索引(预设 key 或自定义 URL)。带默认值放最后:它是可选设置,
    #: 不该逼所有构造点都改签名。
    pip_index: str = ""

    @property
    def pip_index_url(self) -> str:
        """要传给 pip 的 --index-url。空串表示用官方 PyPI(即不传这个参数)。"""
        key = (self.pip_index or "").strip()
        if not key:
            return ""
        if key in PIP_INDEXES:
            return PIP_INDEXES[key]
        # 不是预设 key → 当成用户自填的 index URL。只接受 http(s),避免把任意字符串塞进 argv。
        return key if key.startswith(("http://", "https://")) else ""

    @property
    def hf_endpoint(self) -> str:
        return HF_ENDPOINTS.get(self.source, "https://hf-mirror.com")

    @property
    def resolved_fish_repo(self) -> str:
        return _resolve(
            self.fish_repo_dir, (MANAGED_FISH_REPO,), marker=FISH_REPO_MARKER
        )

    @property
    def resolved_fish_model(self) -> str:
        return _resolve(
            self.fish_model_dir, (MANAGED_FISH_MODEL,), marker=FISH_MODEL_MARKER
        )


_lock = threading.Lock()
_cached: TtsRuntimeConfig | None = None


def _load() -> TtsRuntimeConfig:
    from sqlalchemy.exc import SQLAlchemyError

    from app.core.db import SessionLocal
    from app.db.models import TtsConfig

    try:
        with SessionLocal() as db:
            row = db.get(TtsConfig, SINGLETON_ID)
            if row is not None:
                return TtsRuntimeConfig(
                    engine=row.engine,
                    python_path=row.python_path,
                    source=row.source,
                    pip_index=getattr(row, "pip_index", "") or "",
                    fish_repo_dir=row.fish_repo_dir or "",
                    fish_model_dir=row.fish_model_dir or "",
                )
    except SQLAlchemyError:
        # Table not migrated yet (fresh DB) — the singleton is optional; env defaults apply.
        pass
    return TtsRuntimeConfig(
        engine=settings.tts_engine,
        python_path=settings.tts_python,
        source="hf-mirror",
        pip_index="",
        fish_repo_dir="",
        fish_model_dir="",
    )


def get() -> TtsRuntimeConfig:
    global _cached
    with _lock:
        if _cached is None:
            _cached = _load()
        return _cached


def refresh() -> None:
    global _cached
    with _lock:
        _cached = None
