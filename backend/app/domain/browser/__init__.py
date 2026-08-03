"""浏览器自动化子系统(RPA 节点 / 智能体 / 手动)的领域层。

后端进程碰不到 Electron 里的浏览器,于是照搬发布的「拉取 + 回报」桥,但粒度到**单个动作**:
调用方 open_session → run_action(入队一条 BrowserAction 并阻塞轮询到终态)→ close_session;
Electron 的浏览器 worker 认领 queued 动作 → 用 PageDriver 在会话分区的视图上执行 → 回报结果。

会话分区(见 models.BrowserSession):临时 `ephemeral-<id>`(内存态)、具名 `persist:rpa-<name>`、
池档案会话用其档案分区(BrowserProfile.partition,可为发布登录的 `persist:openstudio-<accountId>`)。
「浏览器池」把持久登录身份统一成 BrowserProfile(不再只服务发布);池档案会话受**租约**(一档案
一时刻一会话)约束,接入智能体时再叠**显式授权**闸——见 open_session / _open_profile_session。
"""

from __future__ import annotations

import re
import time

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.domain import sharing
from app.db.models import BrowserAction, BrowserProfile, BrowserSession, PublishAccount, User, now

_UNSET = object()  # update_profile 里区分「不改」与「置空」

# 动作默认超时:navigate 到重前端页可能慢(pageDriver.goto 自身 45s),给足余量;调用方可覆盖。
ACTION_TIMEOUT_SECONDS = 120.0
_ACTION_POLL_SECONDS = 0.2
# worker 回报间隔外的兜底:running 动作超过这个时长没落终态,视为执行器掉线,回收。
STALE_ACTION_SECONDS = 5 * 60

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


# ---------- 浏览器池:档案(持久身份)CRUD ----------


def create_profile(
    db: Session, *, workspace_id: str, name: str, owner: User, proxy: str | None = None, partition: str | None = None
) -> BrowserProfile:
    """新建一个池档案。默认通用档案分区 persist:pool-<id>;发布账号建档时传 partition=
    persist:openstudio-<accountId> 沿用其既有登录分区(见 publish.create_account,登录态不丢)。

    `owner` 是必填的:一个已登录的浏览器是**某人的身份**,不是工作区的公共资产。做成必填参数
    而不是"事后由调用点补一句 claim",是因为漏掉的那个调用点建出来的档案会没有主人 —— 于是谁
    都看不见它,或者(改成默认公开的话)谁都用得上它。
    """
    prof = BrowserProfile(workspace_id=workspace_id, name=(name or "").strip()[:160], proxy=(proxy or None), enabled=True)
    db.add(prof)
    db.flush()
    prof.partition = partition or f"persist:pool-{prof.id}"
    sharing.claim(db, "browser_profile", prof, owner)
    db.commit()
    db.refresh(prof)
    return prof


def get_profile(db: Session, workspace_id: str, profile_id: str) -> BrowserProfile:
    prof = db.get(BrowserProfile, profile_id)
    if prof is None or prof.workspace_id != workspace_id:
        raise BrowserDomainError("浏览器档案不存在")
    return prof


def list_profiles(db: Session, workspace_id: str) -> list[BrowserProfile]:
    return list(
        db.scalars(
            select(BrowserProfile)
            .where(BrowserProfile.workspace_id == workspace_id)
            .order_by(BrowserProfile.created_at.desc())
        )
    )


def update_profile(
    db: Session,
    workspace_id: str,
    profile_id: str,
    *,
    name: str | None = None,
    proxy: str | None | object = _UNSET,
    enabled: bool | None = None,
) -> BrowserProfile:
    prof = get_profile(db, workspace_id, profile_id)
    if name is not None:
        prof.name = name.strip()[:160]
    if proxy is not _UNSET:
        prof.proxy = (proxy or None) if isinstance(proxy, str) else None
    if enabled is not None:
        prof.enabled = enabled
    db.commit()
    db.refresh(prof)
    return prof


def delete_profile(db: Session, workspace_id: str, profile_id: str) -> None:
    """删档案。有活动会话(租约未释放)或被发布账号绑定 → 拒删,避免删掉正在用/发布依赖的登录身份。"""
    prof = get_profile(db, workspace_id, profile_id)
    if db.scalar(
        select(BrowserSession).where(BrowserSession.profile_id == profile_id, BrowserSession.status == "open")
    ):
        raise BrowserDomainError("该档案有正在进行的会话,先结束再删")
    if db.scalar(select(PublishAccount).where(PublishAccount.profile_id == profile_id)):
        raise BrowserDomainError("该档案绑定了发布账号,请先在发布页解绑或删除账号")
    db.delete(prof)
    db.commit()


def open_session(
    db: Session,
    *,
    workspace_id: str,
    kind: str = "ephemeral",
    name: str = "",
    profile_id: str | None = None,
    owner_kind: str = "manual",
    owner_id: str | None = None,
) -> BrowserSession:
    """新建(或复用)浏览器会话。临时会话每次都是新隔离上下文;具名会话跨次复用;池档案会话在
    档案分区上开,受**租约**约束(一个档案同一时刻一个活动会话:同 owner 复用、异 owner 拒绝)。"""
    if profile_id:
        return _open_profile_session(db, workspace_id, profile_id, owner_kind, owner_id)
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


def _open_profile_session(
    db: Session, workspace_id: str, profile_id: str, owner_kind: str, owner_id: str | None
) -> BrowserSession:
    prof = get_profile(db, workspace_id, profile_id)
    if not prof.enabled:
        raise BrowserDomainError("该浏览器档案已停用")
    # 租约:一个档案同一时刻只允许一个活动会话。
    existing = db.scalar(
        select(BrowserSession).where(BrowserSession.profile_id == profile_id, BrowserSession.status == "open")
    )
    if existing is not None:
        if existing.owner_kind == owner_kind and (existing.owner_id or "") == (owner_id or ""):
            return existing  # 同一 owner 复用
        raise BrowserDomainError("该档案正被占用(同一时刻只允许一个会话),请稍后再试")
    session = BrowserSession(
        workspace_id=workspace_id,
        kind="profile",
        name=(prof.name or "")[:80],
        partition=prof.partition,
        profile_id=profile_id,
        owner_kind=owner_kind if owner_kind in ("agent", "workflow", "manual") else "manual",
        owner_id=owner_id,
        status="open",
    )
    db.add(session)
    prof.last_used_at = now()
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
