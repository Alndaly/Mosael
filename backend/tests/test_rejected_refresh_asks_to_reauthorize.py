"""订阅凭据的刷新被对方明确拒绝 → 记成「要重新授权」;网络错误不算。界面和对话都说清楚、给去处。

维护者撞上的:Kimi Code(订阅)的刷新令牌已经失效,模型列表悬停里写着「令牌刷新失败:… unauthorized (status 400): The
provided authorization grant is invalid」,连接行却是「已授权」,没有任何提醒,智能体聊天时才报一段原文。此前「要重新授权」
只看进程内存里「设置页后台续期最近刷不动」:对话里的刷新被拒记不进去,重启又清空。现在所有刷新都经 sidecar 的
CredentialStore.modify,失败时带着原因来 release;判据只有一份(pi_client.refresh_was_rejected),记在钥匙上(重启不丢),
写进新凭据时清掉。
"""

from __future__ import annotations

import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from app.ai.sidecar import pi_client
from app.ai.sidecar.pi_client import SidecarError, refresh_was_rejected
from app.core.db import SessionLocal
from app.db.models import ProviderCredential
from app.domain.providers import auth as provider_auth
from app.main import app
from tests.refusing_sidecar import KIMI_REJECTED, NETWORK_DOWN
from app.core.child_process import popen_text
from tests.util import add_provider, fresh_client


@pytest.mark.parametrize(("error", "rejected"), [
    (KIMI_REJECTED, True),
    ("ModelsError: OAuth refresh failed for anthropic: Anthropic token refresh failed: invalid_grant", True),
    ("ModelsError: OAuth refresh failed for openai-codex: OpenAI Codex token refresh failed (401): Unauthorized", True),
    #: 只有状态码、没有那几个词:令牌端点回 400 就是这份授权用不了了
    ('ModelsError: OAuth refresh failed for openai-codex: OpenAI Codex token refresh failed (400): {"error":"invalid_request"}', True),
    (NETWORK_DOWN, False),
    ("ModelsError: OAuth refresh failed for kimi-coding: Kimi Code token refresh failed with status 503", False),
    ("ModelsError: OAuth refresh failed for xai: The operation was aborted due to timeout", False),
    ("", False),
])
def test_只认对方明确的拒绝(error: str, rejected: bool) -> None:
    assert refresh_was_rejected(error) is rejected


def _subscription() -> tuple[TestClient, str, dict]:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    with SessionLocal() as db:
        profile = add_provider(db, name="Kimi Code", vendor="kimi-coding", base_url="", api_key="", auth_type="oauth",
                               oauth_credential={"type": "oauth", "access": "a", "refresh": "r", "expires": 1},
                               model="k2", capability_ids=["chat"], make_default=False)
        db.commit()
        profile_id = profile.id
    with SessionLocal() as db:
        from app.db.models import User
        from app.domain.agent.host import mint_tool_token

        user = db.query(User).filter(User.username == "tester").one()
        headers = {"Authorization": f"Bearer {mint_tool_token(db, user)}"}
        db.commit()
    return client, profile_id, headers


def _release(profile_id: str, headers: dict, error: str) -> None:
    api = TestClient(app)
    base = f"/api/agent/provider-credentials/{profile_id}"
    lease = api.post(f"{base}/acquire", headers=headers).json()["lease"]
    assert api.post(f"{base}/release", json={"lease": lease, "refresh_error": error}, headers=headers).status_code == 204


def _row(client: TestClient, profile_id: str) -> dict:
    return next(row for row in client.get("/api/settings/providers").json() if row["id"] == profile_id)


def test_被拒的刷新记在钥匙上_连接行说授权过期_重新授权之后清掉(monkeypatch) -> None:
    monkeypatch.setattr(provider_auth, "refresh_oauth_credential", lambda **kwargs: True)
    client, profile_id, headers = _subscription()

    _release(profile_id, headers, NETWORK_DOWN)
    assert _row(client, profile_id)["oauth_expired"] is False, "断网不是授权失效"

    _release(profile_id, headers, KIMI_REJECTED)
    provider_auth._refresh_failed_at.clear()  # 重启:进程内存清空,钥匙上那一笔还在
    assert _row(client, profile_id)["oauth_expired"] is True

    api = TestClient(app)
    base = f"/api/agent/provider-credentials/{profile_id}"
    lease = api.post(f"{base}/acquire", headers=headers).json()
    committed = api.post(f"{base}/commit", headers=headers, json={
        "lease": lease["lease"], "base_version": lease["version"],
        "credential": {"type": "oauth", "access": "new", "refresh": "r2", "expires": 4102444800000},
    })
    assert committed.status_code == 200, committed.text
    assert _row(client, profile_id)["oauth_expired"] is False, "写进新凭据(重新授权、刷新成功)就清掉"
    with SessionLocal() as db:
        assert db.query(ProviderCredential).filter(ProviderCredential.profile_id == profile_id).one().oauth_rejected_at is None


def test_对话撞上被拒的刷新_说去重新授权_给去处_原文进详情(monkeypatch) -> None:
    script = (
        "import json, sys\n"
        "sys.stdin.readline()\n"
        f"print(json.dumps({{'type': 'error', 'turnId': 'turn', 'message': {KIMI_REJECTED!r}}}), flush=True)\n"
        "sys.stdin.read()\n"
    )
    monkeypatch.setattr(
        pi_client, "spawn_pi",
        lambda **_: popen_text([sys.executable, "-c", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE),
    )
    with pytest.raises(SidecarError) as caught:
        pi_client.run_turn("pi", prompt="你好", system_prompt="", api_base="http://127.0.0.1:1", token="t",
                           provider={"base_url": "http://x/v1", "api_key": "k"}, model="m")
    assert caught.value.code == "oauth_expired"
    assert "重新授权" in caught.value.human and "authorization grant" not in caught.value.human
    assert "authorization grant is invalid" in str(caught.value), "原文收进详情(message.error)"
