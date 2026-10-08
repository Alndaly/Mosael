"""主密钥换了或丢了,发布账号列表照常列出来,并说哪几个的设置解不开了(体检 UM-22)。

换机器只拷了数据库、从备份恢复丢了密钥、或密钥被轮换:此前 `GET /api/publish/accounts` 整个 500(config 读成 None,
响应校验失败),新建发布的目标下拉只写「没有匹配的结果」,像是「没有账号」。
"""

from __future__ import annotations

from cryptography.fernet import Fernet

from app.core import secrets_at_rest
from tests.util import fresh_client


def test_解不开的账号照样列出来_标出设置解不开了(monkeypatch) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    created = client.post(
        "/api/publish/accounts",
        json={"workspace_id": ws, "platform": "bilibili", "name": "频道", "config": {"note": "x"}},
    )
    assert created.status_code == 200, created.text
    assert created.json()["config_unreadable"] is False

    monkeypatch.setenv("MOSAEL_SECRET_KEY", Fernet.generate_key().decode())
    secrets_at_rest.master_key.cache_clear()
    try:
        listed = client.get(f"/api/publish/accounts?workspace_id={ws}")
        assert listed.status_code == 200, listed.text
        [account] = listed.json()
        assert account["name"] == "频道"
        assert account["config"] == {} and account["config_unreadable"] is True
    finally:
        secrets_at_rest.master_key.cache_clear()
