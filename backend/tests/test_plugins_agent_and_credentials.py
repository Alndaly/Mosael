"""插件的三条新接缝:凭据、智能体一等公民工具、MCP 类插件。

这三件事其实是同一个问题的三个面 —— 插件此前只能是"不需要凭据、只有用户手点才跑得起来、
而且必须自己写 Python"的纯函数。这些测试钉住的是它不再是那样,以及**边界仍然在原处**:
插件拿到的仍然只有它自己声明的那几个键。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.db import SessionLocal
from app.domain.plugins import scan_plugins
from tests.util import fresh_client

MANIFEST = {
    "id": "dev.keyed",
    "name": "Keyed Plugin",
    "version": "0.1.0",
    "entry": "main.py",
    "credentials": [
        {"key": "DEMO_API_KEY", "label": "Demo Key", "secret": True, "required": True},
        {"key": "DEMO_BASE_URL", "label": "Base URL", "secret": False, "required": False},
    ],
    "tools": [
        {
            "name": "echo_env",
            "description": "回显进程环境,用来证明注入边界。",
            "read_only": True,
            "input_schema": {"type": "object", "properties": {}},
        }
    ],
}

#: 把自己的环境原样吐回来 —— 注入了什么、没注入什么,断言直接看得到。
ENTRY = """
import json, os, sys
json.loads(sys.stdin.read())
json.dump({"ok": True, "output": {"env": dict(os.environ)}}, sys.stdout)
"""


def _install(tmp_path: Path, manifest: dict = MANIFEST):
    """建库 + 登录 + 装一个插件。顺序要紧:fresh_client 会重建库,插件必须在那之后扫进去。"""
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})  # 插件的管理端点要求实例管理员
    plugin_dir = tmp_path / "plugins" / "keyed"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "open-studio.plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    (plugin_dir / "main.py").write_text(ENTRY, encoding="utf-8")
    with SessionLocal() as db:
        scan_plugins(db, tmp_path / "plugins")
    return client


def test_插件只拿到自己声明的凭据_拿不到应用的(tmp_path: Path, monkeypatch) -> None:
    """隔离边界。插件运行时不透传应用凭据是这套设计的地基,加了凭据注入之后必须仍然如此 ——
    否则"插件绕不过确认卡"这句话就不成立了。"""
    monkeypatch.setenv("OPENAI_API_KEY", "应用自己的密钥-不该出现在插件里")
    client = _install(tmp_path)
    client.patch("/api/plugins/dev.keyed", json={"enabled": True})
    client.patch("/api/plugins/dev.keyed/credentials", json={"values": {"DEMO_API_KEY": "k-123"}})

    invocation = client.post("/api/plugins/dev.keyed/tools/echo_env/invoke", json={"input": {}}).json()
    assert invocation["status"] == "succeeded", invocation.get("error")
    env = invocation["output"]["env"]
    assert env["DEMO_API_KEY"] == "k-123"
    assert "OPENAI_API_KEY" not in env
    # 未填的可选项不注入空串:插件据此判断"没配"和"配成了空"应当一致。
    assert "DEMO_BASE_URL" not in env


def test_密文凭据回显是掩码_原样提交不覆盖(tmp_path: Path) -> None:
    """用户改「接口地址」时不该把已存的 key 洗成一串星号 —— 表单会把它读到的东西发回来。"""
    from app.domain.plugins.credentials import MASK

    client = _install(tmp_path)
    client.patch("/api/plugins/dev.keyed/credentials", json={"values": {"DEMO_API_KEY": "k-123"}})

    listed = {item["key"]: item for item in client.get("/api/plugins/dev.keyed/credentials").json()}
    assert listed["DEMO_API_KEY"]["value"] == MASK and listed["DEMO_API_KEY"]["filled"] is True

    client.patch(
        "/api/plugins/dev.keyed/credentials",
        json={"values": {"DEMO_API_KEY": MASK, "DEMO_BASE_URL": "https://example.test"}},
    )
    client.patch("/api/plugins/dev.keyed", json={"enabled": True})
    env = client.post("/api/plugins/dev.keyed/tools/echo_env/invoke", json={"input": {}}).json()["output"]["env"]
    assert env["DEMO_API_KEY"] == "k-123"
    assert env["DEMO_BASE_URL"] == "https://example.test"


def test_未声明的凭据键被拒绝(tmp_path: Path) -> None:
    """声明先行:接口只接受 manifest 写过的键,否则这张表会变成一个人人可写的通用键值库。"""
    client = _install(tmp_path)
    res = client.patch("/api/plugins/dev.keyed/credentials", json={"values": {"SOMETHING_ELSE": "x"}})
    assert res.status_code == 422
    assert "SOMETHING_ELSE" in res.json()["detail"]


def test_缺必填凭据的插件不进工具表(tmp_path: Path) -> None:
    """让智能体调一个必定 401 的工具,只会烧掉一轮对话来复述一句设置页早就写着的话。"""
    client = _install(tmp_path)
    client.patch("/api/plugins/dev.keyed", json={"enabled": True})
    assert client.get("/api/plugins/tools").json() == []

    client.patch("/api/plugins/dev.keyed/credentials", json={"values": {"DEMO_API_KEY": "k-123"}})
    tools = client.get("/api/plugins/tools").json()
    assert [tool["tool_name"] for tool in tools] == ["echo_env"]


def test_插件工具在智能体清单里是一等公民(tmp_path: Path) -> None:
    """回归的是发现成本:元工具意味着模型要先"想到"可能有插件能帮忙,再花一轮列清单才知道
    参数长什么样 —— 它想不到的时候,用户装的插件就等于不存在。"""
    client = _install(tmp_path)
    client.patch("/api/plugins/dev.keyed", json={"enabled": True})
    client.patch("/api/plugins/dev.keyed/credentials", json={"values": {"DEMO_API_KEY": "k-123"}})

    manifest = {tool["name"]: tool for tool in client.get("/api/agent/tools").json()}
    spec = manifest["plugin__dev_keyed__echo_env"]
    assert "Keyed Plugin" in spec["description"]
    assert spec["parameters"]["type"] == "object"
    # 元工具让位给展开后的一等公民,不再在这份清单里重复同一个能力。
    assert "invoke_plugin_tool" not in manifest and "list_plugin_tools" not in manifest

    result = client.post("/api/agent/tools/plugin__dev_keyed__echo_env", json={"arguments": {}})
    assert result.status_code == 200, result.text
    assert result.json()["result"]["env"]["DEMO_API_KEY"] == "k-123"


def test_停用后智能体那条路径立刻关上(tmp_path: Path) -> None:
    """模型手里还攥着上一轮的工具表,而权限可能在这中间被撤掉。"""
    client = _install(tmp_path)
    client.patch("/api/plugins/dev.keyed", json={"enabled": True})
    client.patch("/api/plugins/dev.keyed/credentials", json={"values": {"DEMO_API_KEY": "k-123"}})
    assert client.post("/api/agent/tools/plugin__dev_keyed__echo_env", json={"arguments": {}}).status_code == 200

    client.patch("/api/plugins/dev.keyed", json={"enabled": False})
    blocked = client.post("/api/agent/tools/plugin__dev_keyed__echo_env", json={"arguments": {}})
    assert blocked.status_code == 404
    assert "未启用" in blocked.json()["detail"]


def test_插件工具默认不是只读_子智能体因此拿不到(tmp_path: Path) -> None:
    """内置工具的只读判据是"没有确认门";插件工具没有确认门也照样能发请求、写文件,所以
    默认落在保守那侧,要 manifest 明写才算。"""
    manifest = json.loads(json.dumps(MANIFEST))
    manifest["tools"].append(
        {"name": "do_something", "description": "会改东西", "input_schema": {"type": "object", "properties": {}}}
    )
    client = _install(tmp_path, manifest)
    client.patch("/api/plugins/dev.keyed", json={"enabled": True})
    client.patch("/api/plugins/dev.keyed/credentials", json={"values": {"DEMO_API_KEY": "k-123"}})

    specs = {tool["name"]: tool for tool in client.get("/api/agent/tools").json()}
    assert specs["plugin__dev_keyed__echo_env"]["read_only"] is True
    assert specs["plugin__dev_keyed__do_something"]["read_only"] is False
    # 内置工具的只读仍然等价于"没有确认门",这条改动不该动到它们。
    assert specs["search_kb"]["read_only"] is True
    assert specs["render_sequence"]["read_only"] is False


# ---------------------------------------------------------------------------
# MCP 类插件
#
# 这里跑的是**真的** MCP:spawn 一个真的 server、握真的手、要真的工具清单。
# 把传输层 mock 掉的话,这些测试就只是在测我自己写的那个 mock —— 而这条链路上会出事的地方
# (握手、清单形状、结果块的取值)恰好全在被 mock 掉的那一侧。
# ---------------------------------------------------------------------------

MCP_SERVER = '''
import os
# mcp 2.0 把 FastMCP 改名为 MCPServer;装饰器与 run() 不变。
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("demo")


@mcp.tool()
def whoami() -> dict:
    """回显注入进来的环境,用来证明 MCP 插件的隔离边界和进程类插件一致。"""
    env = dict(os.environ)
    return {"demo_key": env.get("DEMO_API_KEY", ""), "leaked": "OPENAI_API_KEY" in env}


if __name__ == "__main__":
    mcp.run()
'''

MCP_MANIFEST = {
    "id": "dev.mcp",
    "name": "MCP Plugin",
    "version": "0.1.0",
    "kind": "mcp",
    "mcp": {"transport": "stdio", "command": "PYTHON", "args": ["server.py"]},
    "credentials": [{"key": "DEMO_API_KEY", "label": "Demo Key", "secret": True, "required": True}],
}


def _install_mcp(tmp_path: Path, manifest: dict | None = None):
    import sys

    manifest = json.loads(json.dumps(manifest or MCP_MANIFEST))
    manifest["mcp"]["command"] = sys.executable
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    plugin_dir = tmp_path / "plugins" / "mcp"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "open-studio.plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    (plugin_dir / "server.py").write_text(MCP_SERVER, encoding="utf-8")
    with SessionLocal() as db:
        scan_plugins(db, tmp_path / "plugins")
    return client


def test_mcp_插件的工具清单来自_server_而不是_manifest(tmp_path: Path) -> None:
    """在 manifest 里手抄一份端点清单,等于把一个会随 server 升级而变的东西冻住 ——
    它会烂,而且烂得很安静。"""
    client = _install_mcp(tmp_path)
    client.patch("/api/plugins/dev.mcp/credentials", json={"values": {"DEMO_API_KEY": "k-123"}})
    client.patch("/api/plugins/dev.mcp", json={"enabled": True})

    tools = client.get("/api/plugins/tools").json()
    assert [tool["tool_name"] for tool in tools] == ["whoami"]
    assert tools[0]["kind"] == "mcp"
    # 清单是拉来的,不是抄来的:manifest 文件里根本没有 tools 这一项。
    assert tools[0]["input_schema"]["type"] == "object"


def test_mcp_插件的隔离边界与进程类插件一致(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "应用自己的密钥-不该出现在插件里")
    client = _install_mcp(tmp_path)
    client.patch("/api/plugins/dev.mcp/credentials", json={"values": {"DEMO_API_KEY": "k-123"}})
    client.patch("/api/plugins/dev.mcp", json={"enabled": True})

    invocation = client.post("/api/plugins/dev.mcp/tools/whoami/invoke", json={"input": {}}).json()
    assert invocation["status"] == "succeeded", invocation.get("error")
    output = invocation["output"]
    assert output["demo_key"] == "k-123"
    assert output["leaked"] is False


def test_mcp_插件的工具同样是智能体的一等公民(tmp_path: Path) -> None:
    """接一个 MCP server 进来,不该在"能不能被智能体用上"这件事上矮一头 —— 这正是接它的理由。"""
    client = _install_mcp(tmp_path)
    client.patch("/api/plugins/dev.mcp/credentials", json={"values": {"DEMO_API_KEY": "k-123"}})
    client.patch("/api/plugins/dev.mcp", json={"enabled": True})

    names = {tool["name"] for tool in client.get("/api/agent/tools").json()}
    assert "plugin__dev_mcp__whoami" in names
    result = client.post("/api/agent/tools/plugin__dev_mcp__whoami", json={"arguments": {}})
    assert result.status_code == 200, result.text
    assert result.json()["result"]["demo_key"] == "k-123"


def test_mcp_插件的只读由装它的人决定_不由_server_自称(tmp_path: Path) -> None:
    manifest = json.loads(json.dumps(MCP_MANIFEST))
    client = _install_mcp(tmp_path, manifest)
    client.patch("/api/plugins/dev.mcp/credentials", json={"values": {"DEMO_API_KEY": "k-123"}})
    client.patch("/api/plugins/dev.mcp", json={"enabled": True})
    specs = {tool["name"]: tool for tool in client.get("/api/agent/tools").json()}
    assert specs["plugin__dev_mcp__whoami"]["read_only"] is False

    # manifest 的 tools 是**按名字的覆盖层**,不是第二份清单。
    manifest["tools"] = [{"name": "whoami", "read_only": True}]
    client = _install_mcp(tmp_path, manifest)
    client.patch("/api/plugins/dev.mcp/credentials", json={"values": {"DEMO_API_KEY": "k-123"}})
    client.patch("/api/plugins/dev.mcp", json={"enabled": True})
    specs = {tool["name"]: tool for tool in client.get("/api/agent/tools").json()}
    assert specs["plugin__dev_mcp__whoami"]["read_only"] is True


def test_缺凭据时报的是缺哪一项_而不是一句连不上(tmp_path: Path) -> None:
    client = _install_mcp(tmp_path)
    res = client.post("/api/plugins/dev.mcp/refresh")
    assert res.status_code == 422
    assert "DEMO_API_KEY" in res.json()["detail"]
