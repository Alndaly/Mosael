"""「带我过去」过去多久了,由服务端按它自己的钟算好给出(智能体那一路 AGENT-19)。

前端此前拿这台机器的钟去减服务端的时间戳:网页版连远程服务器时两台机器差半分钟很常见 —— 每一次 open_view 都被当成过期
清掉(用户看到智能体说「带你过去了」,页面不动),或者永不过期。
"""

from __future__ import annotations

from datetime import timedelta

from app.core.db import SessionLocal
from app.db.models import AgentSession, now
from tests.test_agent_queue import _session
from tests.util import fresh_client


def test_待跳转带着服务端算的年龄() -> None:
    client = fresh_client()
    sid = _session(client)
    assert client.get(f"/api/agent/sessions/{sid}").json()["pending_view_age_seconds"] is None

    with SessionLocal() as db:
        row = db.get(AgentSession, sid)
        row.pending_view, row.pending_view_at = "media", now() - timedelta(seconds=40)
        db.commit()
    age = client.get(f"/api/agent/sessions/{sid}").json()["pending_view_age_seconds"]
    assert 39 <= age <= 45, age
    listed = client.get(f"/api/agent/sessions?workspace_id={client.get('/api/workspaces').json()[0]['id']}").json()
    assert 39 <= next(one for one in listed if one["id"] == sid)["pending_view_age_seconds"] <= 45
