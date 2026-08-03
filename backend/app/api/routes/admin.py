from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    AdminOverviewOut,
    AdminUserOut,
    DaySeriesPoint,
    ProviderDefaultOut,
    UserSpendPoint,
)
from app.core.permissions import ensure_deployment_admin
from app.domain.provider_defaults import DEFAULTABLE_CAPABILITIES
from app.db.models import (
    Asset,
    AuthSession,
    Job,
    ProviderDefault,
    ProviderModel,
    ProviderUsageEvent,
    User,
    Workspace,
    WorkspaceMember,
    now,
)

router = APIRouter(tags=["admin"])

"""管理员控制台:**这台部署**的状况。

和「设置」是两件事,所以不挤在设置页里:设置回答"我怎么用这个应用"(外观、我的密钥、我的默认
模型);这里回答"这台部署怎么样"—— 谁进来了、谁在花钱、谁的客户端还停在旧版本。

整条路由都在 `ensure_deployment_admin` 后面:普通成员连列表都取不到,前端也据此决定要不要
在侧边栏摆这个入口。
"""

#: 图表窗口。一个跑了两年的部署不该在打开这一页时扫全库 —— 而"最近一个月"正是这一页要回答的
#: 那些问题(谁在用、谁在花)的自然尺度。
WINDOW_DAYS = 30
#: "最近还在用"的判据。
ACTIVE_DAYS = 7


@router.get("/admin/users", response_model=list[AdminUserOut])
def list_users(db: DbSession, user: CurrentUser) -> list[AdminUserOut]:
    """这个部署里的人:身份、最近在用吗、跑的是哪一版。

    版本取他**最近一次**用到的那份凭据上报的 —— 一个人可以同时开着桌面端和网页端,而管理员
    要回答的是"他现在跑的是哪一版"。
    """
    ensure_deployment_admin(db, user)
    people = db.scalars(select(User).order_by(User.created_at)).all()
    latest: dict[str, AuthSession] = {}
    for session in db.scalars(select(AuthSession).order_by(AuthSession.last_seen_at)):
        if session.last_seen_at is not None:
            latest[session.user_id] = session  # 按 last_seen 升序,最后一条即最新
    counts = dict(
        db.execute(
            select(WorkspaceMember.user_id, func.count()).group_by(WorkspaceMember.user_id)
        ).all()
    )
    return [
        AdminUserOut(
            id=person.id,
            username=person.username,
            display_name=person.display_name,
            is_deployment_admin=person.is_deployment_admin,
            created_at=person.created_at,
            last_seen_at=latest[person.id].last_seen_at if person.id in latest else None,
            client_version=latest[person.id].client_version if person.id in latest else "",
            workspaces=int(counts.get(person.id, 0)),
        )
        for person in people
    ]


@router.get("/admin/provider-defaults", response_model=list[ProviderDefaultOut])
def deployment_defaults(db: DbSession, user: CurrentUser) -> list[ProviderDefaultOut]:
    """**部署默认模型** —— 还没设过的人用哪个。

    它是必要的一层,不是可有可无:取默认模型现在**没有"随便挑一个"的兜底**(那个兜底会让
    界面显示 A 而回答来自 B)。所以新人的起点必须有人替他回答,而那个人就是部署管理员。

    此前它只能经 API 置位、没有任何界面 —— 一个没有界面的能力不是功能,是隐藏状态。
    """
    ensure_deployment_admin(db, user)
    out: list[ProviderDefaultOut] = []
    for capability in DEFAULTABLE_CAPABILITIES:
        row = db.get(ProviderDefault, {"capability": capability, "owner_user_id": ""})
        model = db.get(ProviderModel, row.provider_model_id) if row and row.provider_model_id else None
        out.append(
            ProviderDefaultOut(
                capability=capability,
                provider_profile_id=model.provider_profile_id if model else None,
                model=model.model_id if model else "",
                is_mine=False,
            )
        )
    return out


@router.get("/admin/overview", response_model=AdminOverviewOut)
def overview(db: DbSession, user: CurrentUser) -> AdminOverviewOut:
    """这一页顶部的几个数,加上两张图。

    **花销按人分**,不是只给一个总数:管理员要回答的是"谁在花" —— 一个总数说明不了任何该做的
    决定,而按人分的那一列直接指向要谈的那个人。
    """
    ensure_deployment_admin(db, user)
    since = now() - timedelta(days=WINDOW_DAYS)
    active_since = now() - timedelta(days=ACTIVE_DAYS)

    active = db.scalar(
        select(func.count(func.distinct(AuthSession.user_id))).where(AuthSession.last_seen_at >= active_since)
    )
    jobs_by_day = [
        DaySeriesPoint(day=str(day), total=int(total), failed=int(failed or 0))
        for day, total, failed in db.execute(
            select(
                func.date(Job.created_at),
                func.count(),
                func.sum(func.iif(Job.status == "failed", 1, 0)),
            )
            .where(Job.created_at >= since)
            .group_by(func.date(Job.created_at))
            .order_by(func.date(Job.created_at))
        ).all()
    ]
    # 用量事件记的是"哪次调用花了多少",归属在 job 上 —— 顺着 job.created_by 就知道是谁花的。
    spend = [
        UserSpendPoint(
            user_id=str(user_id or ""),
            username=str(username or ""),
            cost_micros=int(cost or 0),
            calls=int(calls or 0),
        )
        for user_id, username, cost, calls in db.execute(
            select(
                Job.created_by,
                User.username,
                func.sum(ProviderUsageEvent.cost_micros),
                func.count(),
            )
            .select_from(ProviderUsageEvent)
            .join(Job, Job.id == ProviderUsageEvent.job_id)
            .join(User, User.id == Job.created_by, isouter=True)
            .where(ProviderUsageEvent.created_at >= since)
            .group_by(Job.created_by, User.username)
            .order_by(func.sum(ProviderUsageEvent.cost_micros).desc())
            .limit(20)
        ).all()
    ]
    return AdminOverviewOut(
        users=db.scalar(select(func.count()).select_from(User)) or 0,
        active_users_7d=int(active or 0),
        workspaces=db.scalar(select(func.count()).select_from(Workspace)) or 0,
        assets=db.scalar(select(func.count()).select_from(Asset)) or 0,
        jobs_by_day=jobs_by_day,
        spend_by_user=spend,
        window_days=WINDOW_DAYS,
    )
