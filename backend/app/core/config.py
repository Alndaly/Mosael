from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MIBU_", env_file=".env", extra="ignore")

    data_dir: Path = Path.home() / ".mibu-video"
    backend_host: str = "127.0.0.1"
    backend_port: int = 8800
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
    # 由外部 worker 经 /api/jobs/worker/* 认领执行(如 MIBU_EXTERNAL_JOB_KINDS=render
    # 让渲染由团队服务器旁的独立 worker 机器承担)。默认全部 in_process。
    external_job_kinds: str = ""

    # ffmpeg/ffprobe binaries. Default to PATH; override (MIBU_FFMPEG / MIBU_FFPROBE) to
    # point at a full build — Homebrew's core `ffmpeg` is slim (no libass/freetype), so
    # subtitle burn-in needs e.g. /opt/homebrew/opt/ffmpeg-full/bin/ffmpeg.
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"

    # Preview proxies: on video import, transcode a 720p H.264 short-GOP proxy the
    # WebCodecs compositor decodes instead of the original (export still uses the
    # original). Disable (MIBU_GENERATE_PROXIES=0) in tests to avoid spawning ffmpeg.
    generate_proxies: bool = True

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
        return self.data_dir / "mibu.db"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def plugins_dir(self) -> Path:
        return self.data_dir / "plugins"

    @property
    def skills_dir(self) -> Path:
        return self.data_dir / "skills"


settings = Settings()

# 项目更名(mibu-new → mibu-video)的数据目录迁移:老目录还在、新目录未建时整体
# 平移(同卷 rename,原子且瞬时,SQLite/媒体一并带走)。仅对默认路径做——
# MIBU_DATA_DIR 显式指过别处的部署不动。
_legacy_data_dir = Path.home() / ".mibu-new"
if (
    settings.data_dir == Path.home() / ".mibu-video"
    and _legacy_data_dir.is_dir()
    and not settings.data_dir.exists()
):
    _legacy_data_dir.rename(settings.data_dir)
