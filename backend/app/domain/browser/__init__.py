"""浏览器自动化子系统(RPA 节点 / 智能体 / 手动)的领域层。

后端进程碰不到 Electron 里的浏览器,于是照搬发布的「拉取 + 回报」桥,但粒度到**单个动作**:
调用方 open_session → run_action(入队一条 BrowserAction 并阻塞轮询到终态)→ close_session;
Electron 的浏览器 worker 认领 queued 动作 → 用 PageDriver 在会话分区的视图上执行 → 回报结果。

会话分区(见 models.BrowserSession):临时 `ephemeral-<id>`(内存态)、具名 `persist:rpa-<工作区>-<名字哈希>`、
池档案会话用其档案分区(BrowserProfile.partition,可为发布登录的 `persist:mosael-<accountId>`)。
「浏览器池」把持久登录身份统一成 BrowserProfile(不再只服务发布);池档案会话受**租约**(一档案
一时刻一会话)约束,接入智能体时再叠**显式授权**闸——见 open_session / _open_profile_session。
档案归人(见 domain/sharing):开池会话、接着用一个池会话、借档案的 cookie,都要**用的人**自己能用
那个档案(`usable_profile` / `attach_session`,`actor` 必填)。
"""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.unit_of_work import immediate_unit_of_work, unit_of_work
from app.core.i18n import LocalizedError, is_message_key, tr
from app.domain import sharing
from app.domain.authority import Actor
from app.domain.host_files import HostFile
from app.db.models import (
    BrowserAction,
    BrowserPartitionMove,
    BrowserPartitionMoveReceipt,
    BrowserProfile,
    BrowserSession,
    Job,
    PublishAccount,
    User,
    now,
)

_UNSET = object()  # update_profile 里区分「不改」与「置空」

# 动作默认超时:navigate 到重前端页可能慢(pageDriver.goto 自身 45s),给足余量;调用方可覆盖。
#: **从执行器认领那一刻算**,不含排队 —— 排队那段有自己的上限(下一条)。此前截止从入队算:
#: 前面一条长等待占着执行器时,后面那条还没开始跑就已经把自己的时间耗光了。
ACTION_TIMEOUT_SECONDS = 120.0
#: 一条动作最多等多久被执行器领走。领不走说的是另一件事:桌面端没开、浏览器执行器没在跑 ——
#: 和「领走了却一直没做完」分开报,人才知道该去看哪儿。
QUEUE_TIMEOUT_SECONDS = 60.0
_ACTION_POLL_SECONDS = 0.2
# worker 回报间隔外的兜底:running 动作超过这个时长没落终态,视为执行器掉线,回收。
STALE_ACTION_SECONDS = 5 * 60

#: 认领一个动作之后租约活多久。**和 ADR-0002 给任务通道定的是同一个数** —— 它们是同一条
#: 契约的两个实现,分头挑一个数就等于把契约写成了两份。执行器每 20 秒心跳一次来续。
#:
#: 这条通道此前**一条都没落**:没有租约、没有 worker 身份、心跳只报在线。今天单执行器下它
#: 工作正常,问题是没有任何东西能在多执行器或执行器崩溃时保证正确 —— 而隔壁两条通道都有。
WORKER_LEASE_SECONDS = 60

# 文档用途;worker 是动作合法性的最终裁判。
KNOWN_ACTIONS = (
    "navigate", "click", "input", "extract", "wait", "scroll",
    "screenshot", "evaluate", "upload", "press_key", "close",
)


class BrowserDomainError(LocalizedError):
    """浏览器自动化领域错误(会话不存在/动作失败/超时等)。带文案 key(`browserErr_*`),按请求方的
    语言翻 —— 它也经智能体工具回给模型、显示在工具卡上。"""


class BrowserReportError(BrowserDomainError, ValueError):
    """执行器回报被拒(状态不对、动作不存在、租约不归你)。继承 ValueError:回报接口按它回 422。"""


#: 具名会话名字的上限(和 BrowserSession.name 那一列一样长)。
SESSION_NAME_MAX = 80


def named_partition(workspace_id: str, name: str) -> str:
    """具名会话的登录分区:**工作区 + 原名的哈希**。名字本身只用来显示。

    此前是 `persist:rpa-<清洗后的名字>`:没有工作区,A 工作区的「xhs」和 B 工作区的「xhs」是同一份
    登录;清洗把非 ASCII 换成 `-` 再去掉,于是「xhs-主号」「xhs-副号」都成了 `xhs`,「小红书2」「抖音2」
    都成了 `2`,「小红书」干脆是空串。哈希原名就没有这两类碰撞;全是小写十六进制,也躲开了 Electron
    把分区名转小写落盘那一层(`XHS` 和 `xhs` 在磁盘上本来就是同一个目录)。
    """
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]
    return f"persist:rpa-{workspace_id}-{digest}"


def _session_name(name: str) -> str:
    """具名会话的名字:去掉首尾空白,非空、不超长。不合规直接拒 —— 不替人改名,改了就不是他说的那一份登录。"""
    cleaned = (name or "").strip()
    if not cleaned or len(cleaned) > SESSION_NAME_MAX:
        raise BrowserDomainError("browserErr_invalidSessionName", max=SESSION_NAME_MAX)
    return cleaned


