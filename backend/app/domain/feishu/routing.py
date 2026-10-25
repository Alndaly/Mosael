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
- `user`:私聊一个**已绑定**的人(`to` 是那个人的 open_id)。**「已绑定」是就这次用的那台机器人而言**
  —— open_id 按飞书应用隔离,别的机器人眼里的那串 id 在这台里认不出来,也不该拿去发。
- `chat`:`to` 是一个群 id(`oc_…`)。
- `raw`:手填收件 id 与类型 —— 给"机器人看得见、但不在下拉里"的那种 id 留的口子。
  类型**按 id 前缀判**(`oc_` 是群、`ou_` 是人),那一格写的名字要和它对得上。
- `none`:**只站内**,一个字都不发飞书。这是"这次不通知飞书"的**明确选择**,不是"发不出去就算了"。

解析不出来时给一个说得清的 `reason`,调用方据此决定是**降级**(「等人确认」退回站内那条路)
还是**失败**(「发飞书消息」这种节点整个存在的意义就是发出去)。

**认不出的写法不猜。** 不在白名单里的 `channel`、认不出前缀的 `raw_id`、和前缀对不上的
`raw_type`,都当场带着 key 抛出(`LocalizedError`,由调用方翻成它那一层的错误)——
此前它们各自悄悄退回 `origin` / `chat_id`,于是"本该不发飞书"的图发给了发起人、手填错的 id
要等飞书回一句英文报错。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
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

#: 手填的收件 id 长什么样 → 它是哪一种。**前缀是飞书真正校验的那一半**:`oc_` 是群,`ou_` 是人。
_RAW_TYPE_BY_PREFIX = {"oc_": "chat_id", "ou_": "open_id"}


def channel_of(
    config: dict[str, Any],
    *,
    allowed: tuple[str, ...] = MESSAGE_CHANNELS,
    fallback: str = ORIGIN,
    strict: bool,
) -> str:
    """节点上写的通知方式。**没写** = `fallback`(和此前的自动路由一致),**认不出**就当场说清。

    `strict` **没有缺省**:认不出的写法是"当场失败"还是"退回 `fallback`",是**每条路自己的**
    取舍,而这一格就是那个取舍 —— 所以两个调用方各自显式表态,不许谁替谁默认:

    - 「发飞书消息」那类**必须发出去**的节点传 `True`(见 domain/workflows/executors/feishu):
      手改 / 迁移来的图里一个写作 `chatroom` 的值,此前悄悄退回 `origin` —— 而"回 origin"意味着
      发给发起人。这是一条会把话交给错的人的兜底,所以宁可失败。
    - 「等人确认」传 `False`(见 integrations/feishu/approvals):它遇到发不出去**可以退回站内**,
      那条路的降级语义是它自己的,不因为这一处改动换默认行为。

    此前这一格缺省为假,而那个缺省值的存在只是因为「等人确认」要保持旧的降级语义 ——
    于是"发飞书消息"那条路是不是严格,取决于它记不记得多传一个字。现在少传就是 `TypeError`。
    """
    value = str((config or {}).get("channel") or "").strip()
    if not value:
        return fallback
    if value in allowed:
        return value
    if strict:
        raise LocalizedError("wfErr_feishuUnknownChannel", value=value, choices=" / ".join(allowed))
    return fallback


def bot_id_of(config: dict[str, Any]) -> str:
    """点名用哪个机器人;空 = 走自动挑选(工作区里最早启用的那个)。"""
    return str((config or {}).get("bot") or "").strip()


def to_of(config: dict[str, Any]) -> str:
    return str((config or {}).get("to") or "").strip()


def raw_type_of(config: dict[str, Any]) -> str:
    """手填的收件 id 是哪一种 —— **按前缀判**(`oc_` 是群、`ou_` 是人),那一格写的名字要和它对上。

    此前认不出就回 `chat_id`:填错的 id 要等飞书回一句英文报错,而"发给一个群"和"发给一个人"
    错一次就是把话交给了错的对象。空 id 是另一件事(没填收件人),回空串让 `resolve` 照旧说
    `no-target`。
    """
    raw = config or {}
    return _raw_type(str(raw.get("raw_id") or "").strip(), str(raw.get("raw_type") or "").strip())


def _raw_type(raw_id: str, declared: str) -> str:
    """手填的收件 id + 那一格写的类型 → 类型。认不出前缀、或两者对不上,都带 key 抛(见模块说明)。

    它同时被 `raw_type_of`(读节点上那两格)和 `resolve`(别的调用方直接给 id)用 ——
    "哪种 id 算哪种类型"只有这一处答案。
    """
    if not raw_id:
        return ""
    kind = next((one for prefix, one in _RAW_TYPE_BY_PREFIX.items() if raw_id.startswith(prefix)), "")
    if not kind:
        raise LocalizedError("wfErr_feishuRawId", value=raw_id, types=" / ".join(RAW_TYPES))
    if declared and declared != kind:
        raise LocalizedError(
            "wfErr_feishuRawType", value=raw_id, declared=declared, actual=kind, types=" / ".join(RAW_TYPES)
        )
    return kind


