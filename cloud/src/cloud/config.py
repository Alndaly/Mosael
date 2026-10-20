"""MosaelCloud 的部署配置 —— 只从 `CLOUD_*` 环境变量读,测试可以直接构造。

`CloudConfig` 是**显式**的:生产入口 `cloud.main:app` 从环境变量建一份,测试建自己的那一份。
这样同一个进程里可以起好几个互不相干的 Cloud 实例(隔离测试用),不必去改全局单例。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

APP_ROOT = Path(__file__).resolve().parent

API_PREFIX = "/api/cloud/v1"

#: `CLOUD_SMTP_TLS` 只有这三种取值。`starttls` 是 587 提交通道,`ssl` 是 465,`none` 给本地 Mailpit。
SMTP_TLS_MODES = frozenset({"starttls", "ssl", "none"})

#: 第三方登录只支持这两家。名字同时出现在表、路径和配置里,不要在不同地方各写一份字符串。
OAUTH_PROVIDERS = ("github", "google")


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _host_and_port(value: str, default_port: int) -> tuple[str, int]:
    """`localhost:1025` 这种写法拆成 host + port;没有端口就用缺省值。

    只有"最后一个冒号后面全是数字"才当端口 —— `smtp.example.com` 不会被误拆。
    IPv6 字面量这一期不支持,写主机名或 IPv4。
    """
    host, separator, port = value.rpartition(":")
    if separator and port.isdigit():
        return host, int(port)
    return value, default_port


@dataclass(frozen=True)
class CloudConfig:
    #: 数据目录。默认库是它下面的 `cloud.db`。
    data_dir: Path
    #: 官网的公开地址(没有结尾斜杠)。同源校验和 OAuth 回调都以它为原点。
    public_url: str = "http://localhost:3000"
    #: 显式数据库地址;空 = 数据目录里的 SQLite。生产写 `postgresql+psycopg://…`。
    database_url: str = ""
    #: 会话 cookie。生产必须 Secure;本地 http 开发显式关掉。
    cookie_secure: bool = True
    cookie_name: str = "mosael_cloud_session"
    cookie_path: str = API_PREFIX
    #: 登录会话活多久。没有滑动续期:到期就要重新登录,撤销靠删行。
    session_ttl_days: int = 30
    #: 密码长度下限。上限只是挡住拿超长串做 DoS 的请求,不是强度策略。
    password_min_length: int = 8
    password_max_length: int = 128
    #: 发信(SMTP)。**没配 `smtp_host` 时发码接口明确报错**,不假装发出。
    #: `CLOUD_SMTP_HOST` 可以写成 `host:port`(开发时就是 `localhost:1025`,即 Mailpit)。
    smtp_host: str = ""
    smtp_port: int = 587
    #: `starttls`(587)/ `ssl`(465)/ `none`(本地 Mailpit)。没显式配时:有用户名按 starttls,
    #: 没有用户名按 none —— 后者让 `CLOUD_SMTP_HOST=localhost:1025` 一个变量就能连 Mailpit。
    smtp_tls: str = "starttls"
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@mosael.com"
    #: 第三方登录的 OAuth 应用凭据。**空 = 这个入口没启用**,接口会明确报错而不是假装能用。
    #: client id / secret 只从环境变量读,代码里不出现任何真实值。
    github_client_id: str = ""
    github_client_secret: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    #: 一次 OAuth 登录的 state / nonce 活多久。10 分钟够用户看完第三方的授权页再回来。
    oauth_state_ttl_seconds: int = 600
    #: 把 state 绑到发起请求的浏览器的那枚短命 cookie 的名字。
    oauth_cookie_name: str = "mosael_cloud_oauth_state"
    #: 从 `public_url` 推出来的同源校验名单(允许的 Origin)。
    allowed_origins: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        public = self.public_url.rstrip("/")
        object.__setattr__(self, "public_url", public)
        if not self.allowed_origins:
            split = urlsplit(public)
            if split.scheme and split.netloc:
                object.__setattr__(self, "allowed_origins", frozenset({f"{split.scheme}://{split.netloc}"}))
        if self.session_ttl_days <= 0:
            raise ValueError("session_ttl_days must be positive")
        if self.smtp_tls not in SMTP_TLS_MODES:
            raise ValueError(f"smtp_tls must be one of {sorted(SMTP_TLS_MODES)}")
        if not 0 < self.smtp_port < 65536:
            raise ValueError("smtp_port must be between 1 and 65535")
        if self.oauth_state_ttl_seconds <= 0:
            raise ValueError("oauth_state_ttl_seconds must be positive")

    @property
    def resolved_database_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir / 'cloud.db'}"

    @property
    def smtp_configured(self) -> bool:
        """有没有地方可以发信。**空 host = 没有**,调用方必须报错而不是吞掉。"""
        return bool(self.smtp_host.strip() and self.smtp_from.strip())

    def oauth_credentials(self, provider: str) -> tuple[str, str] | None:
        """某个 provider 的 `(client_id, client_secret)`;任缺一项就当作没配置。"""
        values = {
            "github": (self.github_client_id, self.github_client_secret),
            "google": (self.google_client_id, self.google_client_secret),
        }.get(provider)
        if values is None or not values[0].strip() or not values[1].strip():
            return None
        return values

    def oauth_configured(self, provider: str) -> bool:
        return self.oauth_credentials(provider) is not None

    def oauth_redirect_uri(self, provider: str) -> str:
        """回调地址**只由 `public_url` 推出**,不看请求的 Host / X-Forwarded-*。

        这样它天然与官网同源,也避免代理头被伪造时把授权码送去别处。
        """
        return f"{self.public_url}{API_PREFIX}/oauth/{provider}/callback"

    @property
    def development(self) -> bool:
        return not self.cookie_secure

    @classmethod
    def from_env(cls) -> "CloudConfig":
        data_dir = Path(os.environ.get("CLOUD_DATA_DIR", "./cloud-data")).expanduser().resolve()
        smtp_host, smtp_port = _host_and_port(
            os.environ.get("CLOUD_SMTP_HOST", "").strip(),
            int(os.environ.get("CLOUD_SMTP_PORT", "587")),
        )
        smtp_username = os.environ.get("CLOUD_SMTP_USERNAME", "").strip()
        smtp_tls = (
            os.environ.get("CLOUD_SMTP_TLS", "").strip().lower()
            or ("starttls" if smtp_username else "none")
        )
        return cls(
            data_dir=data_dir,
            public_url=os.environ.get("CLOUD_PUBLIC_URL", "http://localhost:3000").strip(),
            database_url=os.environ.get("CLOUD_DATABASE_URL", "").strip(),
            cookie_secure=_flag("CLOUD_COOKIE_SECURE", True),
            cookie_name=os.environ.get("CLOUD_COOKIE_NAME", "mosael_cloud_session").strip() or "mosael_cloud_session",
            cookie_path=os.environ.get("CLOUD_COOKIE_PATH", API_PREFIX).strip() or API_PREFIX,
            session_ttl_days=int(os.environ.get("CLOUD_SESSION_TTL_DAYS", "30")),
            password_min_length=int(os.environ.get("CLOUD_PASSWORD_MIN_LENGTH", "8")),
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_tls=smtp_tls,
            smtp_username=smtp_username,
            smtp_password=os.environ.get("CLOUD_SMTP_PASSWORD", ""),
            smtp_from=os.environ.get("CLOUD_SMTP_FROM", "no-reply@mosael.com").strip() or "no-reply@mosael.com",
            github_client_id=os.environ.get("CLOUD_GITHUB_CLIENT_ID", "").strip(),
            github_client_secret=os.environ.get("CLOUD_GITHUB_CLIENT_SECRET", "").strip(),
            google_client_id=os.environ.get("CLOUD_GOOGLE_CLIENT_ID", "").strip(),
            google_client_secret=os.environ.get("CLOUD_GOOGLE_CLIENT_SECRET", "").strip(),
            oauth_state_ttl_seconds=int(os.environ.get("CLOUD_OAUTH_STATE_TTL_SECONDS", "600")),
        )