# ---------- 浏览器池:档案(持久身份)CRUD ----------


def create_profile(
    db: Session, *, workspace_id: str, name: str, owner: User, proxy: str | None = None, partition: str | None = None
) -> BrowserProfile:
    """新建一个池档案。默认通用档案分区 persist:pool-<id>;发布账号建档时传 partition=
    persist:mosael-<accountId> 沿用其既有登录分区(见 publish.create_account,登录态不丢)。

    `owner` 是必填的:一个已登录的浏览器是**某人的身份**,不是工作区的公共资产。做成必填参数
    而不是"事后由调用点补一句 claim",是因为漏掉的那个调用点建出来的档案会没有主人 —— 于是谁
    都看不见它,或者(改成默认公开的话)谁都用得上它。
    """
    prof = BrowserProfile(workspace_id=workspace_id, name=(name or "").strip()[:160], proxy=(proxy or None), enabled=True)
    db.add(prof)
    db.flush()
    prof.partition = partition or f"persist:pool-{prof.id}"
    sharing.claim(db, "browser_profile", prof, owner)
    db.flush()
    db.refresh(prof)
    return prof


def get_profile(db: Session, workspace_id: str, profile_id: str) -> BrowserProfile:
    prof = db.get(BrowserProfile, profile_id)
    if prof is None or prof.workspace_id != workspace_id:
        raise BrowserDomainError("browserErr_profileNotFound")
    return prof


def usable_profile(db: Session, workspace_id: str, profile_id: str, *, actor: Actor) -> BrowserProfile:
    """取一个**这个人能用**的池档案:在这个工作区里,而且是他的、或者主人共享出来了。

    档案存的是某人已登录的浏览器 —— 借它开会话、取它的 cookie,就是在用那个人的身份。归属在
    这里查(见 domain/sharing.ensure_usable),开会话(`open_session`)和借 cookie(assets/from_url)
    都经过它,不在各入口各抄一遍。`actor` 必填、None 被拒:说不出是谁在用,就不能用别人的身份。
    """
    prof = get_profile(db, workspace_id, profile_id)
    sharing.ensure_usable(db, "browser_profile", prof, actor)
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
    actor: str | None,
) -> BrowserProfile:
    """改档案。只有主人能改(见 sharing.ensure_manageable):共享出去是借给人用,不是交给人管。"""
    prof = get_profile(db, workspace_id, profile_id)
    sharing.ensure_manageable(db, "browser_profile", prof, actor=actor)
    if name is not None:
        prof.name = name.strip()[:160]
    if proxy is not _UNSET:
        prof.proxy = (proxy or None) if isinstance(proxy, str) else None
    if enabled is not None:
        prof.enabled = enabled
    db.flush()
    db.refresh(prof)
    return prof


def delete_profile(db: Session, workspace_id: str, profile_id: str, *, actor: str | None) -> None:
    """删档案。只有主人能删(见 sharing.ensure_manageable)。有活动会话(租约未释放)或被发布账号绑定
    → 拒删,避免删掉正在用/发布依赖的登录身份。"""
    prof = get_profile(db, workspace_id, profile_id)
    sharing.ensure_manageable(db, "browser_profile", prof, actor=actor)
    if db.scalar(
        select(BrowserSession).where(BrowserSession.profile_id == profile_id, BrowserSession.status == "open")
    ):
        raise BrowserDomainError("browserErr_profileHasSession")
    if db.scalar(select(PublishAccount).where(PublishAccount.profile_id == profile_id)):
        raise BrowserDomainError("browserErr_profileLinkedToAccount")
    sharing.forget(db, "browser_profile", prof.id)
    db.delete(prof)
    db.flush()


def open_session(
    db: Session,
    *,
    workspace_id: str,
    kind: str = "ephemeral",
    name: str = "",
    profile_id: str | None = None,
    owner_kind: str = "manual",
    owner_id: str | None = None,
    actor: Actor,
) -> BrowserSession:
    """新建(或复用)浏览器会话。临时会话每次都是新隔离上下文;具名会话的登录跨次保留(分区按工作区 +
    名字定,见 named_partition);池档案会话在档案分区上开。具名和池档案都受**租约**约束(一份登录同一
    时刻一个活动会话:同 owner 复用、异 owner 拒绝)。

    `actor` 是**谁在用**(用户 id):工作流里是这次运行的操作人,确认卡是批准它的人。**必填、
    没有默认值** —— 池档案是某人的登录身份,别人的私有档案在这里被拒(见 `usable_profile`)。
    `owner_kind/owner_id` 是另一件事:会话**归哪次运行管**(谁来关它),不是谁有权用。
    """
    if profile_id:
        return _open_profile_session(db, workspace_id, profile_id, owner_kind, owner_id, actor)
    owner_kind = owner_kind if owner_kind in ("agent", "workflow", "manual") else "manual"
    if kind == "named":
        session_name = _session_name(name)
        partition = named_partition(workspace_id, session_name)
        #: 和池档案同一条租约:一份登录同一时刻只归一个 owner。同 owner(同一次运行里第二个「打开浏览器」)
        #: 复用;别人正开着就拒。此前不看 owner 就复用 —— 两次运行共用一个视图互相点、互相导航,
        #: 先跑完的那次收尾时把会话关掉,另一次做到一半的动作全部落空。
        return _lease_login(
            db,
            BrowserSession(
                workspace_id=workspace_id, kind="named", name=session_name, partition=partition,
                owner_kind=owner_kind, owner_id=owner_id, status="open",
            ),
            busy=lambda: BrowserDomainError("browserErr_sessionBusy", name=session_name),
        )
    session = BrowserSession(
        workspace_id=workspace_id, kind="ephemeral", name="", owner_kind=owner_kind, owner_id=owner_id,
        status="open",
    )
    db.add(session)
    db.flush()
    session.partition = f"ephemeral-{session.id}"  # 依赖 id,故 flush 后再算
    # 这里仍提交:调用方紧接着就 run_action —— 入队和轮询各开自己的会话,执行器在另一个进程里,
    # 都得先看得见这个会话。
    db.commit()
    db.refresh(session)
    return session


