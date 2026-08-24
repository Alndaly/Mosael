"""TTS 运行配置的**数据库那一侧**。

运行时本身(engine / 解释器 / venv 路径怎么算)在 `ai/runtime/config.py` —— 那是基础设施,
不认识数据库。这里只做两件属于领域的事:把用户存的那一行读出来喂给它,以及一次性的数据迁移。

装配在 app/main.py 的启动流程里(`config.use_source(load)`)。这条注入是 `ai` 不再依赖
`domain` 的关键:反过来的话,"在这台机器上跑模型"这件纯基础设施的事会被一张表拴住。
"""

from __future__ import annotations

import logging

from app.ai.runtime.config import SINGLETON_ID, TtsRuntimeConfig, refresh
from app.core.config import settings

logger = logging.getLogger(__name__)

#: 已经不存在的下载源 → 与它**等价**的那一个。**现在是空的**:modelscope 成了真的,不该再被
#: 换成别的。「等价才迁」—— 一次不等价的迁移就是替用户改了设置,而实测机器上那正好是把一条
#: 9 MB/s 的路换成 46 KB/s 的路(见 tests/test_every_download_source_does_something)。
_LEGACY_SOURCES: dict[str, str] = {}


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


def migrate_legacy_sources() -> None:
    """把库里存着的老下载源换成等价的新值。

    不迁的话它会落到 `hf_endpoint` 的兜底(hf-mirror)上 —— 那是**另一个**端点:用户什么都
    没改,下载源却悄悄换了人,而这台机器上镜像恰恰是下不动的那个。
    """
    from app.core.db import SessionLocal
    from app.db.models import TtsConfig

    with SessionLocal() as db:
        rows = db.query(TtsConfig).filter(TtsConfig.source.in_(tuple(_LEGACY_SOURCES))).all()
        for row in rows:
            row.source = _LEGACY_SOURCES[row.source]
        if rows:
            db.commit()
    refresh()
