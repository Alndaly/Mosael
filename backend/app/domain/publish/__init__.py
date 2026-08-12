"""发布内核(计划 §6.9 / Phase 13):账号 = 平台适配器 + 配置,
发布任务 = 成片素材 + 文案元数据 + 目标账号,执行走任务总线。

平台适配器注册表数据驱动。这里**只有需要登录态的真平台** —— 交付到本地目录 / POST 给外部
自动化不属于发布,它们没有账号、没有登录、没有需要人介入的中间态,在 domain/delivery 里。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import PARTITION_PREFIX
from app.db.models import Asset, Job, PublishAccount, PublishTask, User
from app.domain import sharing
from app.domain.jobs import create_job, register_external_kind

# 发布任务由桌面端执行器经 claim/report 驱动,跨后端重启存活;
# 声明执行模式是领域自己的事,任务总线不点名 publish。
register_external_kind("publish")


class PublishDomainError(ValueError):
    pass


# 平台注册表:config 字段描述驱动 UI 表单与校验。
# 全部由桌面端发布器(Electron 内嵌浏览器 + 账号登录态)认领执行 —— 不再有 executor 字段,
# 因为不需要浏览器的那两种(folder/webhook)已经拆到 domain/delivery 去了。
# title_max 在创建时校验,避免任务在平台侧因超长标题晚失败。
#: 每个平台**自己**的发布选项。声明在这里,别处只消费,不各自硬编码。
#:
#: 三方各取所需,而且都只认这一份:后端据此校验(不在表里的键、不在 choices 里的值一律 422),
#: 前端据此**自动**把控件画出来(不必为每个平台写一段表单),执行器从任务的 options 里取值。
#: 这样加一个平台属性 = 在这张表里加一行,不是在三处各加一段。
#:
#: `default` 同时是「用户没选」时的值。可见性一律默认最保守的那档 —— 自动发布误发公开是收不回的,
#: 而想公开只是到平台上改一次(YouTube 的私享、TikTok 的仅自己可见都是这条理由)。
#:
#: **没有声明 = 那个平台上真的没有**,不是还没做:
#:   ・B 站投稿页(实测):只有「定时发布」和「存草稿 / 立即投稿」,没有可见范围控件;
#:   ・微信视频号发表动态页(实测,穿 shadow DOM 查过):只有「位置 / 添加到合集 / 定时发表」;
#:   ・小红书:本工作区没有已登录账号,没法核对真实界面 —— 不猜。
#: 声明一个平台上不存在的选项,等于让用户设一个不会生效的东西。
PLATFORM_OPTIONS: dict[str, list[dict[str, Any]]] = {
    "youtube": [
        {
            "key": "visibility",
            "label": "可见性",
            "type": "enum",
            "default": "private",
            "choices": [
                {"value": "private", "label": "私享(仅自己)"},
                {"value": "unlisted", "label": "不公开列出(有链接可看)"},
                {"value": "public", "label": "公开"},
            ],
            "description": "默认私享。自动发布误发公开收不回,想公开发完再改一次即可。",
        },
        {
            "key": "made_for_kids",
            "label": "面向儿童的内容",
            "type": "bool",
            "default": False,
            "description": "YouTube 的必答项。选「是」会关掉评论等一批功能,按素材实际情况填。",
        },
    ],
    "douyin": [
        {
            "key": "visibility",
            "label": "谁可以看",
            "type": "enum",
            "default": "private",
            "choices": [
                {"value": "private", "label": "仅自己可见"},
                {"value": "friends", "label": "好友可见"},
                {"value": "public", "label": "公开"},
            ],
            "description": "默认仅自己可见,确认无误后再改公开。",
        },
    ],
    "tiktok": [
        {
            "key": "visibility",
            "label": "谁可以看",
            "type": "enum",
            "default": "private",
            "choices": [
                {"value": "private", "label": "仅自己可见"},
                {"value": "friends", "label": "好友"},
                {"value": "public", "label": "所有人"},
            ],
            "description": "默认仅自己可见,确认无误后再改公开。",
        },
        # 评论/合拍/拼接这几个开关**先不声明**:还没在真实页面上确认它们的结构。声明了却不生效,
        # 比不声明糟得多 —— 用户设了、界面上认了,发出去却没变,而且什么都不会提示。
    ],
}


def option_specs(platform: str) -> list[dict[str, Any]]:
    return PLATFORM_OPTIONS.get(platform, [])


def normalize_options(platform: str, raw: dict[str, Any] | None) -> dict[str, Any]:
    """把用户传来的选项收敛成「这个平台认得的那几个键」,并补上默认值。

    **不认识的键直接报错,不静默丢掉** —— 静默丢掉的后果是用户以为自己设了公开,发出来却是私享,
    而界面上什么都没说。同理,枚举值不在 choices 里也报错。
    """
    specs = option_specs(platform)
    allowed = {spec["key"]: spec for spec in specs}
    for key in (raw or {}):
        if key not in allowed:
            raise PublishDomainError(
                f"{platform} 不支持发布选项 {key!r}(支持:{', '.join(allowed) or '无'})"
            )
    out: dict[str, Any] = {}
    for key, spec in allowed.items():
        value = (raw or {}).get(key, spec["default"])
        if spec["type"] == "bool":
            if not isinstance(value, bool):
                raise PublishDomainError(f"发布选项 {key!r} 需要 true/false(收到 {value!r})")
        elif spec["type"] == "enum":
            values = [choice["value"] for choice in spec["choices"]]
            if value not in values:
                raise PublishDomainError(
                    f"发布选项 {key!r} 只能是 {', '.join(values)}(收到 {value!r})"
                )
        out[key] = value
    return out


PUBLISH_PLATFORMS: dict[str, dict[str, Any]] = {
    "douyin": {
        "label": "抖音",
        "description": "由桌面端发布器用你已登录的抖音创作者账号自动上传;首次使用需在弹出的窗口里登录。",
        "config": {},
        "title_max": 30,
        "short_title": False,
    },
    "xiaohongshu": {
        "label": "小红书",
        "description": "由桌面端发布器用已登录的小红书账号自动上传;首次使用需登录。",
        "config": {},
        "title_max": 20,
        "short_title": False,
    },
    "weixin-channels": {
        "label": "微信视频号",
        "description": "由桌面端发布器用已登录的视频号助手账号自动上传;支持短标题。",
        "config": {},
        "title_max": 16,
        "short_title": True,
    },
    "bilibili": {
        "label": "Bilibili",
        "description": "由桌面端发布器用已登录的 B 站账号自动上传;首次使用需登录。",
        "config": {},
        "title_max": 80,
        "short_title": False,
    },
    # TikTok 与 YouTube 都在境外:登录和上传都要能连上它们,通常得配好出站代理(设置 → 本地后端 /
    # 浏览器档案各自的代理)。连不上时表现为登录页打不开,而不是"登录失败"。
    "tiktok": {
        "label": "TikTok",
        "description": "由桌面端发布器用已登录的 TikTok 账号自动上传;首次使用需登录,境内需要可用的代理。",
        "config": {},
        # TikTok 没有独立标题,发布时那一栏是**文案**(caption),上限 2200。
        "title_max": 2200,
        "short_title": False,
    },
    "youtube": {
        "label": "YouTube",
        # 「通行密钥」这一句不是啰嗦:内嵌视图里 isUserVerifyingPlatformAuthenticatorAvailable()
        # 实测为 false(没有平台认证器),Google 只会给「用另一台设备上的通行密钥」——那条要扫码 + 蓝牙,
        # Electron 走不通,页面会一直转。用户不知道就会干等,所以把出路直接写在他添加账号时看得见的地方。
        "description": (
            "由桌面端发布器用已登录的 YouTube 账号上传;首次使用需登录,境内需要可用的代理。"
            "默认发为私享,确认无误后再自行改公开。"
            "登录时若卡在通行密钥(passkey)验证,点「试试其他方式」改用密码或短信——内嵌浏览器不支持通行密钥。"
        ),
        "config": {},
        "title_max": 100,
        "short_title": False,
    },
}

# 别名 → 规范 id(智能体/用户口语直达,老版同款)。
# **`tiktok` 曾经指向 douyin** —— 那是 TikTok 还没接进来时的权宜,而两者是不同平台、不同账号:
# 说"发到 tiktok"会静默发进抖音。TikTok 独立之后这条必须拆掉。
PLATFORM_ALIASES = {
    "抖音": "douyin", "dy": "douyin",
    "tk": "tiktok", "TikTok": "tiktok", "抖音国际版": "tiktok",
    "yt": "youtube", "YouTube": "youtube", "油管": "youtube",
    "小红书": "xiaohongshu", "xhs": "xiaohongshu", "rednote": "xiaohongshu",
    "视频号": "weixin-channels", "微信视频号": "weixin-channels", "channels": "weixin-channels",
    "wechat": "weixin-channels", "weixin": "weixin-channels",
    "b站": "bilibili", "哔哩哔哩": "bilibili", "bili": "bilibili",
}

# 老版任务状态词汇 1:1,移植的适配器直接映射。
TASK_STATUSES = (
    "pending", "running", "prepared", "success", "failed",
    "login_required", "waiting_manual", "permission_required", "blocked", "cancelled",
)
TERMINAL_TASK_STATUSES = frozenset({"prepared", "success", "failed", "cancelled"})
BINDING_STATUSES = ("unknown", "checking", "bound", "login_required", "manual_required", "permission_required")


def normalize_platform(platform: str) -> str:
    raw = (platform or "").strip()
    lowered = raw.lower()
    canonical = PLATFORM_ALIASES.get(raw, PLATFORM_ALIASES.get(lowered, lowered))
    if canonical not in PUBLISH_PLATFORMS:
        raise PublishDomainError(f"未知平台: {platform!r}(支持 {', '.join(PUBLISH_PLATFORMS)})")
    return canonical



def create_account(
    db: Session, *, workspace_id: str, platform: str, name: str, config: dict[str, Any], owner: User, proxy: str | None = None
) -> PublishAccount:
    platform = normalize_platform(platform)
    meta = PUBLISH_PLATFORMS[platform]
    for key, spec in meta["config"].items():
        if isinstance(spec, dict) and spec.get("required") and not str(config.get(key, "")).strip():
            raise PublishDomainError(f"平台 {platform} 缺少必填配置 {key}")
    account = PublishAccount(
        workspace_id=workspace_id, platform=platform, name=name, config=config, proxy=(proxy or "").strip() or None
    )
    db.add(account)
    db.flush()
    # 平台登录态是某人的身份 —— 默认只有他自己看得见,要给同事用得由他显式共享(见 domain/sharing)。
    sharing.claim(db, "publish_account", account, owner)
    db.commit()
    db.refresh(account)
    # 发布账号即浏览器池档案(组合):按其登录分区 persist:<PARTITION_PREFIX>-<id> 建档并回填,pool 页统一可见,
    # 工作流/智能体可复用其登录。浏览器域负责建档,发布域只写指针(见 domain/browser)。
    from app.domain import browser

    profile = browser.create_profile(
        db, workspace_id=workspace_id, name=name, owner=owner, proxy=account.proxy, partition=f"persist:{PARTITION_PREFIX}-{account.id}"
    )
    account.profile_id = profile.id
    db.commit()
    db.refresh(account)
    return account


def start_publish(
    db: Session,
    *,
    workspace_id: str,
    account: PublishAccount,
    asset: Asset,
    title: str,
    description: str,
    tags: list[str],
    created_by: str | None,
    short_title: str = "",
    options: dict[str, Any] | None = None,
) -> PublishTask:
    if not account.enabled:
        raise PublishDomainError("发布账号已停用")
    if not asset.file_key:
        raise PublishDomainError("素材没有本地文件,无法发布")
    meta = PUBLISH_PLATFORMS[account.platform]
    title_max = int(meta.get("title_max", 300))
    if title and len(title) > title_max:
        raise PublishDomainError(f"{meta['label']} 标题最多 {title_max} 字(当前 {len(title)} 字)")

    job = create_job(
        db,
        workspace_id=workspace_id,
        kind="publish",
        created_by=created_by,
        payload={"account_id": account.id, "asset_id": asset.id, "platform": account.platform},
        message=f"等待桌面发布器认领: {title or asset.name}",
    )
    task = PublishTask(
        workspace_id=workspace_id,
        account_id=account.id,
        asset_id=asset.id,
        title=title,
        description=description,
        tags=tags,
        short_title=short_title,
        # 建任务时就定死:补齐默认值、拒绝非法值。执行器拿到的永远是完整字典。
        options=normalize_options(account.platform, options),
        status="pending",
        job_id=job.id,
    )
    db.add(task)
    db.flush()
    # job payload 带上 task_id:任务中心点击发布任务可直达对应发布详情。
    job.payload = {**job.payload, "task_id": task.id}
    db.commit()
    db.refresh(task)
    return task




def task_with_status(db: Session, task: PublishTask) -> dict[str, Any]:
    job = db.get(Job, task.job_id) if task.job_id else None
    account = db.get(PublishAccount, task.account_id)
    asset = db.get(Asset, task.asset_id)
    platform = account.platform if account else ""
    # 发布任务有自己的状态机(pending/running/login_required/waiting_manual/…),job 表达不了
    # 那些需要人介入的中间态。以前这里要按 executor 在 task.status 和 job.status 之间二选一,
    # 因为本地目录/webhook 也混在这张表里;它们拆走之后就只剩一个来源了。
    status = task.status
    return {
        "id": task.id,
        "workspace_id": task.workspace_id,
        "account_id": task.account_id,
        "account_name": account.name if account else "",
        "platform": platform,
        "asset_id": task.asset_id,
        "asset_name": asset.name if asset else "",
        "title": task.title,
        "description": task.description,
        "tags": list(task.tags or []),
        "status": status,
        "error": task.error_message or (job.error if job else None),
        "result": job.result if job else {},
        "job_id": task.job_id,
        "created_at": task.created_at,
    }


def list_tasks(db: Session, workspace_id: str) -> list[PublishTask]:
    return list(
        db.scalars(
            select(PublishTask).where(PublishTask.workspace_id == workspace_id).order_by(PublishTask.created_at.desc())
        )
    )