def _open_profile_session(
    db: Session, workspace_id: str, profile_id: str, owner_kind: str, owner_id: str | None, actor: Actor
) -> BrowserSession:
    prof = usable_profile(db, workspace_id, profile_id, actor=actor)
    if not prof.enabled:
        raise BrowserDomainError("browserErr_profileDisabled")
    # 租约:一个档案同一时刻只允许一个活动会话(见 _lease_login)。
    return _lease_login(
        db,
        BrowserSession(
            workspace_id=workspace_id,
            kind="profile",
            name=(prof.name or "")[:80],
            partition=prof.partition,
            profile_id=profile_id,
            owner_kind=owner_kind if owner_kind in ("agent", "workflow", "manual") else "manual",
            owner_id=owner_id,
            status="open",
        ),
        busy=lambda: BrowserDomainError("browserErr_profileBusy"),
    )


def login_notice(db: Session, session: BrowserSession) -> str:
    """这个具名会话**第一次**打开时,它的登录没能从升级前带过来的话,说一声为什么(按当前语言);否则空串。

    具名会话的分区按工作区分开那次(迁移 named-browser-partitions-are-per-workspace),一份旧登录只归一处:
    也被别的工作区、别的名字用过的那几份记成 abandoned,原因写在 BrowserPartitionMove.reason。此前那句原因
    只躺在库里 —— 用户只看到「登录没了」。第一次 = 这个分区上还没有更早的会话(会话行从不删)。
    """
    if session.kind != "named":
        return ""
    earlier = db.scalar(
        select(BrowserSession.id).where(
            BrowserSession.partition == session.partition,
            BrowserSession.id != session.id,
            BrowserSession.created_at <= session.created_at,
        ).limit(1)
    )
    if earlier is not None:
        return ""
    move = db.scalar(
        select(BrowserPartitionMove)
        .where(
            BrowserPartitionMove.status == "abandoned",
            #: 另一个名字被挤掉:新分区记着;别的工作区被挤掉:新分区是空的,按工作区 + 名字认
            (BrowserPartitionMove.new_partition == session.partition)
            | (
                (BrowserPartitionMove.workspace_id == session.workspace_id)
                & (BrowserPartitionMove.session_name == session.name)
            ),
        )
        .order_by(BrowserPartitionMove.created_at)
        .limit(1)
    )
    if move is None:
        return ""
    return tr("browserNotice_loginNotCarriedOver", name=session.name, detail=move.reason)


#: 拿租约时库被别的写事务占着(每次最多等 busy_timeout 5 秒),最多试几次;都没拿到就按「被占用」报。
LEASE_ATTEMPTS = 3


def _lease_login(db: Session, wanted: BrowserSession, *, busy: Callable[[], BrowserDomainError]) -> BrowserSession:
    """具名 / 池档案会话的租约:这份登录(分区)上已经开着的那个归同一个 owner 就复用,归别人就拒;没有就开 `wanted`。
    占着它的那个早就没人用了(智能体没关、运行异常退出)的话先收回来再判(见 reclaim_idle_sessions)。

    **判和建在同一个 IMMEDIATE 短事务里**(core.unit_of_work.immediate_unit_of_work):一开头就拿写锁,同一拍的
    另一次打开排在锁上,轮到它时看到的已经是前一个建好的那一行。此前是「先查后建」—— 两边都查到「没有」、各建
    一个(实测过);改成在调用方的事务里插、撞索引再判之后,SQLite WAL 下读过的事务等到写锁时快照已旧,直接报
    database is locked,满负载下复现过。索引仍在,兜的是绕开这里的写入。

    这里提交调用方的会话(open_session 一直会提交它:紧接着的动作在别的连接里读这个会话),只是挪到了租约之前 ——
    它要是攥着写锁,租约那个连接就会排在它自己身后等满超时。
    """
    db.commit()
    for attempt in range(LEASE_ATTEMPTS):
        try:
            session_id = _lease_once(wanted, busy)
            break
        except OperationalError as exc:
            if "database is locked" not in str(exc):
                raise
            if attempt == LEASE_ATTEMPTS - 1:
                raise busy() from exc
    session = db.get(BrowserSession, session_id)
    assert session is not None  # 刚在租约的事务里提交过
    return session


