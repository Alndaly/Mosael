"""新建供应商连接只收认得的那几家(SEC-14)。

此前 `{"name": "x", "vendor": "x", "config": {}}` 也是 200:建出一条没有能力、没有端点、永远用不了的连接,还出现在列表里。
"""

from __future__ import annotations

from tests.util import fresh_client


def test_不认得的供应商_回422_不建连接() -> None:
    client = fresh_client()

    refused = client.post("/api/settings/providers", json={"name": "x", "vendor": "x", "config": {}})

    assert refused.status_code == 422, refused.text
    assert "x" in refused.json()["detail"]
    assert all(row["vendor"] != "x" for row in client.get("/api/settings/providers").json()), "拒了还是建出来一条"


def test_认得的照常建() -> None:
    client = fresh_client()
    created = client.post("/api/settings/providers", json={
        "name": "某端点", "vendor": "openai-compatible",
        "config": {"base_url": "https://x.example/v1", "default_model": "m", "api_key": "k"},
    })
    assert created.status_code == 200, created.text
