"""会话钉在哪条连接上 —— 那个 id 必须当场验,不能留给数据库去炸。

`provider_profile_id` 是外键。给一个不存在的 id,插入会以 FOREIGN KEY constraint failed 结束,
接口回一个裸 500:既不说是哪个字段,也不说该怎么办,还会在监控里记成服务端故障。

这不是造出来的边角:界面开着时另一处把连接删了、客户端拿着过期的 id、或者有人从列表里手抄
时截断了(我自己就是这么撞上的)—— 都会走到这里。
"""

from __future__ import annotations

from tests.util import fresh_client


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def test_不存在的连接_id_当场说不存在() -> None:
    client = fresh_client()
    ws = _workspace(client)
    created = client.post(
        "/api/agent/sessions",
        json={"workspace_id": ws, "title": "T", "provider_profile_id": "03100a39"},
    )
    assert created.status_code == 422, created.text
    assert "连接" in created.json()["detail"]


def test_改会话时也验() -> None:
    """PATCH 是直接赋值的第二条路 —— 只挡住新建,换连接时照样写得进一个不存在的 id。"""
    client = fresh_client()
    ws = _workspace(client)
    session = client.post("/api/agent/sessions", json={"workspace_id": ws, "title": "T"}).json()
    changed = client.patch(
        f"/api/agent/sessions/{session['id']}",
        json={"provider_profile_id": "nope-not-a-profile"},
    )
    assert changed.status_code == 422, changed.text


def test_留空仍然是跟随默认() -> None:
    """不指定连接是正常用法(跟随「对话」能力的默认模型),不能被这道闸误伤。"""
    client = fresh_client()
    ws = _workspace(client)
    created = client.post("/api/agent/sessions", json={"workspace_id": ws, "title": "T"})
    assert created.status_code == 200, created.text
    assert created.json()["provider_profile_id"] is None

    session_id = created.json()["id"]
    cleared = client.patch(f"/api/agent/sessions/{session_id}", json={"provider_profile_id": ""})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["provider_profile_id"] is None


def test_真实存在的连接能钉上去() -> None:
    client = fresh_client()
    ws = _workspace(client)
    profile = client.post(
        "/api/settings/providers",
        json={"vendor": "openai-compatible", "name": "本地", "config": {"base_url": "http://localhost:11434/v1", "default_model": "gemma4:12b"}},
    )
    assert profile.status_code == 200, profile.text
    profile_id = profile.json()["id"]
    created = client.post(
        "/api/agent/sessions",
        json={"workspace_id": ws, "title": "T", "provider_profile_id": profile_id},
    )
    assert created.status_code == 200, created.text
    assert created.json()["provider_profile_id"] == profile_id
