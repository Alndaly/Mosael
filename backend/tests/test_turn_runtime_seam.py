"""智能体主循环与运行时之间的缝(`domain/agent/turn_runtime`):主循环只认这里,不直接认 pi sidecar 的客户端。"""

from __future__ import annotations

import ast
import pathlib

import pytest

from app.domain.agent import turn_runtime
from app.domain.agent.turn_runtime import PiSidecarRuntime, use_turn_runtime
from tests.turn_runtime_fake import FakeTurnRuntime, use_fake_turn_runtime


def test_production_runs_on_the_pi_sidecar() -> None:
    assert isinstance(turn_runtime.turn_runtime(), PiSidecarRuntime)


def test_the_loop_does_not_import_the_sidecar_calls() -> None:
    """host 只拿 pi_client 的共用类型(结果、错误),跑一轮 / 停 / 插话 / 排队 / 整理都经 turn_runtime()。"""
    tree = ast.parse(pathlib.Path("app/domain/agent/host.py").read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "app.ai.sidecar.pi_client"
        for alias in node.names
    }
    assert imported <= {"SidecarError", "TurnResult"}, imported


def test_swapping_returns_the_previous_runtime() -> None:
    fake = FakeTurnRuntime()
    previous = use_turn_runtime(fake)
    try:
        assert turn_runtime.turn_runtime() is fake
    finally:
        assert use_turn_runtime(previous) is fake


def test_the_fake_fills_in_and_refuses_what_it_was_not_given(monkeypatch) -> None:
    fake = use_fake_turn_runtime(monkeypatch, steer=lambda *_a, **_k: True)
    assert use_fake_turn_runtime(monkeypatch, abort=lambda _sid: True) is fake, "第二次是补上,不是换掉"
    assert fake.steer("s", "hi") and fake.abort("s")
    assert fake.set_queue("s", []) is False, "没给的动作按「没有在跑的一轮」回答"
    with pytest.raises(AssertionError):
        fake.run("pi", prompt="x")
