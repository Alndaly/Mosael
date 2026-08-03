"""角色阶梯的纯逻辑。

此前这个文件还测「权限位默认值」「每人覆盖」「owner 忽略覆盖」—— 那套矩阵在 ADR 0008 D4 里退场了
(理由见 app/core/roles.py 的模块说明)。**行为层面的覆盖没有变薄**:四个角色各自能做什么,现在由
tests/test_roles_are_permissions.py 端到端地钉,那比断言一张字典更接近用户会撞到的东西。
"""

from __future__ import annotations

from app.core.roles import ROLES, role_at_least, role_rank


def test_role_ladder() -> None:
    assert role_rank("owner") > role_rank("admin") > role_rank("editor") > role_rank("viewer")
    assert role_at_least("admin", "editor")
    assert not role_at_least("editor", "admin")


def test_an_unknown_role_is_below_everything() -> None:
    """认不出来的角色一律当成最低 —— 库里被改坏时应当更严,不是更松。"""
    assert role_rank("wat") < role_rank("viewer")
    assert not role_at_least("wat", "viewer")


def test_the_ladder_is_the_whole_model() -> None:
    assert ROLES == ("owner", "admin", "editor", "viewer")
