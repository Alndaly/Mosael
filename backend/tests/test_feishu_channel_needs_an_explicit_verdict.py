"""`routing.channel_of` 的 `strict` **没有缺省**:两条路各自表态。

这个参数定的是「认不出的 `channel` 当场失败,还是退回 `fallback`」——而退回 `origin` 意味着
**把话发给发起人**。两条路的取舍本来就不同:

- 「发飞书消息」那类节点必须发出去 → `strict=True`(宁可失败,不把话交给错的人);
- 「等人确认」遇到发不出去可以退回站内 → `strict=False`(那条降级语义是它自己的)。

此前是 `strict: bool = False` —— 那个缺省值的存在只是因为「等人确认」要保持旧语义,于是
「发飞书消息」严不严格,取决于它记不记得多传一个字。现在少传就是 `TypeError`,而两个调用方
各自在源码里写着传的是哪一档。
"""

from __future__ import annotations

import inspect

import pytest

from app.domain.feishu import routing
from app.domain.workflows.executors import feishu as executors
from app.integrations.feishu import approvals
from tests.util import executable_source


def test_strict没有缺省_少传就是TypeError() -> None:
    """签名上它必须是一个**必须显式给**的关键字参数(形状,不是行为)。"""
    parameter = inspect.signature(routing.channel_of).parameters["strict"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, parameter.kind
    assert parameter.default is inspect.Parameter.empty, (
        "strict 又有缺省了 —— 那个缺省值只能是某一条路的取舍,而它会静默变成另一条路的"
    )

    with pytest.raises(TypeError):
        routing.channel_of({"channel": "chatroom"})  # 少传一个必给的参数:当场炸,不是默默退回 origin


def test_两条路各自说了自己那一档() -> None:
    """两处调用点都在源码里写着传的是什么 —— 谁也没接住别处的缺省。"""
    assert "strict=True" in executable_source(executors), "「发飞书消息」那条路必须明说它要严格"
    assert "strict=False" in executable_source(approvals), (
        "「等人确认」那条路必须明说它的降级语义(而不是靠一个缺省值)"
    )