def _lease_once(wanted: BrowserSession, busy: Callable[[], BrowserDomainError]) -> str:
    """判一次:返回复用的或新开的会话 id,归别人就抛 `busy()`。池档案顺带记下用过的时间。"""
    with immediate_unit_of_work() as lease:
        reclaim_idle_sessions(lease, partition=wanted.partition)
        existing = lease.scalar(
            select(BrowserSession).where(BrowserSession.partition == wanted.partition, BrowserSession.status == "open")
        )
        if existing is not None and (
            existing.owner_kind != wanted.owner_kind or (existing.owner_id or "") != (wanted.owner_id or "")
        ):
            raise busy()
        if wanted.profile_id:
            profile = lease.get(BrowserProfile, wanted.profile_id)
            if profile is not None:
                profile.last_used_at = now()
        if existing is not None:
            return existing.id
        fresh = BrowserSession(
            workspace_id=wanted.workspace_id, kind=wanted.kind, name=wanted.name, partition=wanted.partition,
            profile_id=wanted.profile_id, owner_kind=wanted.owner_kind, owner_id=wanted.owner_id, status="open",
        )
        lease.add(fresh)
        lease.flush()
        return fresh.id


def attach_session(db: Session, session_id: str, *, workspace_id: str, actor: Actor) -> BrowserSession | None:
    """接着用一个**已经开着**的会话(工作流下游的浏览器节点、智能体的内联动作)。

    返回 None = 不存在或不在这个工作区,调用方按自己的语境报「找不到」。

    池档案会话还要再查一次归属:会话 id 会顺着上游节点、对话流到别处,**拿到 id 不等于有权用
    那个登录身份**。开会话时查过的是开的那个人;接着用的人得自己也能用这个档案,否则同事拿着
    一个会话 id 就能在别人已登录的浏览器里取 cookie、点发布。
    """
    session = db.get(BrowserSession, session_id)
    if session is None or session.workspace_id != workspace_id:
        return None
    if session.profile_id:
        sharing.ensure_usable(db, "browser_profile", db.get(BrowserProfile, session.profile_id), actor)
    return session


def close_session(db: Session, session_id: str) -> None:
    """关闭会话:落 closed + 入队一条 close 动作,让 worker 拆掉视图(临时会话顺带清存储)。

    **还没跑完的动作一并落 failed。** 否则关掉之后,排在 close 前面的那些照样会被执行器领走
    去执行 —— 用户取消了流程,「点发布」照样点下去;而正等着它们的调用方(run_action)要一直
    等到自己超时才放手。
    """
    session = db.get(BrowserSession, session_id)
    if session is None or session.status != "open":
        return
    _mark_closed(db, session)
    # 这里仍提交:关会话多半是收尾(下载失败的 finally、运行落终态后的收拾),调用方随后可能回滚,
    # 关掉这件事不能跟着回滚 —— 否则执行器那边的视图和排着的动作就没人收了。
    db.commit()


def _mark_closed(db: Session, session: BrowserSession) -> None:
    """关会话本身(不提交):落 closed、没跑完的动作落 failed、给执行器排一条 close 拆视图。"""
    session.status = "closed"
    db.execute(
        update(BrowserAction)
        .where(BrowserAction.session_id == session.id, BrowserAction.status.in_(("queued", "running")))
        .values(status="failed", error="browserErr_sessionClosed")
    )
    db.add(
        BrowserAction(
            session_id=session.id, workspace_id=session.workspace_id, action="close", args={}, status="queued"
        )
    )
    db.flush()


def _idle_cutoff() -> datetime | None:
    """最后一次动作早于这一刻的会话算空闲。≤0 分钟表示不收。"""
    minutes = settings.browser_session_idle_minutes
    return now() - timedelta(minutes=minutes) if minutes > 0 else None


def _reclaimable_sessions(db: Session, *, partition: str | None = None) -> list[BrowserSession]:
    """空着太久、该收回的开着的会话。

    **空闲按最后一次动作算**(没有动作就按打开的时间),还有动作在排、在跑的不算空闲。工作流开的会话
    在那次运行还没落终态时不收:节点之间隔着一段很长的生成很正常,那段时间它没有动作,却还要接着用。
    """
    cutoff = _idle_cutoff()
    if cutoff is None:
        return []
    last_action = (
        select(func.max(BrowserAction.updated_at))
        .where(BrowserAction.session_id == BrowserSession.id)
        .correlate(BrowserSession)
        .scalar_subquery()
    )
    pending = (
        select(BrowserAction.id)
        .where(BrowserAction.session_id == BrowserSession.id, BrowserAction.status.in_(("queued", "running")))
        .correlate(BrowserSession)
        .exists()
    )
    query = select(BrowserSession).where(
        BrowserSession.status == "open", func.coalesce(last_action, BrowserSession.created_at) < cutoff, ~pending
    )
    if partition is not None:
        query = query.where(BrowserSession.partition == partition)
    from app.domain.jobs import TERMINAL_STATUSES  # 同 install():导入期不依赖任务总线

    idle = []
    for session in db.scalars(query).all():
        if session.owner_kind == "workflow" and session.owner_id:
            run = db.get(Job, session.owner_id)
            if run is not None and run.status not in TERMINAL_STATUSES:
                continue
        idle.append(session)
    return idle


