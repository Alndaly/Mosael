from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "OPEN_STUDIO_"
_LEGACY_ENV_PREFIX = "MIBU_"  # 更名前的前缀,仅用于向后兼容(勿随全局替换一起改掉)


def _adopt_legacy_env() -> None:
    """更名前的 MIBU_* 配置继续生效:把它们镜像成 OPEN_STUDIO_*(新名已设则不覆盖)。

    真实环境变量与 .env 文件都要照顾——pydantic-settings 按前缀读 .env,单改前缀会让用户
    既有的 .env 静默失效(数据目录/端口/密钥全部回默认,像是"配置丢了")。这里在 Settings
    构造前把两处的老键都补成新键,老部署无需改任何文件。
    """
    sources: list[tuple[str, str]] = [(k, v) for k, v in os.environ.items()]
    env_file = Path(".env")
    if env_file.is_file():
        try:
            for raw in env_file.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                sources.append((key.strip(), value.strip().strip("\"'")))
        except OSError:
            pass
    for key, value in sources:
        if not key.startswith(_LEGACY_ENV_PREFIX):
            continue
        new_key = ENV_PREFIX + key[len(_LEGACY_ENV_PREFIX) :]
        os.environ.setdefault(new_key, value)


_adopt_legacy_env()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, env_file=".env", extra="ignore")

    data_dir: Path = Path.home() / ".open-studio"
    backend_host: str = "127.0.0.1"
    backend_port: int = 8800
    # 后端日志级别(OPEN_STUDIO_LOG_LEVEL=DEBUG 看更细的追溯,=WARNING 只看告警/错误)。
    # 不配的话 app.* 日志会冒泡到没挂 handler 的 root 被丢弃——见 core/logging.py。
    log_level: str = "INFO"
    scheduler_enabled: bool = True
    feishu_autostart: bool = True
    # 第三方登录(留空 = 对应按钮不出现)。Google 用「Web 应用」型客户端并把
    # http://127.0.0.1:8800/api/auth/oauth/google/callback 登记为重定向 URI;
    # Apple 要求 HTTPS 回调,适用于有公网域名的团队部署,client_secret 填按
    # Apple 规范签好的 JWT。
    google_client_id: str = ""
    google_client_secret: str = ""
    apple_client_id: str = ""
    apple_client_secret: str = ""
    oauth_redirect_base: str = ""  # 团队部署时覆盖回调基址(默认 http://<host>:<port>)

    # 逗号分隔的 job kind 列表,把这些 kind 的执行模式翻成 external:任务只入队,
    # 由外部 worker 经 /api/jobs/worker/* 认领执行(如 OPEN_STUDIO_EXTERNAL_JOB_KINDS=render
    # 让渲染由团队服务器旁的独立 worker 机器承担)。默认全部 in_process。
    external_job_kinds: str = ""

    # ffmpeg/ffprobe binaries. Default to PATH; override (OPEN_STUDIO_FFMPEG / OPEN_STUDIO_FFPROBE) to
    # point at a full build — Homebrew's core `ffmpeg` is slim (no libass/freetype), so
    # subtitle burn-in needs e.g. /opt/homebrew/opt/ffmpeg-full/bin/ffmpeg.
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"

    # Preview proxies: on video import, transcode a 720p H.264 short-GOP proxy the
    # WebCodecs compositor decodes instead of the original (export still uses the
    # original). Disable (OPEN_STUDIO_GENERATE_PROXIES=0) in tests to avoid spawning ffmpeg.
    generate_proxies: bool = True

    # 硬件加速导出:探测并优先使用 GPU/媒体引擎编码器(macOS VideoToolbox /
    # Windows NVENC·QSV·AMF),比 libx264 软件编码快数倍且几乎不占 CPU;都不可用时
    # 回落 libx264+CRF。测试里关掉(OPEN_STUDIO_HW_ENCODE=0)以保证软件编码的确定性,
    # 并避开 CI/VM 里硬件编码器缺失导致的失败。
    hw_encode: bool = True

    # 字幕/花字烧字:True=用无头 Chromium 按预览 CSS 渲染成 PNG 再叠加(逐像素对齐预览);
    # False 或找不到前端 dist/Chromium 时回落 ASS(libass)烧字。测试里关掉走 ASS 分支
    # (确定、无需起浏览器)。frontend_dist 为空时从仓库结构自动定位。
    text_rasterize: bool = True
    frontend_dist: str = ""

    # ASR (逐字稿转写). The heavy funasr/whisperx stack runs in a separate
    # interpreter so this backend stays light; empty asr_python autodetects
    # (env → this interpreter).
    asr_python: str = ""
    asr_provider: str = "auto"  # "auto" | "funasr" | "whisperx"
    asr_whisper_model: str = "small"

    # TTS / voice cloning. Heavy f5-tts/fish-speech run in a separate interpreter
    # (empty tts_python autodetects: env → this one).
    tts_python: str = ""
    tts_engine: str = "f5-tts"  # "f5-tts" | "fish-speech"

    # 知识库增强层(全部可选,未配置时基线 FTS5 始终可用)。
    # 文件转换:auto = MinerU(配了 token)→ markitdown → 纯文本
    kb_convert_engine: str = "auto"  # auto|mineru|markitdown|text
    mineru_api_base: str = "https://mineru.net"
    mineru_api_token: str = ""
    # 向量层:配置 embedding 模型即启用;Milvus URI 留空用内嵌 milvus-lite
    kb_embedding_vendor: str = ""  # provider profile vendor,如 openai-compatible / alibaba
    kb_embedding_model: str = ""
    kb_embedding_dim: int = 1024
    kb_milvus_uri: str = ""  # 空 = data_dir/kb_vectors.db;或 http://host:19530
    # 图谱层:配置 Neo4j 连接即启用(入库抽实体,检索做实体扩展)
    neo4j_uri: str = ""
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    @property
    def kb_milvus_path(self) -> str:
        return self.kb_milvus_uri or str(self.data_dir / "kb_vectors.db")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "open-studio.db"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def plugins_dir(self) -> Path:
        return self.data_dir / "plugins"


