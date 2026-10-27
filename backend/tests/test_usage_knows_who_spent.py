"""每一笔用量写的时候就记下替谁花的钱(ADR 0050 D30),老账回填找得到的人、找不到的留空(D31)。

此前「谁在花钱」顺着任务找人:智能体对话、画板、工作流节点里的调用不挂任务,维护者库上 94% 的美元花费归不到人。
"""

from __future__ import annotations

import ast
from pathlib import Path


from app.core.db import SessionLocal
from app.db.models import ProviderUsageEvent, User
from app.domain.billing.usage import billable
from tests.util import fresh_client

BACKEND = Path(__file__).resolve().parents[1]


def test_每个记账的调用点都说替谁花的钱_不写字面量None() -> None:
    """`user_id` 没有默认值,漏了在调用那一刻就报错;这里再静态看一遍,连「先传个 None 凑数」也拦下。"""
    offenders: list[str] = []
    sources = [*(BACKEND / "app").rglob("*.py"), BACKEND / "mcp_server.py"]
    for path in sources:
        tree = ast.parse(path.read_text())
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            name = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
            if name not in ("billable", "record_usage"):
                continue
            given = {kw.arg: kw.value for kw in call.keywords}
            where = f"{path.relative_to(BACKEND)}:{call.lineno}"
            if "user_id" not in given:
                offenders.append(f"{where} 没说替谁花的钱")
            elif isinstance(given["user_id"], ast.Constant) and given["user_id"].value is None:
                offenders.append(f"{where} 写了 user_id=None")
    assert not offenders, "\n".join(offenders)


def test_记账时记下替谁花的钱() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        me = db.query(User).filter_by(username="tester").one().id
        with billable(db, user_id=me, capability="chat", operation="probe", workspace_id=ws, idempotency_key="probe:me") as call:
            call.meter(requests=1)
        db.commit()
        assert db.query(ProviderUsageEvent).filter_by(idempotency_key="probe:me").one().user_id == me


def _event(db, ws: str, key: str, **facts) -> None:
    db.add(ProviderUsageEvent(workspace_id=ws, capability="chat", operation="x", idempotency_key=key, **facts))