def reclaim_idle_sessions(db: Session, *, partition: str | None = None) -> int:
    """把空着太久的会话关掉(不提交,跟着调用方的事务走)。返回关了几个。

    智能体用完浏览器多半不发「关闭」就去干别的了;工作流进程异常退出时,它开的会话也没人关。
    具名 / 池档案会话一时刻只归一个 owner —— 没人收的那一个会让之后每一次同名打开都报「被占用」。
    执行器每次认领都扫一遍,打开会话撞上占用时再就地扫一次那一份登录。
    """
    idle = _reclaimable_sessions(db, partition=partition)
    for session in idle:
        _mark_closed(db, session)
    return len(idle)


def close_sessions_owned_by(db: Session, *, owner_kind: str, owner_id: str) -> int:
    """关掉归这个 owner 的所有还开着的会话。返回关了几个。"""
    owned = db.scalars(
        select(BrowserSession.id).where(
            BrowserSession.owner_kind == owner_kind,
            BrowserSession.owner_id == owner_id,
            BrowserSession.status == "open",
        )
    ).all()
    for session_id in owned:
        close_session(db, session_id)
    return len(owned)


def _close_run_sessions(db: Session, job: Job) -> None:
    """工作流的一次运行落了终态(成功、失败、取消):它开的会话跟着关。

    工作流节点开会话时把 owner 记成**这次运行**的工作流任务(见 workflows/executors/browser)。
    能关会话的「关闭浏览器」节点在失败和取消时都走不到,所以不能只靠它。
    """
    if job.kind == "workflow":
        close_sessions_owned_by(db, owner_kind="workflow", owner_id=job.id)


def install() -> None:
    """装配:任务总线不认识浏览器,是浏览器在这里把「运行结束就关会话」登记进去(app/main.py)。"""
    from app.domain.jobs import register_settle_listener

    register_settle_listener("browser_sessions", _close_run_sessions)


#: 导航只认这几种地址。`file://` 是**读本机文件**:在会话里打开 `file:///…/.ssh/id_rsa` 再
#: extract,就把这台电脑上的私钥读出来了 —— 而本机文件只有部署管理员能读(domain/host_files),
#: 浏览器这条路不该成为绕过它的后门。别的 scheme(javascript:/data:/chrome: …)也没有正当用途。
_NAVIGABLE = re.compile(r"^(https?://|about:blank$)", re.I)


#: 调用方说「这一轮已经不要结果了」的那个问题(工作流:同一张图里别的节点失败了)。浏览器域不认识
#: 工作流,由调用方把问题交进来,每一拍问一次。
StopCheck = Callable[[], bool]


def run_action(
    session_id: str,
    action: str,
    args: dict | None = None,
    *,
    timeout: float = ACTION_TIMEOUT_SECONDS,
    should_stop: StopCheck | None = None,
) -> dict:
    """在会话上跑一个动作:入队 → 阻塞轮询到终态 → 返回 result(失败/超时抛 BrowserDomainError)。

    用独立短会话轮询(照 wait_for_job),既避免长事务,又能看到 worker 在另一连接里的提交。
    `timeout` 是**执行**的上限,从执行器认领那一刻算;排队另有 QUEUE_TIMEOUT_SECONDS。

    两类动作在这里就挡下:`upload` 只能经 `upload_file`(它只收放行过的 `HostFile`),导航只认
    http(s) —— 两者都是「读这台电脑上的文件」的门,见 domain/host_files。
    """
    if action == "upload":
        raise BrowserDomainError("browserErr_uploadNeedsHostFile")
    if action == "navigate":
        url = str((args or {}).get("url") or "").strip()
        if url and not _NAVIGABLE.match(url):
            raise BrowserDomainError("browserErr_navigateScheme")
    return _enqueue(session_id, action, args, timeout=timeout, should_stop=should_stop)


def upload_file(
    session_id: str,
    file: HostFile,
    *,
    selector: str = "",
    timeout_ms: int = 15_000,
    should_stop: StopCheck | None = None,
) -> dict:
    """往会话页面的 `<input type=file>` 塞一个本机文件。

    只收 `HostFile`:它只能由 domain/host_files 造出来(按工作区校验过的素材,或这个人有权读的本机
    路径),所以这里不再判权限 —— 判过了才拿得到这个类型。收裸字符串的话,任何一个调用点忘了过闸,
    别人电脑上的文件就被塞进了任意网页。
    """
    if not isinstance(file, HostFile):
        raise BrowserDomainError("browserErr_uploadNeedsHostFile")
    return _enqueue(
        session_id,
        "upload",
        {"selector": (selector or "").strip(), "path": str(file.path), "timeout_ms": timeout_ms},
        timeout=timeout_ms / 1000 + 20,
        should_stop=should_stop,
    )


