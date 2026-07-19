from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MIBU_", env_file=".env", extra="ignore")

    data_dir: Path = Path.home() / ".mibu-new"
    backend_host: str = "127.0.0.1"
    backend_port: int = 8800
    scheduler_enabled: bool = True
    feishu_autostart: bool = True

    # ffmpeg/ffprobe binaries. Default to PATH; override (MIBU_FFMPEG / MIBU_FFPROBE) to
    # point at a full build — Homebrew's core `ffmpeg` is slim (no libass/freetype), so
    # subtitle burn-in needs e.g. /opt/homebrew/opt/ffmpeg-full/bin/ffmpeg.
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"

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
