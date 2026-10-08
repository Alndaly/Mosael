"""`migrate-provider-credentials-remember-rejected-refresh`:老库的 provider_credentials 补上 `oauth_rejected_at`(可空)。
老凭据一律「没被拒过」;再跑一次什么都不动。"""

from __future__ import annotations

from sqlalchemy import text

from app.core.db import engine
from app.db.migrations import _migrate_provider_credentials_remember_rejected_refresh as migrate
from tests.util import fresh_client


def _columns() -> set[str]:
    with engine.connect() as conn:
        return {row[1] for row in conn.execute(text("PRAGMA table_info(provider_credentials)"))}


def test_老库补上这一列_老凭据没被拒过_再跑一次不动() -> None:
    fresh_client()
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE provider_credentials DROP COLUMN oauth_rejected_at"))
    assert "oauth_rejected_at" not in _columns()
    migrate()
    assert "oauth_rejected_at" in _columns()
    migrate()
    assert "oauth_rejected_at" in _columns()
