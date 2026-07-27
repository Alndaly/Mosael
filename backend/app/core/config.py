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
    # (env → sibling mibu-video venv → this interpreter).
    asr_python: str = ""
    asr_provider: str = "auto"  # "auto" | "funasr" | "whisperx"
    asr_whisper_model: str = "small"

    # TTS / voice cloning. Heavy f5-tts/fish-speech run in a separate interpreter
    # (empty tts_python autodetects: env → sibling mibu-video venv → this one).
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

# 项目历次更名(mibu-new → mibu-video → mibu-cut → open-studio)的数据目录迁移:按新→旧
# 顺序找到第一个存在的老目录整体平移(同卷 rename,原子且瞬时,SQLite/媒体一并带走)。
# 仅对默认路径做 —— OPEN_STUDIO_DATA_DIR 显式指过别处的部署不动。必须发生在任何
# mkdir 之前:先建了空的新目录会让迁移永远跳过(踩过一次)。
if settings.data_dir == Path.home() / ".open-studio" and not settings.data_dir.exists():
    for _legacy_data_dir in (
        Path.home() / ".mibu-cut",
        Path.home() / ".mibu-video",
        Path.home() / ".mibu-new",
    ):
        if _legacy_data_dir.is_dir():
            _legacy_data_dir.rename(settings.data_dir)
            break

# 库文件更名 mibu.db → open-studio.db。同样必须早于任何 SQLAlchemy 连接:一旦连上,
# SQLite 会先把新名建成空库,迁移条件(新库不存在)就永远不成立、老数据凭空"消失"。
# -wal/-shm 是同一库的同伴文件,必须一起搬,否则残留的 WAL 会被当成另一个库的日志。
if not settings.db_path.exists():
    _legacy_db = settings.data_dir / "mibu.db"
    if _legacy_db.is_file():
        _legacy_db.rename(settings.db_path)
        for _suffix in ("-wal", "-shm"):
            _sidecar = _legacy_db.with_name(_legacy_db.name + _suffix)
            if _sidecar.is_file():
                _sidecar.rename(settings.db_path.with_name(settings.db_path.name + _suffix))
