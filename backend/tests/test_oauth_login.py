from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from app.ai.agent import login as login_mod
from tests.util import fresh_client

"""订阅计划的授权登录(设备码 / 浏览器授权)全链路。

跑一个假 sidecar 冒充 pi 的授权流程,验证后端这一侧:事件按序透传、提问能被作答、成功后模型
目录落库、取消能真的把进程收掉。授权协议本身在 pi 里,这里不测也不该测。

**为什么盯着「事件原样透传」**:pi 的 AuthEvent 有 auth_url / device_code / progress / info 四种,
上游随时可能加。这边一旦翻译成自定义结构,新增的那种就会在前端变成一片空白 —— 用户盯着一个
没有设备码的对话框,而日志里什么错都没有。
"""

FAKE_SIDECAR = r'''
import json, sys

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    if msg.get("type") == "auth_login":
        login_id = msg["loginId"]
        # 冒充 pi:先给设备码,再等用户把授权码贴回来
        print(json.dumps({"type": "auth_event", "loginId": login_id,
                          "event": {"type": "device_code", "userCode": "ABCD-1234",
                                    "verificationUri": "https://auth.example/device"}}), flush=True)
        print(json.dumps({"type": "auth_prompt", "loginId": login_id, "promptId": "p1",
                          "promptType": "manual_code", "message": "粘贴授权码"}), flush=True)
    elif msg.get("type") == "auth_answer":
        print(json.dumps({"type": "auth_event", "loginId": "L",
                          "event": {"type": "progress", "message": "正在换取令牌"}}), flush=True)
        print(json.dumps({"type": "auth_done", "loginId": "L",
                          "models": [{"id": "k3", "name": "K3", "contextWindow": 1048576, "maxTokens": 65536},
                                     {"id": "k3-mini", "name": "K3 mini"}]}), flush=True)
    elif msg.get("type") == "auth_cancel":
        sys.exit(0)
'''


@pytest.fixture
def fake_sidecar(tmp_path: Path, monkeypatch):
    script = tmp_path / "sidecar.py"
    script.write_text(FAKE_SIDECAR)
    monkeypatch.setattr(login_mod, "pi_sidecar_command", lambda: (sys.executable, str(script)))
    return script


@pytest.fixture
def client_and_profile():
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    resp = client.post("/api/settings/providers", json={"name": "Kimi 订阅", "vendor": "kimi-coding", "config": {}})
    assert resp.status_code == 200, resp.text
    return client, resp.json()["id"]


