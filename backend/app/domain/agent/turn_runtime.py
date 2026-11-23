"""智能体主循环(`domain/agent/host`)与**跑一轮的那个运行时**之间的缝。

主循环要运行时做五件事:跑一轮(`run`)、停下正在跑的那一轮(`abort`)、往正在跑的那一轮里插一句(`steer`)、
声明这一轮后面排着的消息(`set_queue`)、把上下文整理掉(`compact`)。真实的运行时是 pi sidecar(`ai/sidecar/pi_client`)。

此前 host 直接 import `pi_client` 的五个函数,测试靠 `monkeypatch.setattr(host, "run_turn", …)` 改模块属性(66 处);
架构文档里写的「pi Agent Adapter」在代码里不存在。现在 host 只认这里的 `turn_runtime()`:生产用 `PiSidecarRuntime`,
测试换成 `tests/turn_runtime_fake.FakeTurnRuntime`(两个适配器,一道真实的缝)。

参数与返回值照 `pi_client` 的原样(`TurnResult` / `CompactionResult` / `SidecarError` 是这道缝两边共用的类型),
换运行时不用改主循环。
"""

from __future__ import annotations

from typing import Any, Protocol

from app.ai.sidecar import pi_client
from app.ai.sidecar.pi_client import CompactionResult, TurnResult


class TurnRuntime(Protocol):
    def run(self, adapter: str, **kwargs: Any) -> TurnResult:
        """跑一轮,直到结束;`on_delta / on_tool / …` 回调在跑的途中被调用。失败抛 `SidecarError`。"""
        ...

    def abort(self, session_id: str) -> bool:
        """停下这段对话正在跑的那一轮。运行时确认收到才回 True。"""
        ...

    def steer(self, session_id: str, prompt: str, mode: str = "steer", steer_id: str = "") -> bool:
        """把一句话插进正在跑的那一轮。没有在跑的(或运行时没收下)回 False,调用方改成排队。"""
        ...

    def set_queue(self, session_id: str, items: list[dict[str, str]]) -> bool:
        """声明这一轮后面排着的整份队列(运行时只能整份清空,删不了单条)。"""
        ...

    def compact(self, **kwargs: Any) -> CompactionResult:
        """单独跑一次上下文整理。"""
        ...


class PiSidecarRuntime:
    """真实的运行时:pi sidecar。"""

    def run(self, adapter: str, **kwargs: Any) -> TurnResult:
        return pi_client.run_turn(adapter, **kwargs)

    def abort(self, session_id: str) -> bool:
        return pi_client.abort_turn(session_id)

    def steer(self, session_id: str, prompt: str, mode: str = "steer", steer_id: str = "") -> bool:
        return pi_client.steer_turn(session_id, prompt, mode=mode, steer_id=steer_id)

    def set_queue(self, session_id: str, items: list[dict[str, str]]) -> bool:
        return pi_client.set_turn_queue(session_id, items)

    def compact(self, **kwargs: Any) -> CompactionResult:
        return pi_client.compact_session(**kwargs)


_current: TurnRuntime = PiSidecarRuntime()


def turn_runtime() -> TurnRuntime:
    """主循环此刻用的运行时。"""
    return _current


def use_turn_runtime(runtime: TurnRuntime) -> TurnRuntime:
    """换一个运行时,回原来那个(测试用;生产只有 pi sidecar)。"""
    global _current
    previous, _current = _current, runtime
    return previous
