"""社区服务的全部配置 —— **只从环境变量来**,前缀 `COMMUNITY_`。

每一项在 deploy/community/.env.example 里有一行说明;密钥类的值(短信、对象存储、签名密钥)在仓库里
一个都不出现。

**本地开发零依赖**(`COMMUNITY_ENV=development`,缺省):数据库是 `COMMUNITY_DATA_DIR` 下的 SQLite,文件存在
同一个目录、由服务自己出,签名密钥第一次启动时生成到那个目录里,cookie 不带 Secure(本地是 http),
启动时自动跑迁移。生产环境(`production`)这些都必须显式配,缺了拒绝启动 —— 一把每次重启都换的密钥意味着
每次发版所有人被踢下线,这种事该在启动时就说,而不是上线后才发现。
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: 仓库根(开发时的缺省路径从这里算;容器里由环境变量指到镜像里的位置)。
REPO_ROOT = Path(__file__).resolve().parents[3]

API_PREFIX = "/api/community/v1"

#: 本地开发时官网开发服务器的地址(它把 /api/community/* 转到本服务的 8900 端口)。
DEV_PUBLIC_URL = "http://localhost:3100"

MiB = 1024 * 1024
GiB = 1024 * MiB


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COMMUNITY_", extra="ignore")

    # ---- 基础 ----
    env: Literal["development", "test", "production"] = "development"
    #: 站点的公开地址(没有结尾斜杠)。设备授权的验证地址、分享链接、本地存储的上传地址都用它拼。
    #: 生产必填;不配时是本地官网开发服务器的地址(它把 /api/community/* 转给本服务,上传与媒体地址因此同源)。
    public_url: str = ""
    #: 本地数据目录:缺省的 SQLite 库、本地存储、开发用签名密钥都放这里。
    data_dir: str = "./community-data"
    #: 不配就是 data_dir 下的 SQLite。生产用 `postgresql+psycopg://…`。
    database_url: str = ""
    #: 服务端的 HMAC 密钥:短信验证码的哈希、本地上传地址的签名、刷新令牌宽限期的派生都用它。至少 32 字节。
    secret_key: str = ""
    log_level: str = "INFO"
    #: `json`(生产)或 `text`(开发时读着舒服)。
    log_format: Literal["json", "text"] = "json"

    # ---- 令牌 ----
    #: Ed25519 私钥(PEM)。二选一:直接给内容,或给一个文件路径。
    jwt_private_key: str = ""
    jwt_private_key_file: str = ""
    access_token_ttl_seconds: int = 15 * 60
    refresh_idle_days: int = 30
    refresh_absolute_days: int = 90
    refresh_grace_seconds: int = 20
    #: 刷新令牌 cookie 带不带 Secure。不配:开发环境关(本地是 http),其余开。
    cookie_secure: bool | None = None
    refresh_cookie_name: str = "mosael_refresh"
    #: 刷新令牌 cookie 的 Path。**必须是刷新接口所在路径的前缀**,否则浏览器根本不带它(见 README 的偏差说明)。
    refresh_cookie_path: str = f"{API_PREFIX}/auth"

    # ---- 协议 ----
    #: 当前《用户协议》《隐私政策》的版本号。登录、注册时要带上同意的是哪一版。
    terms_version: str = "1"

    # ---- 短信 ----
    sms_sender: Literal["console", "tencent"] = "console"
    #: 开发用的固定验证码(如 000000)。**只有 COMMUNITY_ENV=development 时才接受**,别的环境配了就拒绝启动。
    dev_sms_code: str = ""
    sms_code_ttl_seconds: int = 5 * 60
    sms_max_attempts: int = 5
    sms_resend_seconds: int = 60
    sms_daily_limit_per_phone: int = 10
    sms_hourly_limit_per_ip: int = 20
    tencent_secret_id: str = ""
    tencent_secret_key: str = ""
    tencent_sms_region: str = "ap-guangzhou"
    tencent_sms_sdk_app_id: str = ""
    tencent_sms_sign_name: str = ""
    #: 验证码模板 ID。三种用途可以各配一个;没配的用这一个。
    tencent_sms_template_id: str = ""
    tencent_sms_template_id_login: str = ""
    tencent_sms_template_id_bind: str = ""
    tencent_sms_template_id_reset: str = ""
    #: 模板变量的顺序:`code` = 验证码,`minutes` = 有效分钟数。模板「验证码{1},{2}分钟内有效」就是 `code,minutes`。
    tencent_sms_template_params: str = "code,minutes"

    # ---- 验证码(腾讯云天御),可选 ----
    captcha_app_id: str = ""
    captcha_app_secret_key: str = ""

    # ---- 密码登录限速 ----
    password_account_max_failures: int = 5
    password_account_lock_seconds: int = 15 * 60
    password_ip_max_failures: int = 30
    password_ip_window_seconds: int = 15 * 60

    # ---- 通用限速(进程内,见 middleware) ----
    write_requests_per_minute: int = 120

    # ---- 存储 ----
    storage: Literal["local", "s3"] = "local"
    #: 本地存储的目录。不配就是 data_dir 下的 media/。
    storage_dir: str = ""
    #: 本地存储时文件的 URL 前缀。生产由反代直接出(`/community-media`,见 deploy/community/Caddyfile);
    #: 开发环境不配时由服务自己出,前缀是 `/api/community/media`(同源反代到服务的那一支)。
    media_url_prefix: str = ""
    #: 服务自己出本地存储的文件(开发用,免得装反代)。不配:开发环境开,其余关。
    serve_media: bool | None = None
    s3_endpoint: str = ""
    s3_region: str = ""
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    #: 公开读的 CDN / 桶地址(可选)。不配就给预签名的 GET 地址。
    s3_public_url: str = ""
    s3_addressing_style: Literal["virtual", "path"] = "virtual"
    upload_url_ttl_seconds: int = 60 * 60
    download_url_ttl_seconds: int = 60 * 60

    # ---- 限额 ----
    share_max_items: int = 300
    share_max_file_bytes: int = 200 * MiB
    share_max_total_bytes: int = 1 * GiB
    user_storage_quota_bytes: int = 5 * GiB
    plugin_max_bytes: int = 64 * MiB
    plugin_max_unpacked_bytes: int = 256 * MiB
    plugin_max_files: int = 2000
    workflow_max_bytes: int = 5 * MiB
    cover_max_bytes: int = 5 * MiB
    json_body_max_bytes: int = 16 * MiB

    # ---- 分享预览图 ----
    #: 能显示中文的字体文件(容器里装了 Noto CJK)。不配就按常见位置找,找不到退回 Pillow 自带字体(不含中文)。
    og_font_path: str = ""
    og_wordmark_path: str = str(REPO_ROOT / "website" / "public" / "brand" / "mosael-wordmark-tight.png")

    # ---- 官方条目 ----
    #: 官网静态索引所在目录(里面有 plugins/registry.json 与 workflows/)。
    official_catalog_dir: str = str(REPO_ROOT / "website" / "public")

    @field_validator("public_url")
    @classmethod
    def _strip_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @model_validator(mode="after")
    def _environment_defaults(self) -> "Settings":
        development = self.env == "development"
        data = Path(self.data_dir)
        if not self.public_url:
            self.public_url = "" if self.env == "production" else DEV_PUBLIC_URL
        if not self.database_url:
            self.database_url = f"sqlite:///{(data / 'community.db').resolve()}"
        if not self.storage_dir:
            self.storage_dir = str(data / "media")
        if self.cookie_secure is None:
            self.cookie_secure = not development
        if self.serve_media is None:
            self.serve_media = development
        if not self.media_url_prefix:
            self.media_url_prefix = "/api/community/media" if self.serve_media else "/community-media"
        if self.dev_sms_code and not development:
            raise ValueError("COMMUNITY_DEV_SMS_CODE is only allowed when COMMUNITY_ENV=development")
        if self.dev_sms_code and not (self.dev_sms_code.isdigit() and len(self.dev_sms_code) == 6):
            raise ValueError("COMMUNITY_DEV_SMS_CODE must be 6 digits")
        return self

    @property
    def development(self) -> bool:
        return self.env == "development"

    @property
    def production(self) -> bool:
        return self.env == "production"

    @property
    def captcha_enabled(self) -> bool:
        return bool(self.captcha_app_id and self.captcha_app_secret_key)

    def template_for(self, purpose: str) -> str:
        specific = {
            "login": self.tencent_sms_template_id_login,
            "bind": self.tencent_sms_template_id_bind,
            "reset": self.tencent_sms_template_id_reset,
        }.get(purpose, "")
        return specific or self.tencent_sms_template_id

    def problems(self) -> list[str]:
        """生产环境启动前必须齐的几项。缺了就说清缺的是哪个变量。"""
        missing: list[str] = []
        if not self.production:
            return missing
        if not self.public_url.startswith("https://"):
            missing.append("COMMUNITY_PUBLIC_URL(站点的 https 地址)")
        if len(self.secret_key) < 32:
            missing.append("COMMUNITY_SECRET_KEY(至少 32 个字符)")
        if not (self.jwt_private_key or self.jwt_private_key_file):
            missing.append("COMMUNITY_JWT_PRIVATE_KEY 或 COMMUNITY_JWT_PRIVATE_KEY_FILE")
        if self.sms_sender == "console":
            missing.append("COMMUNITY_SMS_SENDER=tencent(生产环境不能用 console 发送器,它把验证码写进日志)")
        if self.sms_sender == "tencent":
            for name in ("tencent_secret_id", "tencent_secret_key", "tencent_sms_sdk_app_id", "tencent_sms_sign_name"):
                if not getattr(self, name):
                    missing.append(f"COMMUNITY_{name.upper()}")
            if not self.tencent_sms_template_id and not all(
                (self.tencent_sms_template_id_login, self.tencent_sms_template_id_bind, self.tencent_sms_template_id_reset)
            ):
                missing.append("COMMUNITY_TENCENT_SMS_TEMPLATE_ID")
        if self.storage == "s3":
            for name in ("s3_bucket", "s3_access_key_id", "s3_secret_access_key"):
                if not getattr(self, name):
                    missing.append(f"COMMUNITY_{name.upper()}")
        if not self.cookie_secure:
            missing.append("COMMUNITY_COOKIE_SECURE=true(生产环境的刷新令牌 cookie 必须带 Secure)")
        return missing


def load_settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


__all__ = ["API_PREFIX", "GiB", "MiB", "REPO_ROOT", "Settings", "load_settings"]
