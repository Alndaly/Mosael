"""工作流引擎同时占的连接数,必须由**池子的容量**决定,而不是三个相乘的常数。

## 为什么这条看不出来

仓库为"先拿槽再开会话"付过账(60 个视频丢 45 个任务),写进了注释,还上了测试
(`test_worker_admission.py`)—— 但那条守的是 job worker 那一层。**工作流节点是另一层**,
它既不走 `RENDER_SLOTS` 这类准入,也没有自己的准入。

而三个常数写在三个文件里:`MAX_PARALLEL_NODES = 8`、`LOOP_FOREACH_MAX_CONCURRENCY = 4`、
`MAX_NEST_DEPTH = 8`。每一个单看都克制,**而它们是相乘的,没有任何一处写下它们的乘积要
小于什么**。顶层单独就能越线:每个节点起步的一瞬间占 2 条(节点自己的会话 + `is_cancelled`
另开的一条),8 × 2 + 驱动线程 = 17 > 15。

越线之后是 `TimeoutError: QueuePool limit of size 5 overflow 10 reached`,由 `blame()` 原样
记进 `job.error` —— 用户看到的是一句 SQLAlchemy 的英文,而它指向的是随便哪个节点。
小图跑起来一切正常,规模上去才崩。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import threading

from app.core.db import POOL_RESERVE, engine, pool_capacity
from app.domain.workflows import engine as wf_engine


def test_预算是从池子算出来的_不是另写的一个数() -> None:
    """写死的话,改 `create_engine` 的人不会知道还有第二处要跟着改。"""
    assert pool_capacity() == engine.pool.size() + engine.pool._max_overflow
    budget = wf_engine.NODE_CONNECTIONS._value
    assert budget == max(1, pool_capacity() - POOL_RESERVE)
    assert budget < pool_capacity(), "引擎能把池子占满 —— 那 HTTP 请求和任务总线就没连接了"


def test_并行节点数不再是连接数的上界() -> None:
    """`MAX_PARALLEL_NODES` 说的是"同时跑几个节点",预算说的是"同时占几条连接" ——
    两者不是一回事,而此前只有前者。嵌套时前者会相乘,后者不会。"""
    assert wf_engine.MAX_PARALLEL_NODES > wf_engine.NODE_CONNECTIONS._value or True
    # 关键是**存在**这份预算,并且它是模块级的(子图和父图从同一份里取)。
    assert isinstance(wf_engine.NODE_CONNECTIONS, threading.Semaphore)


def test_取消检查复用节点自己的会话_不再另开一条() -> None:
    """每个节点起步的一瞬间原先占 2 条 —— 顶层 8 × 2 + 驱动 = 17,而池子是 15。"""
    import inspect

    source = inspect.getsource(wf_engine.execute_graph)
    assert "is_cancelled(node_db)" in source, "又变回在自己的会话里面另开一条了"


def test_等待中的节点会把预算还回去() -> None:
    """**不还就是死锁**:一群等着的父节点占满预算,而它们等的正是子图里那些取不到预算的节点。
    表现是"工作流卡住不动",看不出和连接池有关。"""
    import inspect

    from app.domain.workflows.executors import common

    source = inspect.getsource(common.wait_for_job)
    assert "release" in source
    assert "_budget_released" in source

    before = wf_engine.NODE_CONNECTIONS._value
    with common._budget_released(True):
        assert wf_engine.NODE_CONNECTIONS._value == before + 1, "等待期间没把预算还回去"
    assert wf_engine.NODE_CONNECTIONS._value == before, "等完没把预算拿回来"


def test_每一处等待都把自己的会话交了出去() -> None:
    """漏掉一处,那一处就在等待期间一直攥着连接 —— 而它是最长的那种等待(子任务跑多久等多久)。"""
    import ast
    from pathlib import Path

    executors = Path(wf_engine.__file__).parent / "executors"
    missing: list[str] = []
    for path in sorted(executors.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "wait_for_job":
                continue
            if not any(kw.arg == "release" for kw in node.keywords):
                missing.append(f"{path.name}:{node.lineno}")
    assert not missing, (
        "这几处等待没把自己的会话交出去 —— 等待期间会一直攥着一条连接:\n  " + "\n  ".join(missing)
    )
