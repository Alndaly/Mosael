"""浏览器自动化子系统(RPA 节点 / 智能体 / 手动)的领域层。

后端进程碰不到 Electron 里的浏览器,于是照搬发布的「拉取 + 回报」桥,但粒度到**单个动作**:
调用方 open_session → run_action(入队一条 BrowserAction 并阻塞轮询到终态)→ close_session;
Electron 的浏览器 worker 认领 queued 动作 → 用 PageDriver 在会话分区的视图上执行 → 回报结果。

会话隔离(见 models.BrowserSession):临时会话用 `ephemeral-<id>`(内存态),具名持久用
`persist:rpa-<name>`,与发布的 `persist:mibu-<accountId>` 严格分命名空间——RPA 侧只会构造前两类
分区,物理上碰不到发布登录。
"""

from __future__ import annotations

import re
import time

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.db.models import BrowserAction, BrowserSession

# 动作默认超时:navigate 到重前端页可能慢(pageDriver.goto 自身 45s),给足余量;调用方可覆盖。
ACTION_TIMEOUT_SECONDS = 120.0
_ACTION_POLL_SECONDS = 0.2
# worker 回报间隔外的兜底:running 动作超过这个时长没落终态,视为执行器掉线,回收。
STALE_ACTION_SECONDS = 5 * 60

VALID_KINDS = ("ephemeral", "named")
# 文档用途;worker 是动作合法性的最终裁判。
KNOWN_ACTIONS = (
    "navigate", "click", "input", "extract", "wait", "scroll",
    "screenshot", "evaluate", "upload", "press_key", "close",
)


class BrowserDomainError(Exception):
    """浏览器自动化领域错误(会话不存在/动作失败/超时等)。"""


def _safe_name(name: str) -> str:
    """具名会话名 → 分区安全片段:只留 [A-Za-z0-9_-],限长。空则非法。"""
    return re.sub(r"[^A-Za-z0-9_-]", "-", (name or "").strip())[:64].strip("-")


def _partition_for(session: BrowserSession) -> str:
    if session.kind == "named":
        return f"persist:rpa-{_safe_name(session.name)}"
    return f"ephemeral-{session.id}"


def open_session(
    db: Session,
    *,
    workspace_id: str,
    kind: str = "ephemeral",
    name: str = "",
    owner_kind: str = "manual",
    owner_id: str | None = None,
) -> BrowserSession:
    """新建(或复用同名的具名)浏览器会话。临时会话每次都是新的隔离上下文。"""
    kind = "named" if kind == "named" else "ephemeral"
    safe = ""
    if kind == "named":
        safe = _safe_name(name)
        if not safe:
            raise BrowserDomainError("具名会话需要合法名称(字母/数字/-/_)")
        existing = db.scalar(
            select(BrowserSession).where(
                BrowserSession.workspace_id == workspace_id,
                BrowserSession.kind == "named",
                BrowserSession.name == safe,
                BrowserSession.status == "open",
            )
        )
        if existing is not None:
            return existing  # 复用:具名会话就是要跨次保留

    session = BrowserSession(
        workspace_id=workspace_id,
        kind=kind,
        name=safe,
        owner_kind=owner_kind if owner_kind in ("agent", "workflow", "manual") else "manual",
        owner_id=owner_id,
        status="open",
    )
    db.add(session)
    db.flush()
    session.partition = _partition_for(session)  # 依赖 id(临时会话),故 flush 后再算
    db.commit()
    db.refresh(session)
    return session


def close_session(db: Session, session_id: str) -> None:
    """关闭会话:落 closed + 入队一条 close 动作,让 worker 拆掉视图(临时会话顺带清存储)。"""
    session = db.get(BrowserSession, session_id)
    if session is None or session.status != "open":
        return
    session.status = "closed"
    db.add(
        BrowserAction(
            session_id=session_id, workspace_id=session.workspace_id, action="close", args={}, status="queued"
        )
    )
    db.commit()


def list_sessions(db: Session, workspace_id: str, *, include_closed: bool = False) -> list[BrowserSession]:
    stmt = select(BrowserSession).where(BrowserSession.workspace_id == workspace_id)
    if not include_closed:
        stmt = stmt.where(BrowserSession.status == "open")
    return list(db.scalars(stmt.order_by(BrowserSession.created_at.desc())))


