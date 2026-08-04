"""窗口被**什么**占满了,不只是占了多少。

一个百分比回答不了任何该做的决定:满了要清什么?清对话有用吗?而这个应用里真正的大头往往
**不是对话** —— 工具定义(几十个工具的 JSON schema)每次请求重发一遍,一条消息没有时它也在。
只给百分比,用户会去删对话,而那恰恰是最小的一块。

分项必须**由后端算**:算它需要系统提示的实际内容和工具清单,那两样都在服务端;前端猜不出来,
而猜出来的分项比没有分项更糟 —— 它看起来是测量结果。

对齐的是 context_meter.context_breakdown:各分项之和正好等于窗口,否则那条堆叠条读起来是错的。
"""

from __future__ import annotations

from tests.util import fresh_client


def _configured(client) -> None:
    """让这个部署有一个可用的对话模型 —— 没有模型就没有窗口,整条水位不显示。"""
    from app.core.db import SessionLocal
    from tests.util import add_provider

    with SessionLocal() as db:
        add_provider(
            db, name="P", vendor="openai-compatible", base_url="http://localhost:1/v1",
            api_key="k", model="m", capability_ids=["chat"],
            owner_username="tester",
        )
        db.commit()


def _session(client) -> str:
    _configured(client)
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    created = client.post("/api/agent/sessions", json={"workspace_id": workspace, "title": "T"})
    assert created.status_code == 200, created.text
    return created.json()["id"]


def test_the_context_comes_with_its_parts() -> None:
    client = fresh_client()
    detail = client.get(f"/api/agent/sessions/{_session(client)}").json()

    context = detail["context"]
    assert context is not None, "没配供应商?tests.util 应当已经建好了一个"
    parts = {part["kind"]: part["tokens"] for part in context["parts"]}
    assert set(parts) == {"messages", "tools", "system", "free"}


def test_the_parts_add_up_to_the_window() -> None:
    """堆叠条的前提。差一个 token 都会让最后一段画歪。"""
    client = fresh_client()
    context = client.get(f"/api/agent/sessions/{_session(client)}").json()["context"]

    assert sum(part["tokens"] for part in context["parts"]) == context["window"]


def test_the_fixed_overhead_is_visible_on_an_empty_session() -> None:
    """一条消息都没有的会话也已经占掉了一大块 —— 那正是这一屏要说清的事。

    工具定义与系统提示是**每轮都要重发**的固定成本。它们此前完全不可见,于是"剩余 98%"
    在一个连话都没说过的会话上是对的,而在它开口的那一刻就不对了。
    """
    client = fresh_client()
    context = client.get(f"/api/agent/sessions/{_session(client)}").json()["context"]
    parts = {part["kind"]: part["tokens"] for part in context["parts"]}

    assert parts["system"] > 0, "系统提示不可能是 0"
    assert parts["tools"] > 0, "工具定义不可能是 0 —— 注册表里有几十个"
    assert parts["messages"] == 0


def test_tokens_and_window_are_still_there() -> None:
    """水位条本身没变 —— 分项是加出来的一层,不是换掉的一层。"""
    client = fresh_client()
    context = client.get(f"/api/agent/sessions/{_session(client)}").json()["context"]

    assert isinstance(context["tokens"], int)
    assert context["window"] > 0
