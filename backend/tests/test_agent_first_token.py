"""首 token 打点:一轮里「等第一个字」和「后面一路吐完」是两段,分开才有得优化。

只有轮总时长的话,一轮 30 秒既可能是模型想了 29 秒才开口,也可能是它稳稳吐了 30 秒的长文 ——
这两件事该做的优化正好相反(换模型 / 减输出),而界面上长得一模一样。

这里守的是三件事:只记第一次、思考也算、**测不到就不写这个键**(缺键和 0 是两回事,前端据此
显示「—」而不是一个假的 0.0s)。
"""
from __future__ import annotations

from app.ai.agent import host


def test_first_token_is_stamped_once_and_thinking_counts() -> None:
    session = "s-first-token"
    host._stream_reset(session)
    assert host.get_stream_state(session)["first_token_at"] is None

    # 思考先到 —— 对着「思考中…」等了八秒的人不会因为吐的是思考就觉得自己没在等。
    host._stream_thinking(session, {"type": "thinking", "delta": "想一下"})
    first = host.get_stream_state(session)["first_token_at"]
    assert first is not None

    # 后面的增量不能把这个时刻往后推,否则测出来的永远是"最后一个 token"。
    host._stream_thinking(session, {"type": "thinking", "delta": "再想想"})
    host._stream_append(session, "正文")
    assert host.get_stream_state(session)["first_token_at"] == first


def test_stream_append_alone_also_stamps() -> None:
    """有的链路不发思考事件,直接吐正文 —— 那一刻同样是"第一个字"。"""
    session = "s-first-token-text"
    host._stream_reset(session)
    host._stream_append(session, "直接开说")
    assert host.get_stream_state(session)["first_token_at"] is not None


def test_empty_thinking_delta_does_not_stamp() -> None:
    """空 delta 不是一个 token。让它打点的话,收到一个空事件的轮会报出 ~0s 的首 token。"""
    session = "s-first-token-empty"
    host._stream_reset(session)
    host._stream_thinking(session, {"type": "thinking", "delta": ""})
    assert host.get_stream_state(session)["first_token_at"] is None


def test_usage_omits_first_token_when_never_stamped() -> None:
    """一个 token 都没吐出来过(轮直接失败了)—— 不写这个键,而不是写 0。"""
    import time

    started = time.monotonic()
    assert "first_token_seconds" not in host._usage_from_started(started)
    assert "first_token_seconds" not in host._usage_from_started(started, None)

    usage = host._usage_from_started(started, started + 1.5)
    assert usage["first_token_seconds"] == 1.5
    # 从轮开始算起,所以它必然落在总时长之内。
    assert usage["first_token_seconds"] <= usage["duration_seconds"] + 1.5
