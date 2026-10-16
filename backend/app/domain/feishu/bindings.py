"""谁能驱动飞书机器人:一个飞书用户(open_id)绑定到一个 Mosael 成员,机器人就以**那个成员**的身份和
权限行事。绑定靠成员在 Mosael 里自己生成的一次性绑定码(10 分钟有效),发给机器人即完成。

## 认人必须带上「哪台机器人」

飞书的 `open_id` **按应用隔离**(官方《用户身份概述》原话:「不要在跨应用的数据通信中使用
open_id」),所以「发这条消息的人是谁」只有配上机器人(`bot_id` = 哪个飞书应用)才有答案。
这个模块里每一个认人的入口都要求 `bot_id`,一处都不例外 —— 少传一次就是拿 A 应用眼里的 id 去
B 应用里认人,而那正是这条根因:`requester_binding` 取到 A 的 open_id、用 B 的 token 发,飞书直接拒。

说不清归属的老行(`bot_id` 空 + `stale_reason` 非空,见 `migrations._migrate_feishu_bindings_know_their_app`)
**永远不当成有效绑定**:它是「设置页说已绑定、机器人说没绑定」那只错觉的源头,所以照实标出来让人重绑。
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import FeishuBindCode, FeishuBinding, User, WorkspaceMember, now

#: 说不清归属的老行上 `stale_reason` 的取值(稳定 key,出口翻成人话;见 api/routes/feishu)。
STALE_UNKNOWN_APP = "unknown-app"
#: 那台机器人被删了,这一行留着的取值(稳定 key,同上)。删机器人**不级联删绑定**:「谁曾绑过它」
#: 要留着让人看得见、重新绑 —— 而这台应用没了之后,它眼里的那些 open_id 也不再有任何应用解释得了。
STALE_BOT_REMOVED = "bot-removed"


@dataclass(frozen=True)
class Binding:
    """一条绑定在**某台机器人**眼里的样子。`stale_reason` 非空 = 它是说不清归属的老行。"""

    bot_id: str
    open_id: str
    user: User
    stale_reason: str

    @property
    def stale(self) -> bool:
        return bool(self.stale_reason)


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

    `bot_id` 空、或那一行是说不清归属的老行,一律当没绑定 —— 「换过应用之后旧行不许再算数」就落在这里。
    """
    if not bot_id or not open_id:
        return None
    binding = db.get(FeishuBinding, {"workspace_id": workspace_id, "bot_id": bot_id, "open_id": open_id})
    if binding is None or binding.stale_reason or not _is_member(db, workspace_id, binding.user_id):
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
        FeishuBinding(workspace_id=workspace_id, bot_id=bot_id, open_id=open_id, user_id=user_id, stale_reason="")
    )
    db.flush()
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
    row = db.get(FeishuBindCode, {"workspace_id": workspace_id, "code": code})
    if row is None or row.expires_at < now() or not bind_member(db, workspace_id, bot_id, open_id, row.user_id):
        return None
    db.delete(row)
    db.flush()  # 同一个会话里接着认人(resolve_sender)、再兑同一个码,看到的得是兑过之后的样子
    return db.get(User, row.user_id)


def stale_bindings_of_bot(db: Session, workspace_id: str, bot_id: str) -> int:
    """这台机器人被删了:它名下的绑定**不删**,清掉 `bot_id`、标上 `STALE_BOT_REMOVED`。

    级联删掉的话「这个人以前绑过这台」就没有了,而那一行正是要留着让人看得见、重新绑的 ——
    这台应用没了之后,它眼里的那些 open_id 也不再有任何应用能解释(open_id 按应用隔离)。
    返回标了几行。

    主键里有 `bot_id`,所以清空它是一次**改主键**的 UPDATE:同一个人 + 同一串 open_id 要是已经有一条
    说不清归属的老行(`bot_id` 空),两条会撞在同一格主键上 —— 那种情况把老的那条并掉:它本来就是
    「请重新绑」的意思,留下的这条说得更具体(哪台机器人被删了)。
    """
    if not bot_id:
        return 0
    rows = list(
        db.scalars(
            select(FeishuBinding).where(
                FeishuBinding.workspace_id == workspace_id,
                FeishuBinding.bot_id == bot_id,
            )
        )
    )
    for row in rows:
        clash = db.get(FeishuBinding, {"workspace_id": workspace_id, "bot_id": "", "open_id": row.open_id})
        if clash is not None and clash is not row:
            db.delete(clash)
            db.flush()
        row.bot_id = ""
        row.stale_reason = STALE_BOT_REMOVED
    db.flush()
    return len(rows)


def issue_bind_code(db: Session, workspace_id: str, user_id: str) -> tuple[str, datetime]:
    """Member self-issues a one-time code (10-min TTL) to redeem from Feishu."""
    code = secrets.token_hex(3).upper()  # 6 hex chars
    expires = now() + timedelta(minutes=10)
    db.merge(FeishuBindCode(workspace_id=workspace_id, code=code, user_id=user_id, expires_at=expires))
    db.flush()
    return code, expires


def list_bindings(db: Session, workspace_id: str, bot_id: str) -> list[Binding]:
    """这台机器人眼里的绑定,**外加说不清归属的老行**。

    老行(`bot_id` 空)不属于任何一台机器人,但它必须看得见:它是「设置页说已绑定」那只错觉里
    唯一能被人收掉的东西 —— 每一台的面板都列它(标成 stale),也都能删它(见 `remove_binding`)。
    真正的绑定只有 `bot_id` 相等的那一行,所以「面板里显示别的机器人的绑定」这件事不再发生。
    """
    rows = db.execute(
        select(FeishuBinding, User)
        .join(User, User.id == FeishuBinding.user_id)
        .where(
            FeishuBinding.workspace_id == workspace_id,
            FeishuBinding.bot_id.in_([bot_id, ""]),
        )
        .order_by(FeishuBinding.bot_id, FeishuBinding.created_at)
    ).all()
    return [
        Binding(bot_id=row.bot_id, open_id=row.open_id, user=user, stale_reason=row.stale_reason)
        for row, user in rows
    ]


def remove_binding(db: Session, workspace_id: str, bot_id: str, open_id: str) -> None:
    """删掉**这台机器人**的那一行。

    这台机器人名下没有、而工作区里有一条说不清归属的老行时,删掉那条 —— 它没有归属,谁的面板上
    看得见就从哪儿删得掉;别的机器人的行一动不动(那正是此前那个越权面:按工作区删,删掉的是别人的)。
    """
    binding = db.get(FeishuBinding, {"workspace_id": workspace_id, "bot_id": bot_id, "open_id": open_id})
    if binding is None and bot_id:
        binding = db.get(FeishuBinding, {"workspace_id": workspace_id, "bot_id": "", "open_id": open_id})
    if binding is not None:
        db.delete(binding)
