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
from app.core.i18n import LocalizedError, tr
from app.db.models import Asset, Job, PublishAccount, PublishTask, User
from app.domain.authority import Actor, actor_id
from app.domain import sharing
from app.domain.jobs import create_job, register_external_kind

# 发布任务由桌面端执行器经 claim/report 驱动,跨后端重启存活;
# 声明执行模式是领域自己的事,任务总线不点名 publish。
register_external_kind("publish")


class PublishDomainError(LocalizedError, ValueError):
    """发布被拒。带文案 key(`publishErr_*`,见 core/i18n),按请求方的语言翻。"""


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
            "label": "publishOpt_visibility",
            "type": "enum",
            "default": "private",
            "choices": [
                {"value": "private", "label": "publishVis_ytPrivate"},
                {"value": "unlisted", "label": "publishVis_ytUnlisted"},
                {"value": "public", "label": "publishVis_public"},
            ],
            "description": "publishOptDesc_ytVisibility",
        },
        {
            "key": "made_for_kids",
            "label": "publishOpt_madeForKids",
            "type": "bool",
            "default": False,
            "description": "publishOptDesc_madeForKids",
        },
    ],
    "xiaohongshu": [
        {
            "key": "original",
            "label": "publishOpt_original",
            "type": "bool",
            "default": False,
            "description": "publishOptDesc_original",
        },
        {
            "key": "visibility",
            "label": "publishOpt_visibility",
            "type": "enum",
            "default": "private",
            "choices": [
                {"value": "private", "label": "publishVis_onlyMe"},
                {"value": "friends", "label": "publishVis_mutuals"},
                {"value": "public", "label": "publishVis_publicVisible"},
            ],
            "description": "publishOptDesc_privateFirst",
        },
    ],
    "douyin": [
        {
            "key": "visibility",
            "label": "publishOpt_whoCanSee",
            "type": "enum",
            "default": "private",
            "choices": [
                {"value": "private", "label": "publishVis_onlyMe"},
                {"value": "friends", "label": "publishVis_friendsVisible"},
                {"value": "public", "label": "publishVis_public"},
            ],
            "description": "publishOptDesc_privateFirst",
        },
    ],
    "tiktok": [
        {
            "key": "visibility",
            "label": "publishOpt_whoCanSee",
            "type": "enum",
            "default": "private",
            "choices": [
                {"value": "private", "label": "publishVis_onlyMe"},
                {"value": "friends", "label": "publishVis_friends"},
                {"value": "public", "label": "publishVis_everyone"},
            ],
            "description": "publishOptDesc_privateFirst",
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
                "publishErr_unknownOption", platform=platform, option=repr(key),
                supported=", ".join(allowed) or tr("genErr_none"),
            )
    out: dict[str, Any] = {}
    for key, spec in allowed.items():
        value = (raw or {}).get(key, spec["default"])
        if spec["type"] == "bool":
            if not isinstance(value, bool):
                raise PublishDomainError("publishErr_optionNeedsBool", option=repr(key), value=repr(value))
        elif spec["type"] == "enum":
            values = [choice["value"] for choice in spec["choices"]]
            if value not in values:
                raise PublishDomainError(
                    "publishErr_optionChoices", option=repr(key), choices=", ".join(values), value=repr(value)
                )
        out[key] = value
    return out


#: 能下发的**内容形状**(ADR 0076)。`document` 刻意不在里面:没有平台接受一份文档文件,它要先
#: 在素材域转换成下面三种之一。加一种形状 = 这里加一个值 + 适配器实现同名方法 + 前端加一档,
#: 三处对不上就有测试会红(见 tests/test_publish_content_kinds.py)。
CONTENT_KINDS = ("video", "image-text", "article")

#: 每种形状在**默认**(平台没单独声明)情况下的上限。平台声明覆盖它。
#: `None` = 没核实过,就不拦 —— 宁可等平台自己拒,也不要凭猜写一个数把用户挡住。
DEFAULT_CONTENT_LIMITS: dict[str, dict[str, Any]] = {
    "video": {"max_items": 1},
    "image-text": {"max_items": 18, "body_max": None},
    "article": {"max_items": None, "body_max": None, "body_min": None},
}


def content_limits(platform: str, kind: str) -> dict[str, Any]:
    """这个平台这种形状的上限:平台声明 > 默认。"""
    declared = (PUBLISH_PLATFORMS.get(platform, {}).get("content") or {}).get(kind)
    if declared is None:
        return {}
    return {**DEFAULT_CONTENT_LIMITS.get(kind, {}), **declared}


#: **我们已经会发**的形状(执行器侧适配器声明的那一份,由 electron/publish/adapters/*.ts 的
#: `supports` 交叉核对,见 tests/test_publish_adapter_supports_match_registry.py)。
#: 它和 `content_kinds`(平台能发什么)是两件事:这里是**进度**,界面只列这里有的,不摆一个点了会
#: 在真实页面上失败的选项。
IMPLEMENTED_KINDS: dict[str, tuple[str, ...]] = {
    "xiaohongshu": ("video", "image-text"),
    #: 抖音图文 2026-10-23 真机核对后接上:标题 20 字、描述 1000 字、≤35 张图(单图 ≤50MB,
    #: jpg/jpeg/png/webp,不支持 gif)。入口在投稿页的「发布图文」tab。
    "douyin": ("video", "image-text"),
    #: X 图文 2026-10-24 接上:≤4 张图,正文一栏(标题并进正文)。见 PUBLISH_PLATFORMS["x"]。
    "x": ("video", "image-text"),
}


def implemented_kinds(platform: str) -> tuple[str, ...]:
    """界面上能选的形状:平台能发 ∩ 我们已经会发。"""
    return tuple(IMPLEMENTED_KINDS.get(platform, ("video",)))


def content_kinds(platform: str) -> tuple[str, ...]:
    """这个平台认哪几种形状;空 = 只发视频(老平台注册表不用改)。"""
    return tuple(PUBLISH_PLATFORMS.get(platform, {}).get("kinds") or ("video",))


PUBLISH_PLATFORMS: dict[str, dict[str, Any]] = {
    "douyin": {
        "label": "抖音",
        "description": "platformDesc_douyin",
        "config": {},
        "title_max": 30,
        "short_title": False,
        # 真机(2026-10-22):创作中心四个 tab —— 视频 / 图文(≤35 张、单图 ≤50MB、无 gif)/ 文章。
        "kinds": ("video", "image-text", "article"),
        "content": {
            #: 真机(2026-10-23):标题 0/20、描述 0/1000、最多 35 张图。
            "image-text": {"max_items": 35, "title_max": 20, "body_max": 1000},
            "article": {"title_max": 30, "body_max": 20000},
        },
    },
    "xiaohongshu": {
        "label": "小红书",
        "description": "platformDesc_xiaohongshu",
        "config": {},
        "title_max": 20,
        "short_title": False,
        # 真机(2026-10-22):上传图文 ≤18 张(计数 1/18)、单图 ≤32MB、正文 0/1000、无 gif;
        # 「写长文」标题 maxlength=64、正文只显示字数不标上限。
        "kinds": ("video", "image-text", "article"),
        "content": {
            "image-text": {"max_items": 18, "body_max": 1000},
            "article": {"title_max": 64, "body_max": None},
        },
    },
    "weixin-channels": {
        "label": "微信视频号",
        "description": "platformDesc_weixinChannels",
        "config": {},
        "title_max": 16,
        "short_title": True,
        # 助手端图文 ≤18 张(手机端 ≤20);**超过 18 张会变成视频** —— 适配器要挡在 18。
        "kinds": ("video", "image-text"),
        "content": {"image-text": {"max_items": 18, "body_max": 1000}},
    },
    "bilibili": {
        "label": "Bilibili",
        "description": "platformDesc_bilibili",
        "config": {},
        "title_max": 80,
        "short_title": False,
        # 专栏(文章)真机确认入口;字数/图片上限仍是二手口径(200–20000 字、标题 ≤40),
        # 且**发布后不能编辑** —— 发之前必须让人看全文。
        "kinds": ("video", "image-text", "article"),
        "content": {
            "image-text": {"max_items": None},
            "article": {"title_max": 40, "body_min": 200, "body_max": 20000},
        },
    },
    # TikTok 与 YouTube 都在境外:登录和上传都要能连上它们,通常得配好出站代理(管理 → 部署设置 /
    # 浏览器档案各自的代理)。连不上时表现为登录页打不开,而不是"登录失败"。
    "tiktok": {
        "label": "TikTok",
        "description": "platformDesc_tiktok",
        "config": {},
        # TikTok 没有独立标题,发布时那一栏是**文案**(caption),上限 2200。
        "title_max": 2200,
        "short_title": False,
        # Studio 照片轮播:≤35 张、单图 ≤50MB;标题 90 / 描述 4000(页面口径)。
        "kinds": ("video", "image-text"),
        "content": {"image-text": {"max_items": 35, "title_max": 90, "body_max": 4000}},
    },
    # X(Twitter):没有发布选项 —— 帖子即公开,不存在「仅自己可见」分档,PLATFORM_OPTIONS 里
    # 不给它声明任何键(声明了不生效比不声明糟)。
    "x": {
        "label": "X",
        "description": "platformDesc_x",
        "config": {},
        # X 没有标题栏:这一栏是**帖子正文**,上限 280。
        "title_max": 280,
        "short_title": False,
        # 帖子:≤280 字、1–4 张图;长文(Articles)入口待真机,先不声明 article。
        # 图文 2026-10-24 真机核对:撰写页的同一个文件框收图片(可多选),正文一栏装
        # 「标题 + 空行 + 正文」—— 所以我们把标题并进正文一起发。
        "kinds": ("video", "image-text"),
        "content": {"image-text": {"max_items": 4, "title_max": 70, "body_max": 260}},
    },
    "youtube": {
        "label": "YouTube",
        # 「通行密钥」这一句不是啰嗦:内嵌视图里 isUserVerifyingPlatformAuthenticatorAvailable()
        # 实测为 false(没有平台认证器),Google 只会给「用另一台设备上的通行密钥」——那条要扫码 + 蓝牙,
        # Electron 走不通,页面会一直转。用户不知道就会干等,所以把出路直接写在他添加账号时看得见的地方。
        "description": "platformDesc_youtube",
        "config": {},
        "title_max": 100,
        "short_title": False,
        # 社区帖子:文字 + ≤10 图,且频道要先「启用我的社区」。
        "kinds": ("video", "image-text"),
        "content": {"image-text": {"max_items": 10}},
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
    "x": "x", "X": "x", "twitter": "x", "Twitter": "x", "推特": "x",
}

# 老版任务状态词汇 1:1,移植的适配器直接映射。
TASK_STATUSES = (
    "pending", "running", "success", "failed",
    "login_required", "waiting_manual", "permission_required", "blocked", "cancelled",
)
TERMINAL_TASK_STATUSES = frozenset({"success", "failed", "cancelled"})
BINDING_STATUSES = ("unknown", "checking", "bound", "login_required", "manual_required", "permission_required")

#: 发布任务的状态怎么归到首页那三档。**三个集合合起来必须正好是 TASK_STATUSES**
#: (由 test_publish_statuses_are_all_classified 钉住)—— 下面那个兜底会把没归类的状态
#: 悄悄算成"进行中",于是漏掉一个的表现不是报错,是首页永远显示有几条在跑。
#: `queued` 曾经就在这里,而发布任务根本没有这个状态(建出来是 pending,之后只走 report_task)。
#:
#: 住在发布域里:它说的是**发布任务的状态**,不是首页那个接口的事。此前它长在
#: api/routes/workspaces.py 里,于是要用它的人(首页聚合、以后的日报)得去 import 一个路由模块。
ACTIVE_STATUSES = frozenset({"pending", "running"})
BLOCKED_STATUSES = frozenset({"login_required", "waiting_manual", "permission_required", "blocked"})


def summary_bucket(status: str) -> str:
    """一个发布任务在首页那三档里算哪一档。"""
    if status == "success":
        return "succeeded"
    if status in ("failed", "cancelled"):
        return "failed"
    if status in BLOCKED_STATUSES:
        return "blocked"
    if status in ACTIVE_STATUSES:
        return "active"
    return "active"


def normalize_platform(platform: str) -> str:
    raw = (platform or "").strip()
    lowered = raw.lower()
    canonical = PLATFORM_ALIASES.get(raw, PLATFORM_ALIASES.get(lowered, lowered))
    if canonical not in PUBLISH_PLATFORMS:
        raise PublishDomainError(
            "publishErr_unknownPlatform", platform=repr(platform), supported=", ".join(PUBLISH_PLATFORMS)
        )
    return canonical



def create_account(
    db: Session, *, workspace_id: str, platform: str, name: str, config: dict[str, Any], owner: User, proxy: str | None = None
) -> PublishAccount:
    platform = normalize_platform(platform)
    meta = PUBLISH_PLATFORMS[platform]
    for key, spec in meta["config"].items():
        if isinstance(spec, dict) and spec.get("required") and not str(config.get(key, "")).strip():
            raise PublishDomainError("publishErr_missingConfig", platform=platform, key=key)
    account = PublishAccount(
        workspace_id=workspace_id, platform=platform, name=name, config=config, proxy=(proxy or "").strip() or None
    )
    db.add(account)
    db.flush()
    # 平台登录态是某人的身份 —— 默认只有他自己看得见,要给同事用得由他显式共享(见 domain/sharing)。
    sharing.claim(db, "publish_account", account, owner)
    # 发布账号即浏览器池档案(组合):按其登录分区 persist:<PARTITION_PREFIX>-<id> 建档并回填,pool 页统一可见,
    # 工作流/智能体可复用其登录。浏览器域负责建档,发布域只写指针(见 domain/browser)。
    from app.domain import browser

    profile = browser.create_profile(
        db, workspace_id=workspace_id, name=name, owner=owner, proxy=account.proxy, partition=f"persist:{PARTITION_PREFIX}-{account.id}"
    )
    account.profile_id = profile.id
    db.flush()
    db.refresh(account)
    return account


def update_account(db: Session, account: PublishAccount, changes: dict[str, Any], *, actor: str | None) -> PublishAccount:
    """改名、改配置、停用 / 启用、改代理。只有主人能改(见 sharing.ensure_manageable)。"""
    sharing.ensure_manageable(db, "publish_account", account, actor=actor)
    if changes.get("name"):
        account.name = changes["name"]
    if changes.get("config") is not None:
        account.config = changes["config"]
    if changes.get("enabled") is not None:
        account.enabled = changes["enabled"]
    if "proxy" in changes:
        # 空串 → 清成 None(直连);否则存去空白后的值。
        account.proxy = (changes["proxy"] or "").strip() or None
    db.flush()
    db.refresh(account)
    return account


def recheck_account(db: Session, account: PublishAccount, *, actor: str | None) -> PublishAccount:
    """把账号标记为待复检:执行器的下一次巡检立刻认领它重测登录态。只有主人能点。"""
    sharing.ensure_manageable(db, "publish_account", account, actor=actor)
    account.binding_status = "unknown"
    account.last_checked_at = None
    account.last_error = None
    db.flush()
    db.refresh(account)
    return account


def delete_account(db: Session, account: PublishAccount, *, actor: str | None) -> None:
    """删发布账号(发布任务随外键级联)。只有主人能删。

    **还没发完的任务先撤单**:任务行随外键一起没了,而它背后那个任务总线上的 job 不会 —— 此前它一直停在「排队 / 运行中」,
    任务中心和等着它的工作流节点永远等不到结果。撤单让 job 落取消态;正在发的那条,桌面发布器每半秒查一次任务状态,
    查不到任务就中止(electron/publish/publishWorker.ts 的 checkpoint)。"""
    from app.domain.jobs import cancel_job_tree

    sharing.ensure_manageable(db, "publish_account", account, actor=actor)
    for task in db.scalars(select(PublishTask).where(
        PublishTask.account_id == account.id, PublishTask.status.notin_(TERMINAL_TASK_STATUSES),
    )):
        job = db.get(Job, task.job_id) if task.job_id else None
        if job is not None:
            cancel_job_tree(db, job, by=actor)  # 已经落了终态的不动;顺带把任务撤单(见 jobs._cancel_job_row)
        task.status = "cancelled"
    sharing.forget(db, "publish_account", account.id)
    db.delete(account)
    db.flush()


def active_tasks_for_asset(db: Session, asset_id: str) -> list[PublishTask]:
    """这份素材还在发的那些任务(没落终态的)。删素材之前问一声(见 assets.deletion.delete_asset)。"""
    return list(db.scalars(select(PublishTask).where(
        PublishTask.asset_id == asset_id, PublishTask.status.notin_(TERMINAL_TASK_STATUSES),
    )))


def start_publish(
    db: Session,
    *,
    workspace_id: str,
    account: PublishAccount,
    assets: list[Asset],
    kind: str,
    title: str,
    description: str,
    tags: list[str],
    actor: Actor,
    short_title: str = "",
    options: dict[str, Any] | None = None,
    body: str = "",
) -> PublishTask:
    """建一条发布任务 —— **所有发布入口的唯一实现**(发布页、工作流发布节点、智能体确认卡)。
    守着它的是 tests/test_private_identities_need_their_owner.py:每个调用点都写出 actor,每个入口
    都真的会拒。

    `actor` 是**谁在发**:路由里是当前用户,工作流里是这次运行的操作人(`jobs.current_actor`;
    定时任务与 webhook 触发的运行记在任务主人头上),确认卡是批准它的那个人。它同时是任务的
    `created_by`。工作流里它是这次运行的 `Authority`(见 domain/authority):被执行的那一版图也要有
    一个能用这个账号的担保人 —— 同事改过的图借不到主人的账号,直到主人认可那一版。

    **必填、没有默认值**,归属就在这里查:私有账号只有主人和被共享到的人能用(见
    domain/sharing)。此前各入口只查了「是不是这个工作区的人」,同事猜到 id、或在工作流里填上
    别人的账号 id,就能拿别人的登录态发帖。把这道闸放在入口上,第四个入口就会漏;放在这里,
    漏传 `actor` 是类型错误,传 None 是被拒 —— 没有「不知道是谁就放行」。

    执行器(publish worker)认领的是**已经过了这道闸**的任务,那一侧不再重查。
    """
    sharing.ensure_usable(db, "publish_account", account, actor)
    if not account.enabled:
        raise PublishDomainError("publishErr_accountDisabled")
    meta = PUBLISH_PLATFORMS[account.platform]
    #: 三种真实形状(ADR 0076):`document` 不是其中一种 —— 它要先在素材域转换成下面之一。
    if kind not in CONTENT_KINDS:
        raise PublishDomainError("publishErr_unknownKind", kind=repr(kind), supported=", ".join(CONTENT_KINDS))
    declared = content_kinds(account.platform)
    if kind not in declared:
        raise PublishDomainError(
            "publishErr_kindUnsupported", platform=meta["label"], kind=kind, supported=", ".join(declared)
        )
    #: 素材**只有一种形状**:一份列表。视频就是只装一份的那个列表(ADR 0076 之后没有第二种传法)。
    items = [one for one in assets if one is not None]
    limits = content_limits(account.platform, kind)
    if not items:
        raise PublishDomainError("publishErr_noAssets", platform=meta["label"], kind=kind)
    max_items = limits.get("max_items")
    if max_items is not None and len(items) > int(max_items):
        raise PublishDomainError(
            "publishErr_tooManyAssets", platform=meta["label"], kind=kind, max=int(max_items), count=len(items)
        )
    if kind == "video" and len(items) != 1:
        raise PublishDomainError("publishErr_videoNeedsOneAsset", count=len(items))
    for one in items:
        if not one.file_key:
            raise PublishDomainError("publishErr_assetNoFile")
    #: 正文长度:平台声明了的才拦(没核实过的不猜,交给平台自己拒)。
    body = body or ""
    body_min = limits.get("body_min")
    body_max = limits.get("body_max")
    if body_min is not None and 0 < len(body) < int(body_min):
        raise PublishDomainError("publishErr_bodyTooShort", platform=meta["label"], min=int(body_min), count=len(body))
    if body_max is not None and len(body) > int(body_max):
        raise PublishDomainError("publishErr_bodyTooLong", platform=meta["label"], max=int(body_max), count=len(body))
    title_max = int(limits.get("title_max") or meta.get("title_max", 300))
    if title and len(title) > title_max:
        raise PublishDomainError("publishErr_titleTooLong", platform=meta["label"], max=title_max, count=len(title))
    first = items[0]

    job = create_job(
        db,
        workspace_id=workspace_id,
        kind="publish",
        created_by=actor_id(actor),
        payload={
            "account_id": account.id,
            "asset_id": first.id,
            "asset_ids": [one.id for one in items],
            "content_kind": kind,
            "platform": account.platform,
            "subject": title or first.name,
        },
        message="jobMsg_publishWaiting", message_params={"title": title or first.name},
    )
    task = PublishTask(
        workspace_id=workspace_id,
        account_id=account.id,
        asset_id=first.id,
        #: 素材之后删了,记录还说得出发的是什么(见 PublishTask.asset_id)。
        asset_name=first.name or "",
        content_kind=kind,
        asset_ids=[one.id for one in items],
        body=body,
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
    db.flush()
    db.refresh(task)
    return task




def task_with_status(db: Session, task: PublishTask) -> dict[str, Any]:
    job = db.get(Job, task.job_id) if task.job_id else None
    account = db.get(PublishAccount, task.account_id)
    asset = db.get(Asset, task.asset_id) if task.asset_id else None
    platform = account.platform if account else ""
    # 发布任务有自己的状态机(pending/running/login_required/waiting_manual/…),job 表达不了
    # 那些需要人介入的中间态。以前这里要按 executor 在 task.status 和 job.status 之间二选一,
    # 因为本地目录/webhook 也混在这张表里;它们拆走之后就只剩一个来源了。
    status = task.status
    asset_ids = list(task.asset_ids)
    return {
        "id": task.id,
        "workspace_id": task.workspace_id,
        "account_id": task.account_id,
        "account_name": account.name if account else "",
        "platform": platform,
        "asset_id": task.asset_id,
        #: 这份任务的素材(按发出去的顺序);视频就是一份。
        "asset_ids": asset_ids,
        "content_kind": task.content_kind,
        "body": task.body or "",
        #: 素材删了,记录还在(asset_id 为空):名字取建任务时记下的那份。
        "asset_name": asset.name if asset else task.asset_name,
        "title": task.title,
        "description": task.description,
        "tags": list(task.tags or []),
        "status": status,
        "error": task.error_message or (job.error if job else None),
        "result": job.result if job else {},
        "post": dict(task.post) if task.post else None,
        "job_id": task.job_id,
        "created_at": task.created_at,
    }


def list_tasks(db: Session, workspace_id: str) -> list[PublishTask]:
    return list(
        db.scalars(
            select(PublishTask).where(PublishTask.workspace_id == workspace_id).order_by(PublishTask.created_at.desc())
        )
    )
