"""确认门控工具在 sidecar 这条路上的协议,必须写在它拿到的那份描述里。

sidecar 建完确认卡会**阻塞轮询**,用户批完才把最终结果交给模型(agent-sidecar/src/tools.ts)
—— 模型从头到尾看不到 confirmation_id。而工具描述里一旦留着「拿 confirmation_id 去
get_confirmation 轮询」那套(那是**直连 MCP** 才成立的协议),模型就会去找一个永远收不到的
东西:真机上它在对话里说「我没有收到 confirmation_id」,然后多跑 get_job / sleep 两步去查
一件已经做完的事。

所以:描述只说事实,协议由各自的表面自己讲——这条钉的是 sidecar 那一面。
"""

from __future__ import annotations

import mcp_server
from app.domain.agent.tool_manifest import agent_tool_specs
from tests.util import fresh_client


def test_确认门控工具的描述讲明了它是阻塞的_并且不叫模型去轮询() -> None:
    fresh_client()  # 建库
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        specs = {spec.name: spec for spec in agent_tool_specs(db)}

    gated = [name for name in mcp_server.CONFIRMATION_TOOLS if name in specs]
    assert gated, "一个确认门控工具都没进清单?"

    for name in gated:
        description = specs[name].description
        assert "BLOCKS until the user approves" in description, f"{name}:没说清它会阻塞到用户批准"
        # 反过来:别再教模型去轮询确认卡 —— 这条路上它拿不到 confirmation_id。
        assert "get_confirmation returns" not in description, f"{name}:还在教模型轮询 get_confirmation"

    # 非门控工具不该被塞这段协议:它们根本不建卡,多这一段只是噪音(还占每轮的上下文)。
    for name in ("list_assets", "get_current_time"):
        assert "BLOCKS until the user approves" not in specs[name].description, f"{name}:不该带确认协议"
