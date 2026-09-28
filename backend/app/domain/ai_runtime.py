"""AI 出站调用的运行设置:供应商瞬断 / 限流时最多重试几次(单例 AiRuntimeConfig)。

行只在这里建(归属见 ownership.py)。次数本身是进程级状态,住在 `core/http_retry` —— 调用点散在
十几个适配器里,不少拿不到 db 会话;这里负责把存着的那份推过去:启动时一次,改完一次。与出站
代理(`domain/network`)同一套做法。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.http_retry import DEFAULT_MAX_RETRIES, clamp_max_retries, set_max_retries
from app.db.models import AiRuntimeConfig

SINGLETON_ID = "default"


def configured_max_retries(db: Session) -> int:
    """用户设置的最大重试次数;没设过就是缺省值。"""
    row = db.get(AiRuntimeConfig, SINGLETON_ID)
    return clamp_max_retries(row.max_retries if row is not None else DEFAULT_MAX_RETRIES)


def save_max_retries(db: Session, value: int) -> int:
    """存下来并立即对本进程生效,交回生效的那个值。"""
    row = db.get(AiRuntimeConfig, SINGLETON_ID)
    if row is None:
        row = AiRuntimeConfig(id=SINGLETON_ID)
        db.add(row)
    row.max_retries = value
    db.commit()
    apply_to_process(db)
    return configured_max_retries(db)


def apply_to_process(db: Session) -> None:
    set_max_retries(configured_max_retries(db))
