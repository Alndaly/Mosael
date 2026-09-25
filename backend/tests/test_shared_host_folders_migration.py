"""老库的 deployment_config 补上 shared_host_folders:空列表,一个文件夹都没共享。"""

from __future__ import annotations

import json

from sqlalchemy import inspect, text

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_shared_host_folders
from app.domain import deployment
from tests.util import fresh_client


def test_old_deployment_config_gets_an_empty_shared_folder_list() -> None:
    fresh_client()
    with SessionLocal() as db:
        deployment.open_registration(db)  # 确保那一行在
        db.commit()
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE deployment_config DROP COLUMN shared_host_folders"))
    engine.dispose()
    assert "shared_host_folders" not in {c["name"] for c in inspect(engine).get_columns("deployment_config")}

    _migrate_shared_host_folders()

    with engine.begin() as conn:
        rows = conn.execute(text("SELECT shared_host_folders FROM deployment_config")).scalars().all()
    assert rows and all(json.loads(value) == [] for value in rows)

    # 再跑一次什么都不做。
    _migrate_shared_host_folders()
    assert "shared_host_folders" in {c["name"] for c in inspect(engine).get_columns("deployment_config")}
