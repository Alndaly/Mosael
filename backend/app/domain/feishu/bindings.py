"""谁能驱动飞书机器人:一个飞书用户(open_id)绑定到一个 Mosael 成员,机器人就以**那个成员**的身份和
权限行事。绑定靠成员在 Mosael 里自己生成的一次性绑定码(10 分钟有效),发给机器人即完成。

## 认人必须带上「哪台机器人」

飞书的 `open_id` **按应用隔离**(官方《用户身份概述》原话:「不要在跨应用的数据通信中使用
open_id」),所以「发这条消息的人是谁」只有配上机器人(`bot_id` = 哪个飞书应用)才有答案。
这个模块里每一个认人的入口都要求 `bot_id`,一处都不例外 —— 少传一次就是拿 A 应用眼里的 id 去
B 应用里认人,而那正是这条根因:`requester_binding` 取到 A 的 open_id、用 B 的 token 发,飞书直接拒。

「说不清归属」这种行**不存在**:它们属于已经不存在的应用,永远匹配不上任何东西,迁移
(`migrations._migrate_feishu_bindings_drop_stale_rows`)把 `bot_id = ''` 的那些直接删掉了。
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, delete, select
from sqlalchemy.orm import Session

from app.db.models import FeishuBindCode, FeishuBinding, FeishuBot, User, WorkspaceMember, now
from app.domain.collaboration import record_activity

#: 「这条绑定曾经存在过」在审计表里叫什么。**历史**,不是活跃状态(见 `record_removed` / ADR 0070 §9)。
BINDING_REMOVED_ACTION = "feishu.binding.removed"
BINDING_ADDED_ACTION = "feishu.binding.added"
#: 这条历史记的是「哪条绑定」(哪台机器人眼里的哪串 open_id),不是任何一张活跃表的行。
BINDING_SUBJECT_TYPE = "feishu_binding"


@dataclass(frozen=True)
class Binding:
    """一条绑定:某个飞书用户(**在这台机器人眼里的** open_id)绑到一个 Mosael 成员。"""

    bot_id: str
    open_id: str
    user: User


def _is_member(db: Session, workspace_id: str, user_id: str) -> bool:
    return db.get(WorkspaceMember, {"workspace_id": workspace_id, "user_id": user_id}) is not None


def looks_like_code(text: str) -> bool:
    """这段字是不是一张绑定码的样子(去空白、大写之后 4~16 位)。

    兑码和「你发来的这张码不对」那句话共用它 —— 两处各写一遍的话,「什么样的算码」迟早有两个答案。
    """
    code = (text or "").strip().upper()
    return 4 <= len(code) <= 16


def resolve_sender(db: Session, workspace_id: str, bot_id: str, open_id: str) -> User | None:
    """The Mosael account bound to this Feishu sender **as seen by this bot's app** — only if still a member.

    `bot_id` 空一律当没绑定:「这条 open_id 是哪台应用眼里的」答不上来就认不了人,而 open_id 按应用隔离。
    """
    if not bot_id or not open_id:
        return None
    binding = db.get(FeishuBinding, {"workspace_id": workspace_id, "bot_id": bot_id, "open_id": open_id})
    if binding is None or not _is_member(db, workspace_id, binding.user_id):
        return None
    return db.get(User, binding.user_id)


def bind_member(db: Session, workspace_id: str, bot_id: str, open_id: str, user_id: str) -> bool:
    """把 (这台机器人, 这个 open_id) 绑到那个成员上 —— **只在他还在这个工作区里的时候**。

    写绑定的路只有这一处:成员自己兑一张码(`redeem_bind_code`)和「扫码创建完自动绑上发起人」
    (integrations/feishu/onboarding)都走它,键永远是 `(workspace_id, bot_id, open_id)`。
    **不是成员就不绑**:`FeishuBinding.user_id` 指着 `users`,而机器人以这个成员的权限行事 ——
    一个已经不在工作区里的人没有权限可给(和兑码那一侧的判据是同一条)。

    返回"写没写";为什么没写由调用方去说(它知道是缺 open_id、缺发起人,还是那个人已经不在)。
    """
    if not bot_id or not open_id or not user_id:
        return False
    if not _is_member(db, workspace_id, user_id):
        return False
    db.merge(
        FeishuBinding(workspace_id=workspace_id, bot_id=bot_id, open_id=open_id, user_id=user_id)
    )
    db.flush()
    bot = db.get(FeishuBot, bot_id)
    record_activity(
        db,
        workspace_id=workspace_id,
        actor_id=user_id,
        action=BINDING_ADDED_ACTION,
        subject_type=BINDING_SUBJECT_TYPE,
        subject_id=bot_id,
        summary="绑定了飞书机器人",
        payload={
            "bot_id": bot_id,
            "app_id": bot.app_id if bot is not None else "",
            "bot_name": bot.name if bot is not None else "",
            "open_id": open_id,
        },
    )
    return True


def redeem_bind_code(db: Session, workspace_id: str, bot_id: str, open_id: str, text: str) -> User | None:
    """If `text` is a live bind code for this workspace, bind (bot_id, open_id) → its issuer and consume it.

    码本身是**工作区**级的一次性凭证(证明「我是那个成员」);落成的那一行记的是**收到这条消息的那台
    机器人**眼里的 open_id —— 换一台机器人发同一个码,绑的是那台机器人眼里的身份,两行各归各的。
    落行走 `bind_member`,和「建完自动绑」是同一处。
    """
    if not bot_id:
        return None
    code = (text or "").strip().upper()
    if not looks_like_code(code):
        return None
    # 先删掉再绑:DELETE 是这次兑换的 CAS。两个人同时拿同一个码时只有一个 DELETE 拿到
    # user_id,另一个看到空 —— 不会两个 open_id 都绑到同一个成员上。
    user_id = db.execute(
        delete(FeishuBindCode)
        .where(
            FeishuBindCode.workspace_id == workspace_id,
            FeishuBindCode.code == code,
            FeishuBindCode.expires_at >= now(),
        )
        .returning(FeishuBindCode.user_id)
    ).scalar_one_or_none()
    if user_id is None:
        return None
    if not bind_member(db, workspace_id, bot_id, open_id, user_id):
        return None
    db.flush()  # 同一个会话里接着认人(resolve_sender),看到的得是兑过之后的样子
    return db.get(User, user_id)


def issue_bind_code(db: Session, workspace_id: str, user_id: str) -> tuple[str, datetime]:
    """Member self-issues a one-time code (10-min TTL) to redeem from Feishu."""
    code = secrets.token_hex(4).upper()  # 8 hex chars = 32 bit
    expires = now() + timedelta(minutes=10)
    db.merge(FeishuBindCode(workspace_id=workspace_id, code=code, user_id=user_id, expires_at=expires))
    db.flush()
    return code, expires


def list_bindings(db: Session, workspace_id: str, bot_id: str) -> list[Binding]:
    """**这台机器人**眼里的、当前仍是工作区成员的绑定。

    `resolve_sender` 认人时会再查一次成员资格;面板若只 join User,会把已经被移出工作区的人
    继续列成“已绑定”,和机器人实际拒绝他相矛盾。这里直接把成员表 join 进来。
    """
    rows = db.execute(
        select(FeishuBinding, User)
        .join(User, User.id == FeishuBinding.user_id)
        .join(
            WorkspaceMember,
            and_(
                WorkspaceMember.workspace_id == FeishuBinding.workspace_id,
                WorkspaceMember.user_id == FeishuBinding.user_id,
            ),
        )
        .where(
            FeishuBinding.workspace_id == workspace_id,
            FeishuBinding.bot_id == bot_id,
        )
        .order_by(FeishuBinding.created_at)
    ).all()
    return [
        Binding(bot_id=row.bot_id, open_id=row.open_id, user=user)
        for row, user in rows
    ]


def remove_binding(db: Session, workspace_id: str, bot_id: str, open_id: str) -> None:
    """删掉**这台机器人**的那一行。别的机器人的行一动不动(那正是此前那个越权面:按工作区删,删掉的是别人的)。

    删之前先记一条历史(`feishu.binding.removed`):解绑之后,「这个人以前绑过这台」在活跃表里
    就没有痕迹了(那张表只管现状)。记法与理由见 `record_removed` 与 ADR 0070 §9。
    """
    binding = db.get(FeishuBinding, {"workspace_id": workspace_id, "bot_id": bot_id, "open_id": open_id})
    if binding is None:
        return
    bot = db.get(FeishuBot, bot_id)
    record_removed(
        db,
        workspace_id=workspace_id,
        bot_id=bot_id,
        open_id=binding.open_id,
        user_id=binding.user_id,
        app_id=bot.app_id if bot is not None else "",
        bot_name=bot.name if bot is not None else "",
    )
    db.delete(binding)


def record_removed(
    db: Session,
    *,
    workspace_id: str,
    bot_id: str,
    open_id: str,
    user_id: str,
    app_id: str = "",
    bot_name: str = "",
    whole_bot: bool = False,
) -> None:
    """把「这条绑定曾经存在过」记进审计表(`activity_events`,见 `domain/collaboration.record_activity`)。

    **它是历史,不是活跃状态。** `feishu_bindings` 是**活跃**表,`bot_id` 上挂着 `ON DELETE CASCADE`
    —— 机器人一删,它名下的行必须跟着走(那台应用眼里的 open_id 之后没有任何东西解释得了)。
    而"谁曾绑过"要留得下来,就只能落在另一张表上:这条记录不指向 `feishu_bots`(`subject_id` 只是
    一段字符串),所以机器人那一行没了,痕迹照样在。

    **它不参与授权。** 认人(`resolve_sender`)和面板(`list_bindings`)只读**活跃**表;这条记录只
    出现在工作区动态流(`collaboration.list_activity`)那条读路径里 —— 没有任何"从历史推出现在谁能
    驱动机器人"的判断。

    **形状**(照 ADR 0070 §9):
    - `action=BINDING_REMOVED_ACTION`、`subject_type=BINDING_SUBJECT_TYPE`;
    - `subject_id` 只放 `bot_id` —— 模型上它是 `String(64)`,而 `bot_id`(32 位 hex)拼上
      `open_id`(真实值约 35 字符)会顶到 80 左右,超了那一列的边界;所以 `open_id` 进 `payload`;
    - `payload` 四格:`bot_id` / `app_id` / `bot_name` / `open_id` —— 机器人删了之后,
      光有 id 认不出那台应用是谁,`app_id` 与 `bot_name` 是留给读的人的那一半;
    - `actor_id` 是**曾经被绑的那个成员**(`FeishuBinding.user_id`):这条历史的主题是"他绑过这台",
      而 `actor_id` 是 `users.id` 上的 `SET NULL` —— 人走了,痕迹还在。

    不提交:随调用方那个事务落库(解绑的路由 / 删机器人都是各自一个事务)。
    """
    record_activity(
        db,
        workspace_id=workspace_id,
        actor_id=user_id,
        action=BINDING_REMOVED_ACTION,
        subject_type=BINDING_SUBJECT_TYPE,
        subject_id=bot_id,
        summary="删除了飞书机器人,它名下的绑定随之解除" if whole_bot else "解除了飞书绑定",
        payload={"bot_id": bot_id, "app_id": app_id, "bot_name": bot_name, "open_id": open_id},
    )
