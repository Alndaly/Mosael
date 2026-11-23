"""测试用的轮次运行时(`domain/agent/turn_runtime.TurnRuntime` 的第二个适配器):不连 sidecar,每个动作做什么由测试给。

    use_fake_turn_runtime(monkeypatch, run=lambda adapter, **kw: TurnResult(text="ok"))

同一个测试里再调一次(例如先给 `run`、后给 `steer`)是**补上**那一项,不会把先给的换掉。没给的动作按「没有正在跑的一轮」
回答(插话 / 排队 / 停止都回 False),`run` 与 `compact` 没给就报错 —— 测试没想到要它们,却走到了它们。
测试结束自动换回原来的运行时。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.domain.agent import turn_runtime


@dataclass
class FakeTurnRuntime:
    run_fn: Callable[..., Any] | None = None
    abort_fn: Callable[..., bool] | None = None
    steer_fn: Callable[..., bool] | None = None
    set_queue_fn: Callable[..., bool] | None = None
    compact_fn: Callable[..., Any] | None = None

    def run(self, adapter: str, **kwargs: Any) -> Any:
        if self.run_fn is None:
            raise AssertionError("这个测试没给 run,却跑了一轮")
        return self.run_fn(adapter, **kwargs)

    def abort(self, session_id: str) -> bool:
        return self.abort_fn(session_id) if self.abort_fn else False

    def steer(self, session_id: str, prompt: str, mode: str = "steer", steer_id: str = "") -> bool:
        if self.steer_fn is None:
            return False
        return self.steer_fn(session_id, prompt, mode=mode, steer_id=steer_id)

    def set_queue(self, session_id: str, items: list[dict[str, str]]) -> bool:
        return self.set_queue_fn(session_id, items) if self.set_queue_fn else False

    def compact(self, **kwargs: Any) -> Any:
        if self.compact_fn is None:
            raise AssertionError("这个测试没给 compact,却整理了上下文")
        return self.compact_fn(**kwargs)


def use_fake_turn_runtime(
    monkeypatch,
    *,
    run: Callable[..., Any] | None = None,
    abort: Callable[..., bool] | None = None,
    steer: Callable[..., bool] | None = None,
    set_queue: Callable[..., bool] | None = None,
    compact: Callable[..., Any] | None = None,
) -> FakeTurnRuntime:
    current = turn_runtime.turn_runtime()
    fake = current if isinstance(current, FakeTurnRuntime) else FakeTurnRuntime()
    for field, value in (("run_fn", run), ("abort_fn", abort), ("steer_fn", steer), ("set_queue_fn", set_queue), ("compact_fn", compact)):
        if value is not None:
            setattr(fake, field, value)
    if fake is not current:
        monkeypatch.setattr(turn_runtime, "_current", fake)
    return fake