def _enqueue(
    session_id: str, action: str, args: dict | None, *, timeout: float, should_stop: StopCheck | None
) -> dict:
    # 入队是自己的一次用例:提交之后执行器(另一个进程)和下面的轮询才看得见它。
    with unit_of_work() as db:
        session = db.get(BrowserSession, session_id)
        if session is None or session.status != "open":
            raise BrowserDomainError("browserErr_sessionClosed")
        act = BrowserAction(
            session_id=session_id,
            workspace_id=session.workspace_id,
            action=action,
            args=args or {},
            status="queued",
        )
        db.add(act)
        db.flush()
        action_id = act.id

    #: 两段各算各的:排队按「本可以被领走却没被领走」的时间累计,执行从**看见它被认领**那一拍算
    #: (轮询间隔 0.2 秒,误差就这么多)。
    #:
    #: **排在同一会话前一条后面的那段不算排队**:同一会话串行(见 claim_next_action),前一条是一次
    #: 60 秒的等待,这一条就得等它 —— 此前排队计时照走,同一次运行里另一条分支在同一个具名会话上的
    #: 动作,前面那条还没做完它就被报成「桌面端没开」。前面那条自己有执行上限,这里不会无限等。
    queued_for = 0.0
    tick = time.monotonic()
    run_deadline: float | None = None
    while True:
        time.sleep(_ACTION_POLL_SECONDS)
        with SessionLocal() as db:
            act = db.get(BrowserAction, action_id)
            if act is None:
                raise BrowserDomainError("browserErr_actionLost")
            outcome = _settled(act)
            if outcome is not None:
                return outcome
            if act.status == "running" and run_deadline is None:
                run_deadline = time.monotonic() + timeout
            #: 认领它的执行器不再续约了(崩了、被杀了、断网了)。租约到点的判定平时由执行器认领 / 心跳时做
            #: (expire_action_leases),而执行器没了就没人来判 —— 此前调用方因此要等满执行上限,报的还是「执行超时」。
            executor_gone = _lease_expired(act)
            behind_own_session = act.status == "queued" and _session_running(db, act.session_id)
        if executor_gone:
            return _give_up(action_id, "browserErr_executorLost")
        elapsed, tick = time.monotonic() - tick, time.monotonic()
        if run_deadline is None and not behind_own_session:
            queued_for += elapsed
        if should_stop is not None and should_stop():
            return _give_up(action_id, "browserErr_actionHalted")
        if run_deadline is None and queued_for >= QUEUE_TIMEOUT_SECONDS:
            return _give_up_unclaimed(action_id)
        if run_deadline is not None and time.monotonic() >= run_deadline:
            return _give_up(action_id, "browserErr_actionTimeout")


def _lease_expired(act: BrowserAction) -> bool:
    """在跑的这条动作,租约到点了吗(和 expire_action_leases 同一个判据:到点了)。"""
    return act.status == "running" and act.lease_expires_at is not None and act.lease_expires_at <= now()


def _session_running(db: Session, session_id: str) -> bool:
    return db.scalar(
        select(BrowserAction.id).where(BrowserAction.session_id == session_id, BrowserAction.status == "running").limit(1)
    ) is not None


def _give_up_unclaimed(action_id: str) -> dict:
    """排队排到了上限。执行器还在(刚认领过、刚心跳过)就说是排队太久、前面有几条;不在才说桌面端没开 ——
    此前一律报后者,执行器明明开着、只是手上满了,人却被打发去检查桌面端。"""
    if not executor_online():
        return _give_up(action_id, "browserErr_actionNotClaimed")
    with SessionLocal() as db:
        mine = db.get(BrowserAction, action_id)
        ahead = db.scalar(
            select(func.count()).select_from(BrowserAction).where(
                BrowserAction.status.in_(("queued", "running")),
                BrowserAction.created_at < mine.created_at,
                BrowserAction.id != action_id,
            )
        ) if mine is not None else 0
    return _give_up(action_id, "browserErr_actionQueueTimeout", seconds=int(QUEUE_TIMEOUT_SECONDS), ahead=ahead or 0)


def _settled(act: BrowserAction) -> dict | None:
    """动作落了终态:done 交回结果,failed 抛出原因;还没落就是 None。"""
    if act.status == "done":
        return dict(act.result or {})
    if act.status == "failed":
        #: `error` 是「key 或一句话」(同 jobs.say):后端自己记的原因(租约到期、重启、超时)
        #: 存 key,按读的人的语言翻;执行器给的原话(页面找不到元素之类)不翻,放进翻好的句子里。
        if is_message_key(act.error or ""):
            raise BrowserDomainError(act.error)
        if act.error:
            raise BrowserDomainError("browserErr_actionFailedDetail", detail=act.error)
        raise BrowserDomainError("browserErr_actionFailed")
    return None


