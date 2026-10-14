"""`show_widget`:智能体在回答里给一块小界面(地图、面板、小交互)。

后端只管两件事,都是界面那边管不了的:**尺寸**(HTML 原样落进消息记录,每次打开对话都整份读回)和
**校验失败要是失败的工具调用**(界面只画成功了的那几次;空的、超长的留在工具行里,原因模型也读得到)。
安全边界(不同源沙箱、CSP 断网)在前端 features/agent/agentWidget.ts,由那边的测试钉住。
"""

from __future__ import annotations

import pytest

import mcp_server
from tests.util import fresh_client


def test_成功时只回一句已显示_不把html再回给模型() -> None:
    reply = mcp_server.show_widget(title=" 路线图 ", html="<div id=map></div>")
    assert reply == {"shown": True, "title": "路线图"}


@pytest.mark.parametrize(
    ("title", "html", "says"),
    [
        ("空的", "   ", "空"),
        ("太大", "x" * (mcp_server.WIDGET_HTML_LIMIT + 1), "超过上限"),
        ("标" * (mcp_server.WIDGET_TITLE_LIMIT + 1), "<p>ok</p>", "title"),
    ],
)
def test_空的超长的是失败的调用(title: str, html: str, says: str) -> None:
    with pytest.raises(ValueError, match=says):
        mcp_server.show_widget(title=title, html=html)


def test_经工具通道调用_失败成为一句错误而不是500() -> None:
    client = fresh_client()
    ok = client.post("/api/agent/tools/show_widget", json={"arguments": {"title": "t", "html": "<p>hi</p>"}})
    assert ok.status_code == 200 and ok.json()["result"]["shown"] is True
    bad = client.post("/api/agent/tools/show_widget", json={"arguments": {"title": "t", "html": ""}})
    assert bad.status_code == 200 and "空" in bad.json()["error"]


def test_不改任何东西_所以标成只读() -> None:
    """只读决定它不走确认卡;子智能体那一路另把它排除在外(agent-sidecar/src/subagent.ts readOnlyTools)。"""
    assert mcp_server._TOOL_EFFECTS["show_widget"] == "reads"
