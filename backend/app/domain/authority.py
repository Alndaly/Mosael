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
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


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