def _give_up(action_id: str, reason: str, **params: object) -> dict:
    """不等了:把还没落终态的动作落 failed(执行器下次心跳就知道这条不归它了,会停手),再抛 `reason`。

    放手的那一拍它可能刚好做完 —— 那就照做完的算,不拿一个已经有的结果去报失败。
    """
    with unit_of_work() as db:
        act = db.get(BrowserAction, action_id)
        if act is not None and act.status in ("queued", "running"):
            act.status = "failed"
            act.error = reason
        elif act is not None:
            outcome = _settled(act)
            if outcome is not None:
                return outcome
    raise BrowserDomainError(reason, **params)


# ---------- worker 侧:claim / report ----------

#: 执行器多久没来(认领或心跳)就不算在线。它空闲时约每秒认领一次,手上满了只每 20 秒心跳一次 ——
#: 给两次心跳的余量。
EXECUTOR_FRESH_SECONDS = 45.0
#: 最近一次有执行器来认领 / 心跳的时刻(monotonic)。**进程内**:后端是单进程(见 core/config 限流那段),
#: 这个问题(「此刻有没有执行器在拉」)也只对这个进程里在等的调用方有意义;重启后归零,第一拍认领就补上。
_executor_contact: float | None = None


def _note_executor_contact() -> None:
    global _executor_contact
    _executor_contact = time.monotonic()


def executor_online() -> bool:
    """最近 EXECUTOR_FRESH_SECONDS 秒里有执行器来认领或心跳过。"""
    return _executor_contact is not None and time.monotonic() - _executor_contact < EXECUTOR_FRESH_SECONDS


def expire_action_leases(db: Session) -> int:
    """租约到点的动作判失败。**判据只有一条:到点了。**

    到点意味着认领它的那个执行器不再心跳 —— 它崩了、被杀了、或者网断了。动作停在 running
    上不会自己回来,而调用方那边只会等到一个"执行器未响应"的超时,看不出是谁的问题。
    """
    stamp = now()
    stale = db.scalars(
        select(BrowserAction).where(
            BrowserAction.status == "running",
            BrowserAction.lease_expires_at.is_not(None),
            BrowserAction.lease_expires_at <= stamp,
        )
    ).all()
    for act in stale:
        act.status = "failed"
        act.error = "browserErr_executorLost"
    if stale:
        db.flush()
    return len(stale)


def renew_action_leases(db: Session, *, worker: str, claims: list[dict[str, str]]) -> list[str]:
    """心跳续约。返回**真的续上了**的那些动作 id —— 没续上的,执行器那边该停手。

    续不上只有三种可能:这条不是你认领的、令牌不对、或者它已经被判过期了。三种都不该让那个
    执行器继续在一个别人正在干的动作上写结果。
    """
    _note_executor_contact()
    expire_action_leases(db)
    stamp = now()
    renewed: list[str] = []
    for claim in claims:
        count = db.execute(
            update(BrowserAction)
            .where(
                BrowserAction.id == claim.get("action_id"),
                BrowserAction.status == "running",
                BrowserAction.lease_worker == worker,
                BrowserAction.lease_token == claim.get("lease_token"),
                BrowserAction.lease_expires_at > stamp,
            )
            .values(lease_expires_at=stamp + timedelta(seconds=WORKER_LEASE_SECONDS))
        ).rowcount
        if count:
            renewed.append(str(claim.get("action_id")))
    return renewed


def abandoned_actions(db: Session, *, worker: str, claims: list[dict[str, str]]) -> list[str]:
    """执行器手上那些动作里,**已经不归它了**的那些 id(调用方放弃了、被判过期、被别人接走)。只读,不续约。

    心跳 20 秒一次,只靠它的话,调用方不等了(运行停下、超时)之后执行器还要在那条动作上接着干最多 20 秒 ——
    接着点、接着等,而失败现场的截图排在它后面。认领循环每一拍顺带问一次,一拍之内就停手。
    """
    gone: list[str] = []
    for claim in claims:
        act = db.get(BrowserAction, str(claim.get("action_id") or ""))
        if (
            act is None
            or act.status != "running"
            or act.lease_worker != worker
            or act.lease_token != claim.get("lease_token")
        ):
            gone.append(str(claim.get("action_id")))
    return gone


def claim_next_action(db: Session, *, worker: str = "") -> dict | None:
    """认领最老的 queued 动作,CAS 翻 running,带上会话分区信息返回给执行器。

    **认领时落租约三件套**(ADR-0002):谁领的、这次的令牌、什么时候到期。此前 `worker` 这个
    参数收下了却一次都没用过,表里也没有对应的列 —— 于是"这个执行器还在吗""这条回报是不是
    它自己领的那条"在这条通道上都没有答案。
    """
    _note_executor_contact()
    # 先把上一个执行器丢下的收掉:它们本该被这一次认领接走,而不是一直占着 running。
    expire_action_leases(db)
    #: 空着太久的会话也在这里收:执行器在线就一直在认领,这是后端唯一一条按时到来的路;收掉时排的
    #: close 动作也正好由这一拍领走,把视图拆了。
    reclaim_idle_sessions(db)
    #: **同一个会话串行,不同会话并发。** 执行器一次领多条、各自跑(见 electron/publish/browserWorker);
    #: 一个会话上还有一条在跑,它后面的就先不发 —— 同一个视图上两个动作交错着点、导航,谁也做不对。
    #: 在这里挡而不是在执行器里排队:领走即开始计执行时间(run_action),排在执行器里的那段不该算进去。
    busy_sessions = select(BrowserAction.session_id).where(BrowserAction.status == "running")
    while True:
        act = db.scalars(
            select(BrowserAction)
            .where(BrowserAction.status == "queued", BrowserAction.session_id.not_in(busy_sessions))
            .order_by(BrowserAction.created_at)
            .limit(1)
        ).first()
        if act is None:
            return None
        token = uuid.uuid4().hex
        expires = now() + timedelta(seconds=WORKER_LEASE_SECONDS)
        changed = db.execute(
            update(BrowserAction)
            .where(BrowserAction.id == act.id, BrowserAction.status == "queued")
            .values(status="running", lease_worker=worker or None, lease_token=token, lease_expires_at=expires)
        ).rowcount
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
            "lease_token": token,
            "lease_expires_at": expires.isoformat() + "Z",
        }