def run_action(
    session_id: str,
    action: str,
    args: dict | None = None,
    *,
    timeout: float = ACTION_TIMEOUT_SECONDS,
) -> dict:
    """在会话上跑一个动作:入队 → 阻塞轮询到终态 → 返回 result(失败/超时抛 BrowserDomainError)。

    用独立短会话轮询(照 wait_for_job),既避免长事务,又能看到 worker 在另一连接里的提交。
    """
    with SessionLocal() as db:
        session = db.get(BrowserSession, session_id)
        if session is None or session.status != "open":
            raise BrowserDomainError("浏览器会话不存在或已关闭")
        act = BrowserAction(
            session_id=session_id,
            workspace_id=session.workspace_id,
            action=action,
            args=args or {},
            status="queued",
        )
        db.add(act)
        db.commit()
        action_id = act.id

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(_ACTION_POLL_SECONDS)
        with SessionLocal() as db:
            act = db.get(BrowserAction, action_id)
            if act is None:
                raise BrowserDomainError("浏览器动作丢失")
            if act.status == "done":
                return dict(act.result or {})
            if act.status == "failed":
                raise BrowserDomainError(act.error or "浏览器动作失败")

    # 超时:把动作落 failed(未被 worker 认领/执行器无响应),再抛。
    with SessionLocal() as db:
        act = db.get(BrowserAction, action_id)
        if act is not None and act.status in ("queued", "running"):
            act.status = "failed"
            act.error = "浏览器动作超时(执行器未响应)"
            db.commit()
    raise BrowserDomainError("浏览器动作超时(执行器未响应)")


# ---------- worker 侧:claim / report ----------


def claim_next_action(db: Session, *, worker: str = "") -> dict | None:
    """认领最老的 queued 动作,CAS 翻 running,带上会话分区信息返回给执行器。"""
    while True:
        act = db.scalars(
            select(BrowserAction).where(BrowserAction.status == "queued").order_by(BrowserAction.created_at).limit(1)
        ).first()
        if act is None:
            return None
        changed = db.execute(
            update(BrowserAction)
            .where(BrowserAction.id == act.id, BrowserAction.status == "queued")
            .values(status="running")
        ).rowcount
        db.commit()
        if not changed:
            continue  # 被别的 worker 抢了,取下一条
        session = db.get(BrowserSession, act.session_id)
        return {
            "id": act.id,
            "session_id": act.session_id,
            "partition": session.partition if session else "",
            "kind": session.kind if session else "ephemeral",
            "action": act.action,
            "args": dict(act.args or {}),
        }


def report_action(
    db: Session,
    action_id: str,
    *,
    status: str,
    result: dict | None = None,
    error: str | None = None,
    last_url: str | None = None,
) -> BrowserAction:
    """执行器回报动作结果。终态幂等:不覆盖已 done/failed 的动作。"""
    if status not in ("running", "done", "failed"):
        raise ValueError("非法动作状态")
    act = db.get(BrowserAction, action_id)
    if act is None:
        raise ValueError("动作不存在")
    if act.status in ("done", "failed"):
        return act
    act.status = status
    if result is not None:
        act.result = result
    if error is not None:
        act.error = error
    if last_url is not None:
        session = db.get(BrowserSession, act.session_id)
        if session is not None:
            session.last_url = last_url
    db.commit()
    db.refresh(act)
    return act


def reconcile_browser_state() -> int:
    """后端重启:执行器视图已随旧进程消失,把残留的未终态动作落 failed、开着的会话落 closed。
    返回清理的动作数。"""
    cleaned = 0
    with SessionLocal() as db:
        stale = db.scalars(select(BrowserAction).where(BrowserAction.status.in_(("queued", "running")))).all()
        for act in stale:
            act.status = "failed"
            act.error = "后端重启导致中断"
            cleaned += 1
        for session in db.scalars(select(BrowserSession).where(BrowserSession.status == "open")).all():
            session.status = "closed"
        if stale:
            db.commit()
        else:
            db.commit()
    return cleaned
