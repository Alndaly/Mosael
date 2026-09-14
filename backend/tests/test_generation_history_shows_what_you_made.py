"""从画板、工作流、智能体、定时任务生成的东西,生成历史里得看得见。

生成会话是**某人的私人线程**:列表按 `owner_user_id == 我 或 被共享进这个工作区` 过滤。
而没点名会话时现开的那一条此前**不设主人** —— owner_user_id 是 NULL,谁都匹配不上,
于是那条记录连创建它的人自己都看不见。

图不会丢(它进了素材库),丢的是带着提示词、参数和花费的那条记录:回不到历史里,也不进成本核算。

界面那条路一直传 session_id,所以踩不到;踩得到的是另外四个入口,它们都传 session_id=None:
`routes/boards.py`(从画板生成)、`workers/scheduler.py`(定时任务)、
`workflows/executors/subjobs.py`(ai_generate 节点)、`agent/confirmations.py`(智能体生成)。
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import GenerationSession, User
from app.domain import sharing
from app.domain.generation.operations import _resolve_session
from tests.util import fresh_client


def _me(db):
    """列表过滤要一个真 User —— 断言的是「这个人看得见它」,不是「某个字段被填上了」。"""
    user = db.scalars(select(User)).first()
    assert user is not None
    return user


def _visible_to(db, user, workspace_id: str) -> set[str]:
    """route 里那一条过滤,原样搬过来:看得见的生成会话有哪些。"""
    return set(
        db.scalars(
            select(GenerationSession.id).where(
                sharing.visible_filter("generation_session", user, workspace_id)
            )
        )
    )


def _session(db, workspace_id: str, owner: str | None):
    return _resolve_session(
        db, workspace_id=workspace_id, session_id=None, prompt="一只红苹果", created_by=owner
    )


def test_没点名会话时_现开的那条自己看得见() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    with SessionLocal() as db:
        me = _me(db)
        session = _session(db, workspace["id"], me.id)
        db.flush()
        assert session.id in _visible_to(db, me, workspace["id"]), "无主的会话谁都看不见,包括创建它的人"
        db.rollback()


def test_不设归属的话它就成了孤儿() -> None:
    """这一条钉的是**为什么**要设归属 —— 不设的话过滤器一定漏掉它。"""
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    with SessionLocal() as db:
        me = _me(db)
        orphan = GenerationSession(workspace_id=workspace["id"], title="无主", owner_user_id=None)
        db.add(orphan)
        db.flush()
        assert orphan.id not in _visible_to(db, me, workspace["id"])
        db.rollback()


def test_标题从提示词来() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    with SessionLocal() as db:
        assert _session(db, workspace["id"], _me(db).id).title == "一只红苹果"
        db.rollback()


def test_点名了就用那一条_不新建() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    with SessionLocal() as db:
        me = _me(db)
        existing = GenerationSession(workspace_id=workspace["id"], title="新生成", owner_user_id=me.id)
        db.add(existing)
        db.flush()
        before = len(list(db.scalars(select(GenerationSession.id))))
        got = _resolve_session(
            db, workspace_id=workspace["id"], session_id=existing.id, prompt="一只红苹果",
            created_by="另一个人",
        )
        assert got.id == existing.id
        # 「新生成」这个占位标题会被第一条提示词顶掉,但归属不动 —— 别人在我的线程里生成
        # 不该把它变成别人的。
        assert got.title == "一只红苹果"
        assert got.owner_user_id == me.id
        assert len(list(db.scalars(select(GenerationSession.id)))) == before
        db.rollback()