def report_action(
    db: Session,
    action_id: str,
    *,
    status: str,
    result: dict | None = None,
    error: str | None = None,
    last_url: str | None = None,
    lease_token: str | None = None,
) -> BrowserAction:
    """执行器回报动作结果。终态幂等:不覆盖已 done/failed 的动作。

    **回报要带上认领时拿到的令牌。** 不带或者对不上就拒绝:那意味着这条动作已经不是你的了
    (租约过期后被别人接走,或者你是重启前的那个自己)。没有这道检查时,一个失联又活过来的
    执行器会把结果写在**新执行器正在干的那一份**上,而两边都不报错。
    """
    if status not in ("running", "done", "failed"):
        raise BrowserReportError("browserErr_invalidActionStatus")
    act = db.get(BrowserAction, action_id)
    if act is None:
        raise BrowserReportError("browserErr_actionNotFound")
    if act.status in ("done", "failed"):
        return act
    if act.lease_token and lease_token != act.lease_token:
        raise BrowserReportError("browserErr_leaseMismatch")
    act.status = status
    if status == "running":
        # 回报本身也算一次心跳 —— 正在干活的证据比一个单独的心跳帧更硬。
        act.lease_expires_at = now() + timedelta(seconds=WORKER_LEASE_SECONDS)
    if result is not None:
        act.result = result
    if error is not None:
        act.error = error
    if last_url is not None:
        session = db.get(BrowserSession, act.session_id)
        if session is not None:
            session.last_url = last_url
    db.flush()
    db.refresh(act)
    return act


#: 执行器对一条搬家单能回报的结果(见 BrowserPartitionMoveReceipt)。
PARTITION_MOVE_OUTCOMES = ("done", "skipped")


def pending_partition_moves(db: Session, *, worker: str) -> list[dict[str, str]]:
    """这台电脑(执行器 `worker`)还没回过话的搬家单(迁移写下的,见 BrowserPartitionMove)。

    按执行器分:登录数据在各自的磁盘上,一台搬完不等于别的也搬完了。
    """
    answered = select(BrowserPartitionMoveReceipt.id).where(
        BrowserPartitionMoveReceipt.move_id == BrowserPartitionMove.id, BrowserPartitionMoveReceipt.worker == worker
    )
    moves = db.scalars(
        select(BrowserPartitionMove)
        .where(BrowserPartitionMove.status == "pending", ~answered.exists())
        .order_by(BrowserPartitionMove.created_at)
    ).all()
    return [{"id": move.id, "old_partition": move.old_partition, "new_partition": move.new_partition} for move in moves]


def settle_partition_move(db: Session, move_id: str, *, worker: str, status: str, reason: str = "") -> None:
    """执行器回报它那台电脑上的这条搬家单:搬了(done),或者没法搬(skipped,原因写进 reason)。

    只收 pending 的单;同一台回过一次就不再改(回执是它那一刻磁盘上的事实)。
    """
    if status not in PARTITION_MOVE_OUTCOMES:
        raise BrowserReportError("browserErr_invalidActionStatus")
    move = db.get(BrowserPartitionMove, move_id)
    if move is None or move.status != "pending":
        return
    already = db.scalar(
        select(BrowserPartitionMoveReceipt.id).where(
            BrowserPartitionMoveReceipt.move_id == move_id, BrowserPartitionMoveReceipt.worker == worker
        )
    )
    if already is None:
        db.add(BrowserPartitionMoveReceipt(move_id=move_id, worker=worker, status=status, reason=reason[:2000]))
        db.flush()


def reconcile_browser_state() -> int:
    """后端重启:执行器视图已随旧进程消失,把残留的未终态动作落 failed、开着的会话落 closed。
    返回清理的动作数。"""
    cleaned = 0
    with unit_of_work() as db:
        stale = db.scalars(select(BrowserAction).where(BrowserAction.status.in_(("queued", "running")))).all()
        for act in stale:
            act.status = "failed"
            act.error = "browserErr_backendRestarted"
            cleaned += 1
        for session in db.scalars(select(BrowserSession).where(BrowserSession.status == "open")).all():
            session.status = "closed"
    return cleaned
