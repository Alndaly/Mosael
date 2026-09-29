"""MCP 服务没设 `is_error`、把上游失败当正常结果交回来时,调用照样算失败。

用户截图:TikHub 的 key 被拒(403),插件页那条调用记录却写着「成功」—— 那家的 MCP 服务把
`{"error": "unauthorized", "status": 403, ...}` 放进正常结果里,宿主此前只认协议上的 `is_error`。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.domain.plugins import mcp_bridge

TIKHUB_REJECTED = {"error": "unauthorized", "status": 403,
                   "message": "TikHub API key was rejected. Double-check the token you passed via the Authorization: Bearer header."}


def _call(monkeypatch, *, structured=None, text=""):
    class Session:
        async def call_tool(self, name, arguments):
            return SimpleNamespace(is_error=False, structured_content=structured,
                                   content=[SimpleNamespace(text=text)] if text else [])

    monkeypatch.setattr(mcp_bridge, "_sync", lambda _manifest, _env, fn, **_kwargs: asyncio.run(fn(Session())))
    return mcp_bridge.call_tool({"kind": "mcp", "mcp": {}}, "bilibili_web_fetch_video_comments", {}, {})


@pytest.mark.parametrize("shape", [
    pytest.param({"result": json.dumps(TIKHUB_REJECTED)}, id="包在 result 里的一段 JSON 文本(TikHub 实际的样子)"),
    pytest.param({"result": TIKHUB_REJECTED}, id="包在 result 里的对象"),
    pytest.param(TIKHUB_REJECTED, id="直接就是错误对象"),
])
def test_结构化结果里是上游错误_算失败_说出上游原话和状态码(monkeypatch, shape) -> None:
    with pytest.raises(mcp_bridge.McpBridgeError) as raised:
        _call(monkeypatch, structured=shape)
    assert raised.value.key == "pluginErr_upstream"
    assert "key was rejected" in str(raised.value) and "403" in str(raised.value)


def test_只回文本块的服务_文本里是上游错误也算失败(monkeypatch) -> None:
    with pytest.raises(mcp_bridge.McpBridgeError):
        _call(monkeypatch, text=json.dumps({"error": "rate limited", "status_code": 429}))


@pytest.mark.parametrize("data", [
    pytest.param({"status": 404, "title": "一条已删除的视频"}, id="有状态码但没有 error 的正常数据"),
    pytest.param({"error": "", "status": 500}, id="error 是空的"),
    pytest.param({"error": "none", "status": 200}, id="状态码不是 4xx/5xx"),
    pytest.param({"result": "纯文本,不是 JSON"}, id="result 是普通文本"),
    pytest.param({"result": json.dumps({"comments": []}), "cursor": 1}, id="result 旁边还有别的字段"),
])
def test_不是明确的上游错误_照常当数据(monkeypatch, data) -> None:
    assert _call(monkeypatch, structured=data) == data


def test_插件页那条调用记录写成失败_带着原因(monkeypatch) -> None:
    """走到底:tools.invoke 记下的调用是 failed、error 里是上游那句话 —— 不是 succeeded 加一段错误 JSON。"""
    from app.core.db import SessionLocal
    from app.domain.plugins import tools as tools_domain
    from tests.test_plugins import install

    from app.db.models import PluginInstance

    client = install({"id": "dev.fakemcp", "name": "假 MCP", "version": "1.0.0", "runtime": {"kind": "mcp", "command": "x"}})
    with SessionLocal() as db:
        instance_id = db.query(PluginInstance).filter_by(package_id="dev.fakemcp").one().id
    monkeypatch.setattr(tools_domain, "discover_tools", lambda *_args, **_kwargs: [
        {"name": "fetch", "description": "取评论", "input_schema": {"type": "object", "properties": {}}}])
    client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True})

    class Session:
        async def call_tool(self, name, arguments):
            return SimpleNamespace(is_error=False, structured_content={"result": json.dumps(TIKHUB_REJECTED)}, content=[])

    monkeypatch.setattr(mcp_bridge, "_sync", lambda _manifest, _env, fn, **_kwargs: asyncio.run(fn(Session())))
    with SessionLocal() as db:
        invocation = tools_domain.invoke(db, instance_id, "fetch", {})
    assert invocation.status == "failed", invocation.output
    assert "key was rejected" in (invocation.error or "") and "403" in invocation.error
