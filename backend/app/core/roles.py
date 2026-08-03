"""工作区的角色阶梯。

    viewer  读内容
    editor  读写内容,可以用智能体
    admin   editor + 改工作区设置、管成员
    owner   admin + 删除/转让工作区

**没有权限位矩阵。** 此前是「四个角色 + 九个权限位 + 每人可覆盖」,删掉后两者的理由(ADR 0008 D4):

  - 身份类资源搬出工作区之后,一半的位没有对应的能力了 —— `credentials` 配的是自己的密钥,
    `publish` 用的是自己的账号,它们不再是"工作区里谁能做什么"。
  - 剩下的位从来没人真的分开配过:`upload / edit / delete / export / schedule` 之间的区分,
    在一个内容工作区里想不出真实场景 —— 能改时间线却不能上传素材,是什么角色?
  - 它还养出了一个恒真条件:editor 默认持有除 `members` 外的全部位,于是实例管理员判据的第二个
    条件永远成立(第 1 步随判据一起清掉了)。

**可逆**:真需要逐位配置时再加回来,那时会有真实用例说清楚要哪几位 —— 而不是先摆一个矩阵在这儿
等人来用。

这个模块是纯逻辑(不碰 DB、不碰 FastAPI),执行在 app/core/permissions.py。
"""
from __future__ import annotations

ROLES = ("owner", "admin", "editor", "viewer")
_RANK = {"viewer": 0, "editor": 1, "admin": 2, "owner": 3}


def role_rank(role: str) -> int:
    return _RANK.get(role, -1)


def role_at_least(role: str, minimum: str) -> bool:
    return role_rank(role) >= role_rank(minimum)
