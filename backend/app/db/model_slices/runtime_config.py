"""这台机器上的配置:本机 AI 运行时、部署、网络出口、TTS。

都是**单例行**(每张表只有一行),所以它们不带 workspace_id —— 它们描述的是部署,不是工作区。
"""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base
from app.db.model_base import now

class AiRuntimeConfig(Base):
    """Singleton (id='default') 运行时 AI 设置。目前只含「供应商瞬断时的最大重试次数」
    (0..10,缺省 3),用户可在设置页调整——见 workflows/executors/ai.py。"""

    __tablename__ = "ai_runtime_config"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default="default")
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class DeploymentConfig(Base):
    """Singleton (id='default') 部署级开关 —— **这台后端**怎么对外。

    为什么进库而不是留在环境变量里:改它是部署管理员在界面上就该能做的决定(和发邀请码、
    授予管理员同一类),而环境变量意味着要能碰到部署机、要重启进程。

    **库是唯一真相**;环境变量只在首次迁移时播一次种(见 core/db._migrate_deployment_config),
    之后不再读 —— 不做"两边都读"的兼容,那样一个部署会同时有两个答案,而谁赢取决于代码里的顺序。
    """

    __tablename__ = "deployment_config"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default="default")
    #: 陌生人能不能自己建账号。关掉之后要邀请码(见 routes/auth.register)。
    open_registration: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    #: 插件市场的索引地址。空 = 用内置默认(见 domain/plugins/registry)。
    #:
    #: 是部署级设置而不是每人一份:装插件是把代码放进**这台机器**,而这台机器上装了什么
    #: 对所有用户是同一件事。公司内网可以指向自己那一份。
    plugin_registry_url: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class NetworkConfig(Base):
    """Singleton (id='default') 出站网络代理。

    空 proxy_url = 直连。一处配置,后端 httpx / sidecar / 内嵌浏览器都遵守 —— 见
    app/domain/network.py(里面也说明了为什么回环永远不走代理)。
    """

    __tablename__ = "network_config"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default="default")
    #: 形如 http://127.0.0.1:7890 或 socks5://127.0.0.1:1080;空串 = 直连。
    proxy_url: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    #: 额外绕过代理的主机,逗号分隔。默认值由领域层在建行时填(模型层不该反向依赖 domain),
    #: 回环则由代码强制补上、不依赖这里填对 —— 两者都见 app/domain/network.py。
    no_proxy: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class TtsConfig(Base):
    """Singleton (id='default') runtime config for voice cloning: which engine,
    the external interpreter that has f5-tts/fish-speech installed, and the model
    download source. Overrides the MOSAEL_TTS_* env fallback so it's UI-editable."""

    __tablename__ = "tts_config"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default="default")
    engine: Mapped[str] = mapped_column(String(32), nullable=False, default="f5-tts")  # f5-tts | fish-speech
    python_path: Mapped[str] = mapped_column(String(500), nullable=False, default="")  # empty = autodetect
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="hf-mirror")  # hf | hf-mirror | modelscope
    #: 装引擎依赖(torch 等 2.5–3.5GB)时用的 pip 索引。空 = 官方 PyPI。
    #: 与 source 分开:那个管模型权重从哪拉(HuggingFace),这个管 Python 包从哪拉。
    pip_index: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Fish Speech runs from a source checkout + a local weights dir (with codec.pth);
    # empty = fall back to the app-managed install. See domain/tts_config.py.
    fish_repo_dir: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    fish_model_dir: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)
