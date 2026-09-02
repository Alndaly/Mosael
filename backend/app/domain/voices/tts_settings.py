"""TTS 运行配置的**数据库那一侧**。

运行时本身(engine / 解释器 / venv 路径怎么算)在 `ai/runtime/config.py` —— 那是基础设施,
不认识数据库。这里只把用户存的那一行读出来喂给它。

装配在 app/main.py 的启动流程里(`config.use_source(load)`)。这条注入是 `ai` 不再依赖
`domain` 的关键:反过来的话,"在这台机器上跑模型"这件纯基础设施的事会被一张表拴住。
"""

from __future__ import annotations

import logging

from app.ai.runtime.config import SINGLETON_ID, TtsRuntimeConfig
from app.core.config import settings

logger = logging.getLogger(__name__)

def load() -> TtsRuntimeConfig:
    """用户存的那一份;读不到就退回环境变量默认值。"""
    from sqlalchemy.exc import SQLAlchemyError

    from app.core.db import SessionLocal
    from app.db.models import TtsConfig

    try:
        with SessionLocal() as db:
            row = db.get(TtsConfig, SINGLETON_ID)
            if row is not None:
                return TtsRuntimeConfig(
                    engine=row.engine,
                    python_path=row.python_path,
                    source=row.source,
                    pip_index=getattr(row, "pip_index", "") or "",
                    fish_repo_dir=row.fish_repo_dir or "",
                    fish_model_dir=row.fish_model_dir or "",
                )
    except SQLAlchemyError as exc:
        # 新库还没迁移出这张表时是正常的(那时本来就没有已保存的配置)。但**任何别的**
        # 数据库错误意味着用户存的引擎/下载源被无声忽略、悄悄换成默认值 —— 那是他改了设置
        # 却不生效的形状,得留下痕迹。
        logger.warning("读取 TTS 配置失败,这一次用默认值:%s: %s", type(exc).__name__, exc)
    return TtsRuntimeConfig(
        engine=settings.tts_engine,
        python_path=settings.tts_python,
        source="hf-mirror",
        pip_index="",
        fish_repo_dir="",
        fish_model_dir="",
    )
