"""migrate-generation-result-deleted-mark:老的 generation_jobs 表补上 result_deleted_at。

`create_all` 只建缺失的表、不给已存在的表加列 —— 没有这一步,升级的机器上后端起不来
(no such column)。钉住:这列在,且这步幂等。
"""

from __future__ import annotations

from sqlalchemy import inspect

from app.core.db import engine
from app.db.migrations import _migrate_generation_result_deleted_mark


def _columns() -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns("generation_jobs")}


def test_老表补上产出被删那一列_再跑一次什么都不做() -> None:
    _migrate_generation_result_deleted_mark()
    assert "result_deleted_at" in _columns()
    _migrate_generation_result_deleted_mark()
