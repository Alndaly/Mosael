"""向量层和图谱层**真的跑起来了吗** —— 还是每次都静默降级。

`reindex_document` 把增强层索引丢进后台线程,整段包在 `except Exception: logger.exception(...)`
里,注释写着"失败只降级 —— 保存与检索永不因增强层报错"。这个设计是对的:入库不该因为
embedding 端点挂了就失败。

但降级把**另一类**错误也一起吃掉了:那个后台函数里用到了 `user_id`,而它的签名里没有这个参数,
调用处也没传 —— 于是每一次都是 NameError,每一次都被同一个 except 记进日志然后当作"增强层不可用"。
结果是向量层一次都没跑过,而**从外面看没有任何区别**:文档状态正常、chunk 数正常、检索也有结果
(FTS 兜住了),只是永远只有关键词那一层。

这一份钉的是"它到底跑没跑",不是"它跑对没跑对" —— 后者由 embedding 端点决定,前者由代码决定。
"""

from __future__ import annotations

import time

from app.core.db import SessionLocal
from app.db.models import KbDataset, KbDocument
from app.domain import kb as kb_domain
from app.domain.kb import vectors as kb_vectors
from tests.util import fresh_client


def _wait_ingested(client, document_id: str, seconds: float = 8) -> dict:
    """摄取是后台线程(抓取/转换可能几百秒),接口立刻回 queued —— 断言前要等它落定。"""
    deadline = time.time() + seconds
    while time.time() < deadline:
        row = client.get(f"/api/kb/documents/{document_id}").json()
        if row["status"] in ("completed", "error"):
            return row
        time.sleep(0.05)
    raise AssertionError("摄取一直没结束")


def _document(client) -> tuple[str, str]:
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    dataset = client.post(
        "/api/kb/datasets", json={"workspace_id": workspace_id, "name": "D"}
    )
    assert dataset.status_code == 200, dataset.text
    return workspace_id, dataset.json()["id"]


def test_the_vector_tier_is_actually_invoked(monkeypatch) -> None:
    """入库一篇文档时,向量层必须**被调用**。降级是给它调用失败准备的,不是给它没被调用准备的。"""
    calls: list[dict] = []

    monkeypatch.setattr(kb_vectors, "vector_tier_enabled", lambda: True)
    monkeypatch.setattr(
        kb_vectors,
        "upsert_document_vectors",
        lambda db, **kwargs: calls.append(kwargs),
    )

    client = fresh_client()
    workspace_id, dataset_id = _document(client)
    created = client.post(
        f"/api/kb/datasets/{dataset_id}/documents",
        json={"workspace_id": workspace_id, "title": "标题", "content": "一段够长的正文。" * 20},
    )
    assert created.status_code == 200, created.text

    # 后台线程,给它一点时间。
    deadline = time.time() + 5
    while not calls and time.time() < deadline:
        time.sleep(0.05)

    assert calls, "向量层一次都没被调用 —— 它被静默降级吃掉了"
    assert calls[0]["document_id"] == created.json()["id"]


def test_the_scheduler_receives_the_actor(monkeypatch) -> None:
    """形状棘轮:`user_id` 必须是**参数**,不是从外层碰运气借来的自由变量。

    它是自由变量时,后台线程里每次都 NameError,而 NameError 和"embedding 端点挂了"落进同一个
    except —— 一个必然失败被当成偶然失败记了下来。
    """
    import ast
    import inspect

    source = inspect.getsource(kb_domain._schedule_enhanced_index)
    tree = ast.parse(source.strip())
    function = tree.body[0]
    names = [a.arg for a in function.args.args] + [a.arg for a in function.args.kwonlyargs]

    assert "user_id" in names, f"user_id 不在签名里,却在函数体里被用到:{names}"


def test_indexing_survives_a_broken_embedding_endpoint(monkeypatch) -> None:
    """降级本身要留着:embedding 端点挂了,入库照样成功、FTS 照样能搜到。"""
    def boom(*args, **kwargs):
        raise RuntimeError("embedding 端点 503")

    monkeypatch.setattr(kb_vectors, "vector_tier_enabled", lambda: True)
    monkeypatch.setattr(kb_vectors, "upsert_document_vectors", boom)

    client = fresh_client()
    workspace_id, dataset_id = _document(client)
    created = client.post(
        f"/api/kb/datasets/{dataset_id}/documents",
        json={"workspace_id": workspace_id, "title": "关于时间线的说明", "content": "时间线是剪辑的核心。" * 20},
    )
    assert created.status_code == 200, created.text
    ingested = _wait_ingested(client, created.json()["id"])
    assert ingested["status"] == "completed", f"增强层失败把整篇文档拖成了 error:{ingested['error']}"

    with SessionLocal() as db:
        document = db.get(KbDocument, created.json()["id"])
        dataset = db.get(KbDataset, dataset_id)
        assert document.chunk_count > 0, "分块没做 —— 增强层的失败不该影响基线"
        hits = kb_domain.search(db, dataset, "时间线", user_id=None)
    assert hits, "FTS 也搜不到了 —— 降级降过头了"