def requester_binding(db: Session, workspace_id: str, user_id: str | None, bot_id: str = "") -> tuple[FeishuBot, str] | None:
    """发起这次运行的人绑过飞书吗:(机器人, **那台机器人眼里的**他);没有就 None。

    这是 `origin` 那一档**第二条**路(不是从飞书会话来的,但发起人绑过账号 —— 私聊他),
    也是此前 `bot_for_user` 干的那件事;`bot` 那一格照样说得上话。

    **两个值必须来自同一行绑定**:`open_id` 按应用隔离,先挑机器人再拿"某个工作区里的
    open_id"就是拿 A 的 id 用 B 的 token 发 —— 飞书直接拒(这条根因的第三个后果)。
    点名了机器人就用它的那一行;没点名时挑**他绑过的那台**(启用中、创建时间最早的那个)——
    此前是没有 app 维度也没有 ORDER BY,取哪条由存储顺序定。
    """
    if not user_id:
        return None
    wanted = str(bot_id or "").strip()
    if wanted:
        bot = pick_bot(db, workspace_id, wanted)
        if bot is None:
            return None
        open_id = _bound_open_id(db, workspace_id, bot.id, user_id)
        return (bot, open_id) if open_id else None
    row = db.execute(
        select(FeishuBot, FeishuBinding.open_id)
        .join(FeishuBinding, FeishuBinding.bot_id == FeishuBot.id)
        .where(
            FeishuBot.workspace_id == workspace_id,
            FeishuBot.enabled.is_(True),
            FeishuBinding.workspace_id == workspace_id,
            FeishuBinding.user_id == user_id,
        )
        .order_by(FeishuBot.created_at)
    ).first()
    return (row[0], row[1]) if row is not None else None


def _bound_open_id(db: Session, workspace_id: str, bot_id: str, user_id: str) -> str:
    """这个成员在这台机器人眼里的 open_id。同一个人在同一台机器人上绑过不止一个飞书身份时,
    取**最近绑的那个** —— 此前没有 ORDER BY,取哪条由存储顺序定。"""
    return db.scalar(
        select(FeishuBinding.open_id)
        .where(
            FeishuBinding.workspace_id == workspace_id,
            FeishuBinding.bot_id == bot_id,
            FeishuBinding.user_id == user_id,
        )
        .order_by(FeishuBinding.created_at.desc())
    ) or ""


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
    """这次运行来自哪个飞书会话。

    两条来源:触发器在起跑时就把 `(bot_id, chat_id)` 写进任务载荷;普通智能体发起的运行则
    从回执指向的 `origin="feishu"` 会话解。触发器那条**不能**靠回执 —— trigger job 没有
    `AgentSession`,否则 `channel=origin` 会退到 owner 私聊。
    """
    payload = getattr(job, "payload", None) or {}
    trigger_bot_id = str(payload.get("trigger_bot_id") or "").strip()
    trigger_chat_id = str(payload.get("trigger_chat_id") or "").strip()
    if trigger_bot_id and trigger_chat_id:
        bot = db.get(FeishuBot, trigger_bot_id)
        if bot is not None and bot.workspace_id == getattr(job, "workspace_id", ""):
            return bot, trigger_chat_id
    receipt = payload.get("receipt")
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
    (调用方把节点上 `raw_id` 那一格传进来 —— 写法不同,解的地方是同一处)。**认不出的写法不是
    "解不出来"**:那几种带 key 抛出,因为"没填收件人"和"写了一个不存在的档位"是两件事。
    """
    channel = str(channel or "").strip() or ORIGIN
    if channel not in (ORIGIN, NONE, USER, CHAT, RAW):
        raise LocalizedError("wfErr_feishuUnknownChannel", value=channel, choices=" / ".join(MESSAGE_CHANNELS))
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
        #: 类型按 id 前缀判(见 _raw_type):认不出前缀、或和那一格写的名字对不上,都在这里说清。
        receive_type = _raw_type(target_id, str(raw_type or "").strip())
        if not target_id or receive_type not in RAW_TYPES:
            return _failed("no-target")
    else:
        if not target_id:
            return _failed("no-target")
        receive_type = _TYPE_BY_CHANNEL[channel]
    bot = pick_bot(db, workspace_id, bot_id)
    if bot is None:
        return _failed("no-bot")
    if channel == USER and not _is_bound(db, workspace_id, bot.id, target_id):
        #: `channel=user` 的契约是"一个**在这台机器人眼里已绑定**的人":没绑过的 open_id 不猜着发。
        #: 要发一个任意 id 是 `raw` 那一档的事 —— 那一档明确说了"机器人看得见的都行"。
        return _failed("not-bound")
    return Resolution(target=Target(bot=bot, receive_id=target_id, receive_type=receive_type), reason=channel)


def _is_bound(db: Session, workspace_id: str, bot_id: str, open_id: str) -> bool:
    """这个人**在这台机器人(这个应用)眼里**绑过没有。答不上「哪台机器人」就不算绑定。"""
    if not bot_id:
        return False
    return (
        db.scalar(
            select(FeishuBinding.open_id).where(
                FeishuBinding.workspace_id == workspace_id,
                FeishuBinding.bot_id == bot_id,
                FeishuBinding.open_id == open_id,
            )
        )
        is not None
    )
