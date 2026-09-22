"""「能对时间线做什么」只有**一份**数据,而且它说的是实话。

## 现场

`EDIT_OP_KINDS` 的注释写着:

> **这是「能对时间线做什么」的清单**,不是某一个界面的清单 —— 智能体的 `edit_timeline`、
> 工作流的时间线节点、将来任何别的入口,认的都是这一份。

而它当时有 **10** 项,同一个文件里的变更操作有 **28** 个。缺席的包括 `set_clip_speed`、
`set_clip_gain`、`split_clip`、`set_clip_text`、`set_subtitle_style`、`ripple_delete_clip`、
`set_sequence_reframe`…… 于是"把这段调成 1.5 倍速"、"把这条字幕的样式改一下"在对话里和
工作流里都**做不到** —— 而领域层做得到。

**缺席的表现是功能缺失,不是报错**:用户只会觉得"智能体不会调速",不会觉得这里有一处断链。

而且清单和派发是两份手写的元组与 `if/elif`,恰好对得上,没有任何东西比对它们 ——
加一项忘了另一边:加在元组里 → 运行时"不认识的时间线操作";加在派发里 → 校验先把它拦掉。
这正是"两个数碰巧相等,所以一直没人发现"那个形状。

现在派发表是唯一那份数据,`EDIT_OP_KINDS` 从它算出来,**两者不可能漂**。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import inspect

import pytest

from app.domain.sequences import operations as ops


def test_清单从派发表算出来_不是第二份手写() -> None:
    assert ops.EDIT_OP_KINDS == tuple(ops._EDIT_OPS), "又变回两份手写了"
    source = inspect.getsource(ops.apply_edit_operations)
    assert 'elif kind == "' not in source, "派发又长回一串 if/elif 了 —— 那就是第二份清单"


def test_每一项都指向真的函数和真的请求体() -> None:
    for kind, (request, handler) in ops._EDIT_OPS.items():
        assert callable(handler), f"{kind} 的处理函数不可调用"
        assert hasattr(request, "__dataclass_fields__"), f"{kind} 的请求体不是 dataclass"


def test_那几个曾经做不到的事现在做得到() -> None:
    """调速、调音量、分割、改字幕样式、改画幅 —— 都是用户真的会说的话。"""
    for kind in ("set_clip_speed", "set_clip_gain", "split_clip",
                 "set_clip_text", "set_subtitle_style", "set_sequence_reframe",
                 "ripple_delete_clip", "detach_clip_audio", "move_clips_batch"):
        assert kind in ops.EDIT_OP_KINDS, f"{kind} 还是不在清单里 —— 对话里说不出这件事"


def test_不认识的算子仍然报得明白() -> None:
    with pytest.raises(ops.SequenceDomainError, match="不认识的时间线操作"):
        ops.apply_edit_operations(None, "seq", [{"kind": "fly_to_the_moon"}])


def test_确认卡的校验读的是同一份() -> None:
    """校验和派发用同一份清单,否则会出现"校验放行了而派发不认识"这种最难查的那种。"""
    from app.domain.agent.confirmable import media

    assert "EDIT_OP_KINDS" in inspect.getsource(media), "确认卡那边又自己列了一份"
