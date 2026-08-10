"""Runtime config for voice cloning (TTS). DB singleton (TtsConfig id='default')
overrides the OPEN_STUDIO_TTS_* env fallback so engine / interpreter / download source /
Fish Speech source+weights dirs are editable from Settings. Cached; call refresh()
after a write."""
from __future__ import annotations

import threading
from dataclasses import dataclass
import logging
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

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
# 只有 HuggingFace 系的源在这里 —— 它们的区别就是一个 base URL。
# ModelScope 不在:它不是 HF 兼容端点,走的是另一个客户端(见 audio/tts_worker),
# 所以它是"哪条路"的选择,不是"哪个 URL"的选择。曾经把它塞进这张表、指向 huggingface.co,
# 于是那个选项列在那里、选得中、却什么都不改变。
HF_ENDPOINTS = {
    "hf": "https://huggingface.co",
    "hf-mirror": "https://hf-mirror.com",
}

#: 已经不存在的下载源 → 与它**等价**的那一个。等价才迁,否则就是替用户改了设置。
#: (ModelScope 现在是真的了,所以它不在这里。)
_LEGACY_SOURCES: dict[str, str] = {}


def migrate_legacy_sources() -> None:
    """把库里存着的老下载源换成等价的新值。

    不迁的话它会落到 `hf_endpoint` 的兜底(hf-mirror)上 —— 那是**另一个**端点:用户什么都
    没改,下载源却悄悄换了人,而这台机器上镜像恰恰是下不动的那个。
    """
    from app.core.db import SessionLocal
    from app.db.models import TtsConfig

    with SessionLocal() as db:
        rows = db.query(TtsConfig).filter(TtsConfig.source.in_(tuple(_LEGACY_SOURCES))).all()
        for row in rows:
            row.source = _LEGACY_SOURCES[row.source]
        if rows:
            db.commit()
    refresh()

# App 托管的 TTS 运行环境:两个引擎(f5-tts / fish-speech)共用这一个 venv。
#
# 用户**不需要**自己准备 Python。点「下载」时后端用随 App 分发的独立解释器在这里建 venv 并
# 装引擎包,再拉模型权重。设置页那个「TTS 解释器」输入框因此降级为高级覆盖项——留空是常态。
#
# 为什么不把引擎包直接打进安装包:f5-tts / fish-speech 都要 torch + torchaudio + transformers,
# 实测 2.5–3.5 GB。预装会让安装包从 ~700MB 涨到约 4GB,而绝大多数用户根本不用声音克隆。
# 随包只带一个 ~40MB 的解释器,重的部分按需落到用户数据目录,是同样"零配置"下便宜十倍的做法。
#: 运行环境**一个引擎一份**。共用一份的代价这次差点兑现:fish 的上游 pyproject 钉着
#: torch==2.8.0 / transformers<=4.57.3,而同一个 venv 里 f5 装的是 torch 2.13 —— 照钉子装
#: 会把 f5 当场废掉。最后是把版本钉子全去掉才让两边同时跑起来,那不是解决,是赌两边的 API
#: 恰好兼容;赌注会在上游某次更新时兑现,而症状是"我只动了 A,B 怎么坏了"。
MANAGED_TTS_ROOT = settings.data_dir / "tts"

#: 分开之前那个共用的。**不留作兼容候选** —— 多路兼容本身就是负担。它由 migrate_shared_venv
#: 一次性搬走或删掉,搬完之后这个路径就不该再出现在任何判断里。
LEGACY_SHARED_VENV = MANAGED_TTS_ROOT / "venv"

# App-managed Fish Speech install: the one-click download fetches the official source
# checkout + s2-pro weights here, so real synthesis works on a fresh machine without any
# manual path config (Settings paths still override).
MANAGED_FISH_REPO = settings.data_dir / "tts" / "fish-speech-src"
MANAGED_FISH_MODEL = settings.data_dir / "tts" / "fish-speech-s2-pro"

#: F5 走 ModelScope 时权重落在这里(HF 那条路由 f5_tts 自己落进 HF 缓存)。
#: 分开放是因为两条路的目录布局本来就不一样,硬凑成一个会让"装没装"更难判。
MANAGED_F5_MODEL = settings.data_dir / "tts" / "f5-tts-weights"


def managed_venv_dir(engine_id: str) -> Path:
    """这个引擎自己的托管 venv 目录。名字里带引擎 id,出问题时一眼看得出该删哪个。"""
    safe = engine_id.replace("/", "-").replace("..", "-")
    return MANAGED_TTS_ROOT / f"venv-{safe}"


def managed_venv_python(engine_id: str) -> Path:
    """这个引擎的托管解释器路径(不保证存在)。"""
    return _venv_python(managed_venv_dir(engine_id))


def _venv_python(venv: Path) -> Path:
    return venv / ("Scripts" if _WINDOWS else "bin") / ("python.exe" if _WINDOWS else "python")


def _selected_engine() -> str:
    return get().engine


def _engines_a_venv_can_run(python: Path) -> list[str]:
    """这个解释器能跑哪些引擎。判据和运行时用的是同一份(合成真正 import 的那几行)。"""
    import logging as _logging

    from app.audio import tts_models
    from app.core.child_process import run_logged

    able: list[str] = []
    for engine in tts_models.CATALOG:
        code = tts_models._probe_code(engine.id)
        if not code:
            continue
        try:
            probe = run_logged([str(python), "-c", code], capture_output=True, timeout=180,
                               what="迁移前探测克隆引擎", level=_logging.DEBUG)
        except (OSError, RuntimeError, ValueError):
            continue
        if probe.returncode == 0:
            able.append(engine.id)
    return able


def migrate_shared_venv() -> None:
    """把分开之前那个共用 venv 搬到它实际服务的引擎名下,搬完删掉旧路径。

    为什么是迁移而不是"留着当候选":留着就意味着两条路并存,而**两条路正是这次的病根** ——
    一个环境同时被两个引擎装东西,谁先装谁定版本。多留一天,就多一天可能有人往里装。

    规则:
      - 只跑得了一个引擎 → 归它。
      - 两个都跑得了(用户机器上就是这样)→ 归当前选中的那个;另一个按需自己装一份。
      - 一个都跑不了 → 没用的数据,删掉。
      - 目标已经存在 → 不覆盖(那是用户后来装好的),旧的直接删。
    """
    import shutil

    legacy = LEGACY_SHARED_VENV
    python = _venv_python(legacy)
    if not legacy.is_dir():
        return
    able = _engines_a_venv_can_run(python) if python.is_file() else []
    if not able:
        logger.info("删掉跑不了任何引擎的旧共用 venv:%s", legacy)
        shutil.rmtree(legacy, ignore_errors=True)
        return
    target_engine = _selected_engine() if _selected_engine() in able else able[0]
    target = managed_venv_dir(target_engine)
    if target.exists():
        logger.info("%s 已经有自己的运行环境了,直接删掉旧的共用 venv", target_engine)
        shutil.rmtree(legacy, ignore_errors=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    legacy.rename(target)
    logger.info("旧的共用 venv 归给 %s:%s → %s", target_engine, legacy, target)


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
        # ModelScope 不走这条 —— 它有自己的客户端;这里给它一个能用的 HF 兜底,
        # 免得同一次下载里别的 HF 调用(比如源码检出之外的小文件)没有端点可用。
        return HF_ENDPOINTS.get(self.source, "https://huggingface.co")

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
