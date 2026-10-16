"""飞书收件人:节点上怎么写、运行时解到哪。

## 一份解析,两族节点共用

"发到哪"此前只有一处实现(`integrations/feishu/approvals.route_for_approval`),而且是**自动猜**的:
这次运行来自飞书会话就发回那个会话,否则看发起人绑没绑 —— 节点上既看不见也改不了。
现在节点上写(`channel` / `bot` / `to`),解析落在**领域**这一处:「等人确认」(`await_approval`)
和 4 个飞书能力节点共用它。各写一套的话,同一个写法迟早给出发给谁的两个答案。

## 几档写法

- `origin`(**缺省**):哪来发回哪 —— 这次运行的任务载荷里那份回执指着一次 `origin="feishu"` 的
  智能体会话,消息就发回那个会话(`AgentSession.external_key` 是 `feishu:<bot_id>:<chat_id>`)。
  这一档就是此前那条"先近"的路:旧的图(节点上没写那三格)行为不变。
- `user`:私聊一个**已绑定**的人(`to` 是那个人的 open_id)。
- `chat`:`to` 是一个群 id(`oc_…`)。
- `raw`:手填收件 id 与类型 —— 给"机器人看得见、但不在下拉里"的那种 id 留的口子。
- `none`:**只站内**,一个字都不发飞书。这是"这次不通知飞书"的**明确选择**,不是"发不出去就算了"。

解析不出来时给一个说得清的 `reason`,调用方据此决定是**降级**(「等人确认」退回站内那条路)
还是**失败**(「发飞书消息」这种节点整个存在的意义就是发出去)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AgentSession, FeishuBinding, FeishuBot

ORIGIN = "origin"
USER = "user"
CHAT = "chat"
RAW = "raw"
NONE = "none"

#: 「等人确认」的 `channel` 能写的值:那个门可以"只站内",但没有"手填一个收件 id"的场景
#: (它发的是一张带按钮的卡,收件人得是应用认得出的会话或人)。
APPROVAL_CHANNELS = (ORIGIN, USER, CHAT, NONE)
#: 「发飞书消息」多一个 `raw`。
MESSAGE_CHANNELS = (ORIGIN, USER, CHAT, RAW)

#: 收件 id 的类型(飞书 `receive_id_type` 认的那两个)。
RAW_TYPES = ("chat_id", "open_id")

#: 每一档解出来的收件 id 是哪一种。
_TYPE_BY_CHANNEL = {USER: "open_id", CHAT: "chat_id"}


def _pick(config: dict[str, Any], key: str, allowed: tuple[str, ...], fallback: str) -> str:
    value = str((config or {}).get(key) or "").strip()
    return value if value in allowed else fallback


def channel_of(config: dict[str, Any], *, allowed: tuple[str, ...] = MESSAGE_CHANNELS, fallback: str = ORIGIN) -> str:
    """节点上写的通知方式。没写 = `origin`(和此前的自动路由一致),认不出的也回缺省。"""
    return _pick(config, "channel", allowed, fallback)


def bot_id_of(config: dict[str, Any]) -> str:
    """点名用哪个机器人;空 = 走自动挑选(工作区里最早启用的那个)。"""
    return str((config or {}).get("bot") or "").strip()


def to_of(config: dict[str, Any]) -> str:
    return str((config or {}).get("to") or "").strip()


def raw_type_of(config: dict[str, Any]) -> str:
    return _pick(config, "raw_type", RAW_TYPES, "chat_id")


def requester_binding(db: Session, workspace_id: str, user_id: str | None, bot_id: str = "") -> tuple[FeishuBot, str] | None:
    """发起这次运行的人在这个工作区绑过飞书吗:(机器人, 他的 open_id);没有就 None。

    这是 `origin` 那一档**第二条**路(不是从飞书会话来的,但发起人绑过账号 —— 私聊他),
    也是此前 `bot_for_user` 干的那件事;`bot` 那一格照样说得上话。
    """
    if not user_id:
        return None
    bot = pick_bot(db, workspace_id, bot_id)
    if bot is None:
        return None
    open_id = db.scalar(
        select(FeishuBinding.open_id).where(
            FeishuBinding.workspace_id == workspace_id, FeishuBinding.user_id == user_id
        )
    )
    return (bot, open_id) if open_id else None


def session_origin(db: Session, session_id: str | None) -> tuple[FeishuBot, str] | None:
    """这一次运行是从哪个飞书会话来的:(机器人, 会话 id)。

    路由信息全在 `AgentSession.external_key` 里(`feishu:<bot_id>:<chat_id>`,见
    get_or_create_external_session 的调用处),所以哪个单都不用为此加列。
    """
    if not session_id:
        return None
    session = db.get(AgentSession, session_id)
    if session is None or session.origin != "feishu" or not session.external_key:
        return None
    parts = session.external_key.split(":", 2)
    if len(parts) != 3 or parts[0] != "feishu":
        return None
    bot = db.get(FeishuBot, parts[1])
    return (bot, parts[2]) if bot is not None else None


def run_origin(db: Session, job: Any) -> tuple[FeishuBot, str] | None:
    """这次运行来自哪个飞书会话:任务载荷里那份回执指着一次 `origin="feishu"` 的智能体会话。"""
    receipt = (getattr(job, "payload", None) or {}).get("receipt")
    if not isinstance(receipt, dict):
        return None
    return session_origin(db, str(receipt.get("session_id") or ""))


def pick_bot(db: Session, workspace_id: str, bot_id: str = "") -> FeishuBot | None:
    """这次用哪个机器人发。

    点名的那个必须**在这个工作区里**(工作区就是这道边界:拿别的工作区的机器人 id 发不出去);
    没点名时挑最早启用的那个 —— 和此前 `bot_for_user` 的挑法逐字一致,旧的图行为不变。
    点名一个**停用**的机器人仍然照发:那个开关管的是长连接(收消息),不拦出站的 REST。
    """
    wanted = str(bot_id or "").strip()
    if wanted:
        bot = db.get(FeishuBot, wanted)
        return bot if bot is not None and bot.workspace_id == workspace_id else None
    return db.scalar(
        select(FeishuBot)
        .where(FeishuBot.workspace_id == workspace_id, FeishuBot.enabled.is_(True))
        .order_by(FeishuBot.created_at)
    )


def enabled_bots(db: Session, workspace_id: str) -> list[FeishuBot]:
    """这个工作区里启用的机器人,按创建时间(和 pick_bot 的自动挑选同序)。"""
    return list(
        db.scalars(
            select(FeishuBot)
            .where(FeishuBot.workspace_id == workspace_id, FeishuBot.enabled.is_(True))
            .order_by(FeishuBot.created_at)
        )
    )


@dataclass(frozen=True)
class Target:
    """"发到哪"解出来的那一份:哪个机器人、发给谁、那个 id 是哪一种。"""

    bot: FeishuBot
    receive_id: str
    receive_type: str


@dataclass(frozen=True)
class Resolution:
    """解析的结果:`target` 是解出来的,`reason` 是这一档 / 解不出来的原因。

    解不出来**不是错误**:「等人确认」遇到它就退回站内那条路(照旧在等),「发飞书消息」遇到它当场失败。
    两种取舍由调用方定,这一处只把"为什么"说清楚。
    """

    target: Target | None
    reason: str

    @property
    def ok(self) -> bool:
        return self.target is not None


def _failed(reason: str) -> Resolution:
    return Resolution(target=None, reason=reason)


def resolve(
    db: Session,
    *,
    workspace_id: str,
    channel: str,
    bot_id: str = "",
    to: str = "",
    raw_type: str = "chat_id",
    job: Any = None,
) -> Resolution:
    """按节点上写的解出"发到哪"。解不出来时 `reason` 说清是哪一种(见模块说明)。

    `to` 就是那个收件 id:`channel=user` 时是人的 open_id、`chat` 时是群 id、`raw` 时是手填的那个
    (调用方把节点上 `raw_id` 那一格传进来 —— 写法不同,解的地方是同一处)。
    """
    channel = str(channel or "").strip() or ORIGIN
    if channel == NONE:
        return _failed(NONE)
    if channel == ORIGIN:
        origin = run_origin(db, job)
        if origin is not None:
            bot, chat_id = origin
            return Resolution(target=Target(bot=bot, receive_id=chat_id, receive_type="chat_id"), reason=ORIGIN)
        #: 不是从飞书来的:退到"发起人绑过飞书就私聊他"—— 这正是此前那条"先近后远"的第二条,
        #: 所以旧的图(节点上没写那三格)行为不变。
        requester = getattr(job, "created_by", None) if job is not None else None
        dm = requester_binding(db, workspace_id, requester, bot_id)
        if dm is None:
            return _failed("no-origin")
        bot, open_id = dm
        return Resolution(target=Target(bot=bot, receive_id=open_id, receive_type="open_id"), reason=ORIGIN)

    target_id = str(to or "").strip()
    if channel == RAW:
        receive_type = str(raw_type or "").strip()
        if not target_id or receive_type not in RAW_TYPES:
            return _failed("no-target")
    else:
        if not target_id:
            return _failed("no-target")
        receive_type = _TYPE_BY_CHANNEL[channel]
    bot = pick_bot(db, workspace_id, bot_id)
    if bot is None:
        return _failed("no-bot")
    if channel == USER and not _is_bound(db, workspace_id, target_id):
        #: `channel=user` 的契约是"一个**已绑定**的人":没绑过的 open_id 不猜着发。
        #: 要发一个任意 id 是 `raw` 那一档的事 —— 那一档明确说了"机器人看得见的都行"。
        return _failed("not-bound")
    return Resolution(target=Target(bot=bot, receive_id=target_id, receive_type=receive_type), reason=channel)


def _is_bound(db: Session, workspace_id: str, open_id: str) -> bool:
    return (
        db.scalar(
            select(FeishuBinding.open_id).where(
                FeishuBinding.workspace_id == workspace_id, FeishuBinding.open_id == open_id
            )
        )
        is not None
    )
