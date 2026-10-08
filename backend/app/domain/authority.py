"""一次运行替谁用私有的东西:**点运行的人**,以及**被执行的那一版图是谁写的**。

此前特权检查只看运行的 actor(手动运行是点运行的人,定时任务 / webhook 是任务主人)。可工作流是
工作区内容、同事能改:同事改了主人的图,主人的定时任务到点一跑,那次运行就以主人的授权,用主人的
私有发布账号、浏览器档案、本机文件 —— §3.6 挡住了「以自己的身份用别人的」,没挡住「借别人的任务
用别人的」。

所以一次运行的权限是两半的**交集**:

- `actor`:谁在跑(和以前一样);
- `vouchers`:这次执行到的每一版图(含被 `call_workflow` 调起的子流程各自那一版),各有一组
  **担保人** —— 保存这一版的人(`WorkflowRevision.created_by`),加上事后「认可这一版」的人。
  每一版都得有**至少一个**担保人自己也过得了这道检查。

图没变、人没变的时候两半是同一个人,单机用时永远是同一个人 —— 零摩擦。同事改过的那一版,要等主人
点一次「认可这一版」(见 workflows.revisions.attest_revision)才借得到主人的东西。

这里只放**判据的形状**,不认识任何具体资源:发布账号 / 浏览器档案(domain/sharing)和本机文件
(domain/host_files)把自己的「这个人行不行」交给 `ensure`,各自说各自的报错。

**花某人的钱也是借用**(ADR 0047):AI 供应商连接、插件连接都归人,用它就是花主人的钥匙和额度。
一次运行要用属于某人的连接时,被执行的每一版图都得有**这条连接的主人**做担保人(`ensure_vouched_to_spend`)。
连接解析散在生成、对话、配音、翻译、插件调用各处,离工作流执行器隔着好几层(生成任务是工作流任务的子任务),
所以这道闸不靠调用方把授权一路传下去,而是自己从任务上下文里取「这次运行的授权」—— 那是沿任务父链收集的
(workflows.authority.current_authority)。供应商、插件两个域不认识工作流(工作流依赖它们),由组装根把
取授权的函数交进来(`use_run_authority`,见 app.main._wire_seams)。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.core.i18n import LocalizedError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass(frozen=True)
class Voucher:
    """被执行的一版图,以及谁为它担保(作者 + 认可过它的人)。"""

    workflow_id: str
    workflow_name: str
    revision: int
    users: frozenset[str] = field(default_factory=frozenset)

    def attest_details(self) -> dict[str, dict[str, object]]:
        """报错带给界面的那一份:哪条工作流的哪一版等人认可(见前端「认可这一版」)。"""
        return {"attest": {"workflow_id": self.workflow_id, "workflow_name": self.workflow_name, "revision": self.revision}}


@dataclass(frozen=True)
class Authority:
    """一次运行的全部授权:谁在跑,加上被执行的每一版图由谁担保。"""

    actor: str | None
    vouchers: tuple[Voucher, ...] = ()


#: 闸门的 `actor` 参数收的东西。HTTP 路由、确认卡传一个用户 id(只有一个人,没有图);
#: 工作流执行器传 `Authority`(见 workflows.authority.current_authority)。
Actor = str | Authority | None


def as_authority(actor: Actor) -> Authority:
    return actor if isinstance(actor, Authority) else Authority(actor=actor or None)


def actor_id(actor: Actor) -> str | None:
    return as_authority(actor).actor


def ensure(
    actor: Actor,
    allowed: Callable[[str | None], bool],
    *,
    denied: Callable[[], Exception],
    unvouched: Callable[[Voucher], Exception],
) -> None:
    """跑的人要过,每一版图也要有一个担保人过。

    先判跑的人:他自己都用不了的,说「你用不了」比说「这一版需要认可」更对 —— 认可救不了他。
    """
    authority = as_authority(actor)
    if not allowed(authority.actor):
        raise denied()
    for voucher in authority.vouchers:
        if not any(allowed(user) for user in voucher.users):
            raise unvouched(voucher)


# ---------------- 花某人的钱(ADR 0047) ----------------


class SpendNotVouched(LocalizedError, PermissionError):
    """这次运行要用 `connection`(属于某人的 AI 供应商连接 / 插件连接),而被执行的某一版图既不是连接的主人存的,
    他也没认可过。`details["attest"]` 说是哪条工作流的哪一版(界面据此给「认可这一版」)。"""

    def __init__(self, voucher: Voucher, *, connection: str) -> None:
        super().__init__(
            "spendErr_notVouched", workflow=voucher.workflow_name, revision=voucher.revision, connection=connection
        )
        self.details = voucher.attest_details()


def _outside_any_run(_db: Session) -> Authority:
    return Authority(actor=None)


#: 「此刻这次运行的授权」从哪儿来。组装根接上 workflows.authority.current_authority;没接上时(只 import 了
#: 领域的脚本)当作不在任何运行里。棘轮:tests/test_scheduled_runs_need_a_voucher_to_spend.py 看着它接上了。
_run_authority: Callable[[Session], Authority] = _outside_any_run


def use_run_authority(provider: Callable[[Session], Authority]) -> None:
    """组装根调一次(见 app.main._wire_seams)。"""
    global _run_authority
    _run_authority = provider


def ensure_vouched_to_spend(db: Session, owner: str | None, *, connection: str) -> None:
    """这次运行要花 `owner` 的东西(他的连接、钥匙、额度):被执行的每一版图都要有他做担保人,否则抛 `SpendNotVouched`。

    `owner` 为空的连接不属于任何人(没有谁的钱可花),不判。不在运行里(接口请求、单独的生成任务)没有图,也不判 ——
    那时只剩「跑的人是不是主人」,由解析连接的地方自己判(见 providers.credentials.resolve_connection)。
    """
    if not owner:
        return
    for voucher in _run_authority(db).vouchers:
        if owner not in voucher.users:
            raise SpendNotVouched(voucher, connection=connection)
