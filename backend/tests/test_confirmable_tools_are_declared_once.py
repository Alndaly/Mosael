"""棘轮:一个会改东西的工具,只在一处声明。

此前它摊在四处 —— 权限表、校验链、摘要链、执行链 —— 加一个工具要在四处各补一段,而漏掉的那一段
不会报错:漏了校验就是一张说不清要做什么的卡,漏了摘要就是一张只写着工具名的卡,漏了执行就是
用户点了批准然后什么都没发生。

现在一个工具就是一条 `ConfirmableTool`。这里守两件事:
1. MCP 那边标着"要确认"的工具,和登记表里的那些,是同一批(两份手写清单必然漂移);
2. 内核不认识任何具体工具的名字。
"""

from __future__ import annotations

import pathlib

RATCHET = True

KERNEL = pathlib.Path(__file__).resolve().parents[1] / "app" / "domain" / "agent" / "confirmations.py"


def test_每个登记的工具四样俱全() -> None:
    from app.domain.agent.confirmable import tool_specs

    specs = tool_specs()
    assert len(specs) >= 15, "登记表几乎是空的,多半是注册模块没被 import 到"
    for name, spec in specs.items():
        assert spec.name == name
        assert callable(spec.summarize) and callable(spec.execute), name


def test_内核不点名任何工具() -> None:
    """内核只管卡的生命周期:开卡、认人、领卡、执行、回执。"""
    from app.domain.agent.confirmable import tool_specs

    kernel = KERNEL.read_text(encoding="utf-8")
    named = sorted(name for name in tool_specs() if f'"{name}"' in kernel)
    assert not named, f"确认内核里出现了具体工具的名字:{named}"


def test_登记表和_MCP_那份要确认的清单一致() -> None:
    import mcp_server

    from app.domain.agent.confirmable import tool_specs

    assert set(mcp_server.CONFIRMATION_TOOLS) == set(tool_specs())