def _poll_until(client, profile_id: str, login_id: str, predicate, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    state: dict = {}
    while time.monotonic() < deadline:
        resp = client.get(f"/api/settings/providers/{profile_id}/oauth/login/{login_id}")
        assert resp.status_code == 200, resp.text
        state = resp.json()
        if predicate(state):
            return state
        time.sleep(0.05)
    raise AssertionError(f"等不到期望状态,最后一次是:{state}")


def test_login_streams_events_then_takes_an_answer_and_stores_the_catalog(
    fake_sidecar, client_and_profile
) -> None:
    client, profile_id = client_and_profile

    started = client.post(f"/api/settings/providers/{profile_id}/oauth/login")
    assert started.status_code == 200, started.text
    login_id = started.json()["login_id"]

    # 设备码必须原样到达前端 —— 这就是用户要照着输的那串。
    state = _poll_until(client, profile_id, login_id, lambda s: s["prompt"] is not None)
    device = next((e for e in state["events"] if e.get("type") == "device_code"), None)
    assert device is not None, f"设备码事件丢了:{state['events']}"
    assert device["userCode"] == "ABCD-1234"
    assert device["verificationUri"] == "https://auth.example/device"
    assert state["prompt"]["prompt_type"] == "manual_code"

    answered = client.post(
        f"/api/settings/providers/{profile_id}/oauth/login/{login_id}/answer",
        json={"prompt_id": state["prompt"]["prompt_id"], "answer": "代码"},
    )
    assert answered.status_code == 200, answered.text

    done = _poll_until(client, profile_id, login_id, lambda s: s["status"] in ("done", "error"))
    assert done["status"] == "done", done["error"]
    assert [m["id"] for m in done["models"]] == ["k3", "k3-mini"]

    # 目录落库:模型选择器随后要用它。以前 oauth 档案在这里只会是一个空下拉。
    listed = client.get(f"/api/settings/providers/{profile_id}/models").json()
    assert [m["id"] for m in listed] == ["k3", "k3-mini"]
    assert listed[0]["context_window"] == 1048576
    assert listed[1]["context_window"] is None, "端点没给的字段不能被填出来"

    # 没有默认模型时先挑一个:否则「登录成功但用不了」,比登录失败更费解。
    profile = client.get("/api/settings/providers").json()[0]
    assert profile["default_model"] == "k3"


def test_answering_a_prompt_that_is_no_longer_pending_is_rejected(fake_sidecar, client_and_profile) -> None:
    """重复提交(用户连点两次)不该被当成新的一步喂进去。"""
    client, profile_id = client_and_profile
    login_id = client.post(f"/api/settings/providers/{profile_id}/oauth/login").json()["login_id"]
    state = _poll_until(client, profile_id, login_id, lambda s: s["prompt"] is not None)
    prompt_id = state["prompt"]["prompt_id"]

    first = client.post(
        f"/api/settings/providers/{profile_id}/oauth/login/{login_id}/answer",
        json={"prompt_id": prompt_id, "answer": "a"},
    )
    assert first.status_code == 200
    second = client.post(
        f"/api/settings/providers/{profile_id}/oauth/login/{login_id}/answer",
        json={"prompt_id": prompt_id, "answer": "a"},
    )
    assert second.status_code == 409


def test_cancel_kills_the_process(fake_sidecar, client_and_profile) -> None:
    """用户关掉弹窗后不能留下一个等在那儿的进程 —— 授权流程最长会挂 15 分钟。"""
    client, profile_id = client_and_profile
    login_id = client.post(f"/api/settings/providers/{profile_id}/oauth/login").json()["login_id"]
    _poll_until(client, profile_id, login_id, lambda s: s["prompt"] is not None)
    session = login_mod.get_session(login_id)
    assert session is not None and session.process is not None

    resp = client.delete(f"/api/settings/providers/{profile_id}/oauth/login/{login_id}")
    assert resp.status_code == 204
    deadline = time.monotonic() + 5
    while session.process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert session.process.poll() is not None, "取消后进程还活着"


def test_a_second_start_reuses_the_running_login(fake_sidecar, client_and_profile) -> None:
    """否则用户会同时看到两串设备码,不知道该输哪个。"""
    client, profile_id = client_and_profile
    first = client.post(f"/api/settings/providers/{profile_id}/oauth/login").json()["login_id"]
    _poll_until(client, profile_id, first, lambda s: s["prompt"] is not None)
    second = client.post(f"/api/settings/providers/{profile_id}/oauth/login").json()["login_id"]
    assert second == first


def test_api_key_vendors_cannot_start_an_oauth_login(client_and_profile) -> None:
    """没有授权流程的供应商点了也白点,应当当场说清楚而不是起一个必然失败的进程。"""
    client, _ = client_and_profile
    other = client.post(
        "/api/settings/providers", json={"name": "兼容端点", "vendor": "openai-compatible",
                                         "config": {"api_key": "k", "base_url": "http://x/v1", "default_model": "m"}}
    ).json()["id"]
    resp = client.post(f"/api/settings/providers/{other}/oauth/login")
    assert resp.status_code == 400
    assert "订阅计划" in resp.json()["detail"]


def test_logout_clears_both_the_credential_and_the_catalog(fake_sidecar, client_and_profile) -> None:
    """留下目录会让登出后的模型选择器仍列着一堆用不了的模型。"""
    from app.core.db import SessionLocal
    from app.domain.provider_auth import acquire_lease, commit_credential

    client, profile_id = client_and_profile
    login_id = client.post(f"/api/settings/providers/{profile_id}/oauth/login").json()["login_id"]
    state = _poll_until(client, profile_id, login_id, lambda s: s["prompt"] is not None)
    client.post(
        f"/api/settings/providers/{profile_id}/oauth/login/{login_id}/answer",
        json={"prompt_id": state["prompt"]["prompt_id"], "answer": "代码"},
    )
    _poll_until(client, profile_id, login_id, lambda s: s["status"] == "done")
    # 真实流程里凭据由 sidecar 经 CredentialStore 写回;假 sidecar 不做这步,这里补上。
    lease = acquire_lease(profile_id)
    with SessionLocal() as db:
        commit_credential(db, profile_id, lease, {"type": "oauth", "access": "a", "refresh": "r", "expires": 1})
    assert client.get("/api/settings/providers").json()[0]["oauth_linked"] is True

    resp = client.delete(f"/api/settings/providers/{profile_id}/oauth")
    assert resp.status_code == 200, resp.text
    assert resp.json()["oauth_linked"] is False
    assert client.get(f"/api/settings/providers/{profile_id}/models").json() == []
