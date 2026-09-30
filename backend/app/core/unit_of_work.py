"""一次用例一个事务:**入口层**开、提交、回滚;领域函数只改对象,不提交。

此前提交散在各处:领域层三百多处 `db.commit()`、路由层又八十多处。一个领域函数中途提交之后
被别的函数组合调用,前半段已经落库,后半段一失败就回不去,留下半截状态(建了任务没发事件、
改了图没记版本)。而同一个领域操作有四个入口(HTTP、智能体工具、工作流节点、飞书),谁该提交
在每个入口各说各的。

约定:

- **领域函数不 commit**。要拿自增默认值(id)就 `db.flush()`。
- **入口层**用 `unit_of_work()`(后台线程、工具、节点)或路由依赖 `Tx`(见 api/deps.transaction)包住一次用例:
  正常结束提交,抛异常回滚。
- 必须**提交之后**才能做的事(起线程去读刚写的行、推送通知)登记成 `after_commit(db, fn)`,
  不要为了它在中途提交。回滚了就不执行。

`tests/test_domain_does_not_commit.py` 守着第一条:领域层的提交只减不增。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.orm import Session, SessionTransaction

from app.core.db import SessionLocal

logger = logging.getLogger(__name__)

_HOOKS = "mosael_after_commit"


def after_commit(db: Session, hook: Callable[[], None]) -> None:
    """这次事务**提交成功之后**再做。回滚了就丢掉。

    挂在 Session 的事件上而不是只在 unit_of_work 里跑:还没迁完的代码照旧自己 `db.commit()`,
    登记的钩子在那一次提交之后同样会执行 —— 迁移期两种写法并存,不能因为提交的人不同就漏跑。

    登记时记下**是在哪个保存点里登记的**:那个保存点回滚了(`begin_nested` 里抛错被接住),外层照样提交,
    而它里面登记的钩子(比如删掉刚删的那行素材的文件)不该跟着跑 —— 行回来了,文件没了。
    """
    db.info.setdefault(_HOOKS, []).append((db.get_nested_transaction(), hook))


def _inside(owner: SessionTransaction | None, transaction: SessionTransaction) -> bool:
    """`owner` 是不是 `transaction` 本身或它里面更深的一层。"""
    while owner is not None:
        if owner is transaction:
            return True
        owner = owner.parent
    return False


@event.listens_for(Session, "after_commit")
def _run_hooks(db: Session) -> None:
    hooks = db.info.pop(_HOOKS, [])
    for _owner, hook in hooks:
        try:
            hook()
        except Exception:  # noqa: BLE001 —— 事务已经提交了,钩子失败不能让调用方以为没提交
            logger.exception("after_commit hook failed")


@event.listens_for(Session, "after_soft_rollback")
def _drop_savepoint_hooks(db: Session, previous_transaction: SessionTransaction) -> None:
    """回滚到保存点:只摘掉**在它里面**登记的钩子,外层的留着。

    不能挂在 `after_rollback` 上:SQLAlchemy 回滚保存点时也发它,而它不说回滚的是哪一层 —— 此前在那里一把清空,
    一个被接住的保存点回滚就让外层已经登记的钩子全丢了。
    """
    if previous_transaction.nested and _HOOKS in db.info:
        db.info[_HOOKS] = [(owner, hook) for owner, hook in db.info[_HOOKS] if not _inside(owner, previous_transaction)]


@event.listens_for(Session, "after_transaction_end")
def _drop_hooks(db: Session, transaction: SessionTransaction) -> None:
    """最外层事务结束了还剩下的钩子(回滚了、会话直接关了)不再跑。提交的那条路在 `_run_hooks` 里已经取走。"""
    if transaction.parent is None:
        db.info.pop(_HOOKS, None)


@contextmanager
def unit_of_work() -> Iterator[Session]:
    """开一个会话,包住一次用例:正常结束提交,抛异常回滚。"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
