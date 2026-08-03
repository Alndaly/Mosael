from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "OPEN_STUDIO_"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, env_file=".env", extra="ignore")

    data_dir: Path = Path.home() / ".open-studio"
    backend_host: str = "127.0.0.1"

    #: 允不允许自助注册。**默认开放。**
    #:
    #: 它一度默认关(ADR 0008 第 0 步),理由是那条跑出来过的链的第一环:注册 → 自己建工作区
    #: → 满足当时那道自助的实例管理员判据 → 改实例配置 / 在服务端跑任意 Python。**那条链的
    #: 中段和末段后来各自断了**:第 1 步把部署配置收到 `is_deployment_admin`(自己建工作区不再
    #: 带来任何部署权限),第 5 步把代码执行搬进隔离环境。关注册当时是止血,伤口已经缝上了。
    #:
    #: 现在陌生人注册拿到的是**他自己的**工作区:看不到别人的东西(D3)、用不了别人的钥匙(D4)、
    #: 跑不了伤到别人的代码(D2)。想关的部署把它设成 0 —— 那是部署的选择,不是产品的默认姿态。
    open_registration: bool = True

    backend_port: int = 8800
    # 后端日志级别(OPEN_STUDIO_LOG_LEVEL=DEBUG 看更细的追溯,=WARNING 只看告警/错误)。
    # 不配的话 app.* 日志会冒泡到没挂 handler 的 root 被丢弃——见 core/logging.py。
    log_level: str = "INFO"
    scheduler_enabled: bool = True
    # 由桌面端(Electron)拉起时置 1。用来门控「按本机绝对路径导入素材」这类
    # 只在「后端与用户文件在同一台机器上」才成立的能力 —— 团队服务器部署不会有这个标记,
    # 于是客户端也就无法让服务器去读它自己的文件系统。
    local_desktop: bool = False
    # 应用版本。**唯一真相在根 package.json**,由 Electron 壳在拉起后端时传进来
    # (electron/main.cjs)。后端自己维护第二个版本号必然漂移——智能体的能力面板此前
    # 就一直显示 pyproject 里那个从未跟着发版更新过的 0.1.0。
    # 纯 `uvicorn` 起的开发后端拿不到,那时 app_version() 会回落去读仓库里的 package.json。
    app_version: str = ""
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
_DB_NAMES = ("open-studio.db",)


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




def app_version() -> str:
    """当前应用版本。

    壳传进来的优先(那是发版时打进包里的那个数);纯 `uvicorn` 起的开发后端拿不到,
    回落去读仓库根的 package.json —— 开发时看到 "0.7.0-dev" 比看到一个假的定值有用。
    两个都没有就说 "dev",**不编一个版本号出来**。
    """
    if settings.app_version:
        return settings.app_version
    for parent in Path(__file__).resolve().parents:
        manifest = parent / "package.json"
        if manifest.is_file():
            try:
                import json

                version = json.loads(manifest.read_text(encoding="utf-8")).get("version")
            except (OSError, ValueError):
                break
            if version:
                return f"{version}-dev"
            break
    return "dev"


#: 凭据周期。放在这里(配置这个叶子模块)而不是 core/security:启动迁移要按它回填老行,
#: 而 security 会用到 db.models —— 让 db 去 import security 就成了 db ⇄ security ⇄ models
#: 的环(分层棘轮会红)。策略只有一份,两边都从这里取。
#:
#: 登录:桌面应用没人主动登出,靠**活跃续期**保持有效,这个数字实际约束的是"多久不用就要重登"。
LOGIN_SESSION_TTL = timedelta(days=30)
#: 服务令牌:一次有界操作的凭据(对话轮次上限 600s、设备码登录几分钟、OAuth 刷新一瞬间)。
#: 半小时足够宽,又把"忘了撤销"的代价从永久压到半小时。
SERVICE_SESSION_TTL = timedelta(minutes=30)
