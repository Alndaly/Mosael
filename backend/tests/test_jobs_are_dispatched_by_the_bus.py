"""建了 job 就得让总线派发它,不许自己起线程。

`dispatch_job` 是「谁来跑」的唯一决定处:它读 kind 的执行模式,in_process 就起一个叫
`JOB_THREAD_NAME` 的守护线程,external 就把 job 留在 queued 等外部 worker 认领。绕过它
自己 `threading.Thread(...)` 的代价有两个,而且都不在出错的那一刻显形:

1. **执行模式变成一句空话。** ADR-0002 和 CONTEXT.md 都承诺 `MOSAEL_EXTERNAL_JOB_KINDS=<kind>`
   能把一种任务挪给外部 worker 而不改领域代码。绕过总线的 kind 不读这个设置 —— 注册成
   external 也照样在本进程里跑,而配置的人以为它已经挪走了。

2. **线程没有名字,于是测试看不见它。** `wait_for_idle_jobs()` 按 `JOB_THREAD_NAME` 找在飞的
   线程,`fresh_client()` 靠它决定什么时候可以安全 `drop_all`。没名字的线程会活过它那条用例,
   在库被重建时写进去,炸成 `no such table: task_events` —— 而这个异常记在**当时恰好在跑的
   那条无关用例**头上。典型的"单独跑绿、全量跑红、CI 更容易红"。

`jobs.py` 里 `JOB_THREAD_NAME` 的注释一直断言「派发点只有 dispatch_job 一处,所以名字必然
覆盖全部」。写下它的时候有 4 个反例(workflow / proxy / video_to_gif / trim),而没有任何东西
会让人发现这一点 —— 这条棘轮就是那个东西。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent

# 存量越界:建 job 却自己起线程的函数,记成 `文件::函数`。**只减不增。**
ALLOWLIST: frozenset[str] = frozenset()


def _spawns_thread(node: ast.AST) -> bool:
    """`threading.Thread(...)` 或 `from threading import Thread` 之后的裸 `Thread(...)`。"""
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Attribute) and func.attr == "Thread":
            return True
        if isinstance(func, ast.Name) and func.id == "Thread":
            return True
    return False


def _calls(node: ast.AST, name: str) -> bool:
    return any(
        isinstance(child, ast.Call)
        and (
            (isinstance(child.func, ast.Name) and child.func.id == name)
            or (isinstance(child.func, ast.Attribute) and child.func.attr == name)
        )
        for child in ast.walk(node)
    )


def _scan() -> set[str]:
    found: set[str] = set()
    for path in sorted((BACKEND_ROOT / "app").rglob("*.py")):
        rel = str(path.relative_to(BACKEND_ROOT))
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # 总线自己当然又建 job 又起线程 —— 它就是那个唯一的派发点。
            if rel == "app/domain/jobs.py":
                continue
            if _calls(node, "create_job") and _spawns_thread(node) and not _calls(node, "dispatch_job"):
                found.add(f"{rel}::{node.name}")
    return found


def test_建了job就交给总线派发() -> None:
    offenders = sorted(_scan() - ALLOWLIST)
    assert not offenders, (
        "这些地方建了 job 却自己起线程:执行模式会失效,线程也没有 JOB_THREAD_NAME。"
        f"改成 dispatch_job(db, job, <零参可调用>)。越界处:{offenders}"
    )


def test_存量清单只减不增() -> None:
    stale = sorted(ALLOWLIST - _scan())
    assert not stale, f"已经修好了,从 ALLOWLIST 删掉:{stale}"


def _attribute_reads_in_thread_targets() -> set[str]:
    """`dispatch_job(db, job, lambda: ...)` 的 lambda 里读的 `x.attr`(当函数调的 `mod.f(...)` 不算)。"""
    found: set[str] = set()
    for path in sorted((BACKEND_ROOT / "app").rglob("*.py")):
        rel = str(path.relative_to(BACKEND_ROOT))
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for call in ast.walk(tree):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "dispatch_job"):
                continue
            if len(call.args) < 3 or not isinstance(call.args[2], ast.Lambda):
                continue
            target = call.args[2]
            callees = {id(node.func) for node in ast.walk(target) if isinstance(node, ast.Call)}
            for node in ast.walk(target):
                if isinstance(node, ast.Attribute) and id(node) not in callees:
                    found.add(f"{rel}:{node.lineno} {ast.unparse(node)}")
    return found


def test_交给线程的可调用只捏普通值_不在线程里读ORM属性() -> None:
    """线程起来时,调用方的会话还在用:它可能已经回滚过(回滚让会话里所有对象的属性过期,
    不看 expire_on_commit),线程里一读 `job.id` 就拿**调用方的会话**去回库加载 —— 而那个会话
    此刻可能正在下一次提交里,炸成「This session is in 'prepared' state」。

    真机上的现场是调度循环:同一轮里前一个工作流刚派发,后一个任务触发失败 `db.rollback()`,
    前一个线程还没读到 `workflow.id`。测试里记在 test_orphaned_workflow_tasks 的下一条用例头上,
    三次里挂一次。派发前把要用的 id 取成局部变量,lambda 只捏这些普通值。
    """
    offenders = sorted(_attribute_reads_in_thread_targets())
    assert not offenders, f"这些 lambda 在任务线程里读 ORM 对象的属性,先在派发前取成局部变量:{offenders}"