settings = Settings()

_DEFAULT_DATA_DIR = Path.home() / ".open-studio"
#: 只保留 .mibu-cut —— v0.1.0 / v0.2.0 是用它发布的,现有用户的数据都在那里。
#: 更早的 .mibu-video / .mibu-new 属于本仓库之前的前身项目,从未公开发布过,已移除。
_LEGACY_DATA_DIRS = (Path.home() / ".mibu-cut",)
_DB_NAMES = ("open-studio.db", "mibu.db")


def _db_has_rows(path: Path) -> bool:
    """这个 SQLite 文件里有没有真实的用户数据(以 workspaces 表有行为准)。

    判「有没有数据」而不是判「文件在不在」:一个已建好表结构、但一行没有的空库也有几百 KB,
    靠体积区分不了。只读打开,任何异常(文件不是库、缺表、被占用)都当作"没有数据"。
    """
    if not path.is_file():
        return False
    try:
        import sqlite3

        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = connection.execute("SELECT COUNT(*) FROM workspaces").fetchone()
            return bool(row and row[0])
        finally:
            connection.close()
    except Exception:
        return False


def _dir_has_user_data(directory: Path) -> bool:
    return any(_db_has_rows(directory / name) for name in _DB_NAMES)


def _migrate_data_dir() -> None:
    """数据目录更名迁移:.mibu-cut(v0.1.0 / v0.2.0 的发布路径)→ .open-studio。

    只在默认路径上做 —— OPEN_STUDIO_DATA_DIR 显式指过别处的部署不动。

    判据是**新目录里有没有用户数据**,而不是"新目录存不存在"。后者踩过一次:任何一个进程
    (哪怕只是导入了 app.core.db,它在模块层就 mkdir)都会先把空的新目录建出来,此后迁移
    条件永远不成立 —— 老数据原地不动、应用却开在空库上,用户看到的是"所有项目都没了"。
    新目录已被空壳占位时,把空壳挪到 .stale 备份名下再平移老目录(不删任何东西)。
    """
    if settings.data_dir != _DEFAULT_DATA_DIR or _dir_has_user_data(_DEFAULT_DATA_DIR):
        return
    if not _DEFAULT_DATA_DIR.exists():
        # 快路径:新目录还没建 → 第一个存在的老目录整体平移(同卷 rename,原子且瞬时)。
        legacy = next((d for d in _LEGACY_DATA_DIRS if d.is_dir()), None)
        if legacy is not None:
            legacy.rename(_DEFAULT_DATA_DIR)
        return
    # 新目录已被空壳占位:只有当某个老目录确有用户数据时才值得动它(空目录之间来回搬没意义)。
    legacy = next((d for d in _LEGACY_DATA_DIRS if d.is_dir() and _dir_has_user_data(d)), None)
    if legacy is None:
        return
    stale = _DEFAULT_DATA_DIR.with_name(_DEFAULT_DATA_DIR.name + ".stale")
    index = 1
    while stale.exists():
        index += 1
        stale = _DEFAULT_DATA_DIR.with_name(f"{_DEFAULT_DATA_DIR.name}.stale{index}")
    _DEFAULT_DATA_DIR.rename(stale)  # 不删任何东西,只是让开
    legacy.rename(_DEFAULT_DATA_DIR)


def _migrate_db_filename() -> None:
    """库文件更名 mibu.db → open-studio.db。

    必须早于任何 SQLAlchemy 连接:一旦连上,SQLite 会先把新名建成空库。同样以"有没有数据"
    为判据 —— 只看文件在不在的话,那个空库会让真数据永远搬不过来。
    -wal/-shm 是同一库的同伴文件,必须一起搬,否则残留的 WAL 会被当成另一个库的日志。
    """
    # 判据不对称是有意的:同一个数据目录里存在 mibu.db,本身就说明"这个装机用的是旧库名",
    # 即便它是空的也该采纳(那就是这个装机的库)。只需守住一点:新库已有数据时绝不覆盖。
    legacy_db = settings.data_dir / "mibu.db"
    if not legacy_db.is_file() or _db_has_rows(settings.db_path):
        return
    if settings.db_path.exists():  # 空壳占位 → 让开
        settings.db_path.rename(settings.db_path.with_name(settings.db_path.name + ".stale"))
    legacy_db.rename(settings.db_path)
    for _suffix in ("-wal", "-shm"):
        sidecar = legacy_db.with_name(legacy_db.name + _suffix)
        if sidecar.is_file():
            sidecar.replace(settings.db_path.with_name(settings.db_path.name + _suffix))


_migrate_data_dir()
_migrate_db_filename()
