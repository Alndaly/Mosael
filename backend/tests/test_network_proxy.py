from __future__ import annotations

import os

import pytest

from app.domain.network import (
    DEFAULT_BYPASS_HOSTS,
    LOOPBACK_NO_PROXY,
    apply_to_process,
    effective_no_proxy,
    proxy_env,
    subprocess_env,
)
from tests.util import fresh_client

"""出站代理。

触发它的场景是「供应商按地区拒绝」——换令牌被拒的同时,后续的对话请求同样会被拒,所以能用的
最小单位是「整个应用的出站」,而不是单给 OAuth 配一个。

**最要命的一条是回环必须绕过代理**:sidecar 的每次工具调用都要回连 `127.0.0.1:<后端端口>`,
一旦被送进代理,整个智能体全废 —— 而且表现是「所有工具超时」,几乎不会有人联想到是代理。
所以回环由代码强制补上,不依赖用户填对。
"""


@pytest.fixture(autouse=True)
def _clean_proxy_env():
    """代理变量是**进程级**的,漏清会污染同一进程里后跑的用例(表现为别的测试莫名去连代理)。"""
    yield
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        os.environ.pop(key, None)
        os.environ.pop(key.lower(), None)


def test_loopback_is_always_bypassed_even_if_the_user_clears_it() -> None:
    for typed in ("", "example.com", "只写了别的"):
        bypass = effective_no_proxy(typed).split(",")
        for host in LOOPBACK_NO_PROXY:
            assert host in bypass, f"填「{typed}」时 {host} 没进绕过列表 —— 智能体的工具调用会全废"


def test_user_entries_come_first_and_are_deduped() -> None:
    assert effective_no_proxy("example.com, example.com , 127.0.0.1") == (
        "example.com,127.0.0.1,localhost,::1,0.0.0.0"
    )


def test_separators_people_actually_type_are_accepted() -> None:
    """中文逗号和换行 —— 中文输入法下这是常态,不认就等于静默丢掉一条绕过规则。"""
    assert effective_no_proxy("a，b\nc").startswith("a,b,c,")


def test_both_cases_are_set_because_libraries_disagree() -> None:
    """httpx 认小写优先,别的库和 Node 习惯大写。只设一种会出现「有的走了代理有的没走」。"""
    env = proxy_env("http://127.0.0.1:7890", "")
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:7890"
    assert env["https_proxy"] == "http://127.0.0.1:7890"
    assert env["NO_PROXY"] == env["no_proxy"]


def test_empty_proxy_means_direct() -> None:
    assert proxy_env("", "example.com") == {}
    assert proxy_env("   ", "") == {}


def test_apply_then_clear_removes_the_variables(monkeypatch) -> None:
    """关掉代理必须真的关掉。留着旧变量的话,界面显示直连、实际还在走代理。"""
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    apply_to_process("http://127.0.0.1:7890", "")
    assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:7890"
    apply_to_process("", "")
    assert "HTTPS_PROXY" not in os.environ
    assert "https_proxy" not in os.environ


def test_subprocess_env_drops_inherited_proxy_when_disabled(monkeypatch) -> None:
    """用户在应用里关掉了代理,子进程却还在用启动 shell 里继承来的老变量 —— 行为对不上界面。"""
    from app.core.db import SessionLocal

    fresh_client()
    with SessionLocal() as db:
        env = subprocess_env(db, {"HTTPS_PROXY": "http://shell-inherited:1080", "PATH": "/usr/bin"})
    assert "HTTPS_PROXY" not in env
    assert env["PATH"] == "/usr/bin", "只该动代理相关的变量"


def test_domestic_endpoints_are_bypassed_by_default() -> None:
    """配代理的动机通常是「某家境外供应商按地区拒绝」,但这个开关覆盖后端**全部**出站。
    飞书 / 火山 / 百炼这些跟着走境外代理只会更慢甚至不通,所以新装就预填上。"""
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    bypass = client.get("/api/settings/network").json()["effective_no_proxy"].split(",")
    for host in ("open.feishu.cn", "openspeech.bytedance.com", "dashscope.aliyuncs.com"):
        assert host in bypass, f"{host} 不在默认绕过列表里"


def test_default_bypass_is_a_default_not_a_rule() -> None:
    """和回环不同,国内端点用户删得掉 —— 公司代理在国内时可能就是要全量走代理。"""
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    body = client.put("/api/settings/network", json={"proxy_url": "http://p:1", "no_proxy": ""}).json()
    bypass = body["effective_no_proxy"].split(",")
    assert "open.feishu.cn" not in bypass, "国内端点应当删得掉"
    assert "127.0.0.1" in bypass, "但回环不行"


def test_settings_round_trip_and_effective_list_is_echoed() -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})

    assert client.get("/api/settings/network").json()["proxy_url"] == ""

    resp = client.put(
        "/api/settings/network", json={"proxy_url": " http://127.0.0.1:7890 ", "no_proxy": "example.com"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["proxy_url"] == "http://127.0.0.1:7890", "首尾空格要吃掉——粘贴时很容易带上"
    # 回显实际生效的绕过列表,省得用户以为本机回连也被代理了。
    assert body["effective_no_proxy"] == "example.com,localhost,127.0.0.1,::1,0.0.0.0"

    # 立刻对本进程生效:后端自己的 httpx 调用不必等重启。
    assert os.environ.get("HTTPS_PROXY") == "http://127.0.0.1:7890"

    client.put("/api/settings/network", json={"proxy_url": ""})
    assert "HTTPS_PROXY" not in os.environ
