"""东西删了,它的共享记录也得跟着走。

`resource_shares.resource_id` 是**多态**引用 —— 同一列指向五张不同的表,所以建不了外键、
也就没有级联。必须每条删除路径显式清。

漏掉的后果不是报错:记录留在库里指向一个不存在的 id,越攒越多。真库里撞见过 ——
19 条 generation_session 共享记录里 16 条指向早就删掉的会话。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import re
from pathlib import Path

import pytest

from app.core.db import SessionLocal
from app.db.models import ResourceShare
from app.domain import sharing
from tests.util import fresh_client

APP = Path(__file__).resolve().parents[1] / "app"


def _share_rows(db, kind: str) -> list[ResourceShare]:
    from sqlalchemy import select

    return list(db.scalars(select(ResourceShare).where(ResourceShare.kind == kind)))


class Test删了就清:
    def test_生成会话(self) -> None:
        client = fresh_client()
        ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        sid = client.post("/api/generation/sessions", json={"workspace_id": ws}).json()["id"]
        client.post(f"/api/shares/generation_session/{sid}", json={"workspace_id": ws})
        with SessionLocal() as db:
            assert len(_share_rows(db, "generation_session")) == 1

        assert client.delete(f"/api/generation/sessions/{sid}").status_code == 204

        with SessionLocal() as db:
            assert _share_rows(db, "generation_session") == [], "会话没了,共享记录还指着它"

    def test_对话(self) -> None:
        client = fresh_client()
        ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        sid = client.post("/api/agent/sessions", json={"workspace_id": ws}).json()["id"]
        client.post(f"/api/shares/agent_session/{sid}", json={"workspace_id": ws})
        with SessionLocal() as db:
            assert len(_share_rows(db, "agent_session")) == 1

        assert client.delete(f"/api/agent/sessions/{sid}").status_code == 204

        with SessionLocal() as db:
            assert _share_rows(db, "agent_session") == []


class Test每一种都接上了:
    """按 SHAREABLE 那张表逐项查删除路径 —— 加第六种资源时,漏掉的那一处会在这里红。

    判据是「删除路径的源码里出现 sharing.forget(..., "<kind>", ...)」。粗,但它盯的正是
    最容易漏的那件事:新加一种资源、写了删除路由、忘了清共享。
    """

    def test_五种资源的删除路径都调了_forget(self) -> None:
        kinds = set(sharing.KINDS)
        sources = "\n".join(
            path.read_text(encoding="utf-8") for path in APP.rglob("*.py") if "__pycache__" not in str(path)
        )
        missing = [kind for kind in kinds if not re.search(rf'forget\([^)]*"{kind}"', sources)]
        assert missing == [], f"这些资源删掉之后不会清共享记录:{missing}"

    def test_这道棘轮扫得到东西(self) -> None:
        """假阴性比红更危险:哪天 SHAREABLE 改了名,上面那条会真空通过。"""
        assert len(sharing.KINDS) >= 5
