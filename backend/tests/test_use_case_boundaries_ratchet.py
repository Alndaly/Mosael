"""两道只减不增的棘轮:**领域层不提交事务**、**授权不写在路由里**(见 core/unit_of_work)。

同一个领域操作有四个入口:HTTP、智能体工具、工作流节点、飞书。

- 提交写在领域函数里:组合调用时前半段已经落库、后半段失败回不去;谁该提交在每个入口各说各的。
  约定是领域只改对象(要 id 就 flush),入口层用 unit_of_work / Tx 包住一次用例。
- 授权写在路由里:另外三个入口要么经 HTTP 回连借路由的检查,要么各自补一份、容易漏。
  约定是领域函数收行动人、自己把关(见 domain/authority)。

存量冻结在下面两张表里,按领域逐个迁移。规则:某个文件的数目**变多**或新文件出现 → 红;
**变少**了 → 也红,把表里的数改小(不留一扇随时可以走回来的门)。
"""

from __future__ import annotations

# 进 docs/CONVENTIONS.md 的棘轮清单(scripts/sync-ratchet-docs.py 生成)。
RATCHET = True

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

#: app/domain 下每个文件里 `.commit()` 的调用数。
DOMAIN_COMMITS: dict[str, int] = {
    "app/domain/agent/autopilot.py": 4,
    "app/domain/agent/confirmations.py": 1,
    "app/domain/agent/host.py": 11,
    "app/domain/assets/denoise.py": 1,
    "app/domain/assets/importer.py": 1,
    "app/domain/assets/proxies.py": 1,
    "app/domain/assets/separation.py": 1,
    "app/domain/assets/video_gif.py": 1,
    "app/domain/boards/actions.py": 1,
    "app/domain/boards/persistence.py": 1,
    "app/domain/boards/plugin_references.py": 1,
    "app/domain/boards/tools.py": 1,
    "app/domain/boards/trim.py": 1,
    "app/domain/browser/__init__.py": 3,
    "app/domain/documents/extraction.py": 2,
    "app/domain/generation/plugin_connections.py": 1,
    "app/domain/generation/public_links.py": 1,
    "app/domain/generation/runner.py": 14,
    "app/domain/jobs.py": 10,
    "app/domain/members.py": 5,
    "app/domain/network.py": 1,
    "app/domain/plugins/bundled.py": 1,
    "app/domain/plugins/dynamic_tools.py": 1,
    "app/domain/plugins/instances.py": 11,
    "app/domain/plugins/packages.py": 1,
    "app/domain/plugins/tools.py": 6,
    "app/domain/render.py": 2,
    "app/domain/voices/transcription.py": 2,
    "app/domain/voices/voices.py": 5,
    "app/domain/workflows/engine.py": 8,
    "app/domain/workflows/executors/common.py": 2,
    "app/domain/workflows/executors/entities.py": 1,
    "app/domain/workflows/executors/subjobs.py": 1,
    "app/domain/workflows/executors/talking.py": 1,
    "app/domain/workflows/plugin_references.py": 1,
}

#: app/api 下每个文件里 ensure_workspace_perm / ensure_workspace_access 的调用数。
ROUTE_AUTHORIZATION: dict[str, int] = {
}


def _count(root: str, predicate) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in sorted((BACKEND / root).rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        n = sum(1 for node in ast.walk(tree) if isinstance(node, ast.Call) and predicate(node.func))
        if n:
            counts[path.relative_to(BACKEND).as_posix()] = n
    return counts


def _compare(actual: dict[str, int], frozen: dict[str, int], what: str, advice: str) -> None:
    grew = sorted(f"{path}: {frozen.get(path, 0)} → {n}" for path, n in actual.items() if n > frozen.get(path, 0))
    assert not grew, f"{what}变多了:\n  " + "\n  ".join(grew) + f"\n{advice}"
    shrank = sorted(f"{path}: {n} → {actual.get(path, 0)}" for path, n in frozen.items() if actual.get(path, 0) < n)
    assert not shrank, f"{what}变少了 —— 好事,把表里的数改小:\n  " + "\n  ".join(shrank)


def test_the_domain_does_not_commit() -> None:
    actual = _count("app/domain", lambda func: isinstance(func, ast.Attribute) and func.attr == "commit")
    _compare(
        actual,
        DOMAIN_COMMITS,
        "领域层的 commit ",
        "领域函数只改对象(要 id 就 db.flush()),提交交给入口层的 unit_of_work / Tx;"
        "提交之后才能做的事用 after_commit 登记。",
    )


def test_authorization_moves_into_the_domain() -> None:
    names = {"ensure_workspace_perm", "ensure_workspace_access"}
    actual = _count(
        "app/api", lambda func: (getattr(func, "id", None) or getattr(func, "attr", None)) in names
    )
    _compare(
        actual,
        ROUTE_AUTHORIZATION,
        "路由里的授权检查",
        "让领域函数收行动人、自己把关 —— 这样智能体工具、工作流节点、飞书走同一道检查。",
    )
