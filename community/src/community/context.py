"""一个进程里的「服务上下文」:配置、数据库、签名密钥、存储、短信发送器。挂在 `app.state.ctx` 上。

测试直接构造它,换上假的短信发送器和临时目录里的存储 —— 不靠猴子补丁改模块全局。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from community.config import Settings
from community.db import make_engine, make_sessionmaker
from community.sms import CaptchaVerifier, SmsSender, make_captcha, make_sender
from community.storage import Storage, make_storage
from community.tokens import KeyRing


@dataclass
class Context:
    settings: Settings
    engine: Engine
    sessions: sessionmaker[Session]
    keys: KeyRing
    storage: Storage
    sms: SmsSender
    captcha: CaptchaVerifier | None = None
    extras: dict = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        settings: Settings,
        *,
        sms: SmsSender | None = None,
        captcha: CaptchaVerifier | None = None,
        storage: Storage | None = None,
        engine: Engine | None = None,
    ) -> "Context":
        engine = engine or make_engine(settings.database_url)
        return cls(
            settings=settings,
            engine=engine,
            sessions=make_sessionmaker(engine),
            keys=KeyRing.from_settings(settings),
            storage=storage or make_storage(settings),
            sms=sms or make_sender(settings),
            captcha=captcha if captcha is not None else make_captcha(settings),
        )


__all__ = ["Context"]
