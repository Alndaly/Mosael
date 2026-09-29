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
    "app/domain/agent/autopilot.py": 5,
    "app/domain/agent/confirmable/automation.py": 1,
    "app/domain/agent/confirmable/deletion.py": 1,
    "app/domain/agent/confirmations.py": 4,
    "app/domain/agent/host.py": 15,
    "app/domain/agent/questions.py": 3,
    "app/domain/ai_chat.py": 1,
    "app/domain/ai_runtime.py": 1,
    "app/domain/assets/denoise.py": 5,
    "app/domain/assets/from_url.py": 5,
    "app/domain/assets/image_grid.py": 1,
    "app/domain/assets/importer.py": 2,
    "app/domain/assets/proxies.py": 5,
    "app/domain/assets/separation.py": 5,
    "app/domain/assets/video_gif.py": 5,
    "app/domain/billing/usage.py": 1,
    "app/domain/boards/actions.py": 1,
    "app/domain/boards/canvas.py": 4,
    "app/domain/boards/plugin_references.py": 2,
    "app/domain/boards/timelines.py": 1,
    "app/domain/boards/tools.py": 2,
    "app/domain/boards/trim.py": 3,
    "app/domain/browser/__init__.py": 14,
    "app/domain/documents/extraction.py": 8,
    "app/domain/entities/drawing.py": 2,
    "app/domain/entities/library.py": 8,
    "app/domain/feishu/bindings.py": 3,
    "app/domain/feishu/bots.py": 1,
    "app/domain/fonts.py": 1,
    "app/domain/generation/operations.py": 1,
    "app/domain/generation/plugin_connections.py": 2,
    "app/domain/generation/public_links.py": 1,
    "app/domain/generation/runner.py": 15,
    "app/domain/jobs.py": 17,
    "app/domain/luts.py": 1,
    "app/domain/members.py": 6,
    "app/domain/network.py": 1,
    "app/domain/notes/__init__.py": 3,
    "app/domain/plugins/bundled.py": 1,
    "app/domain/plugins/capability_defaults.py": 2,
    "app/domain/plugins/dynamic_tools.py": 1,
    "app/domain/plugins/instances.py": 12,
    "app/domain/plugins/packages.py": 2,
    "app/domain/plugins/tools.py": 8,
    "app/domain/providers/auth.py": 1,
    "app/domain/publish/__init__.py": 6,
    "app/domain/publish/worker.py": 7,
    "app/domain/render.py": 8,
    "app/domain/scenes/operations.py": 5,
    "app/domain/scheduler/executors.py": 6,
    "app/domain/scheduler/operations.py": 5,
    "app/domain/sequences/append.py": 1,
    "app/domain/sequences/history.py": 2,
    "app/domain/sequences/operations.py": 29,
    "app/domain/session_groups.py": 4,
    "app/domain/transcripts/operations.py": 1,
    "app/domain/voices/agent_voice.py": 1,
    "app/domain/voices/subtitle_dub.py": 9,
    "app/domain/voices/transcription.py": 6,
    "app/domain/voices/voices.py": 15,
    "app/domain/workflows/__init__.py": 3,
    "app/domain/workflows/engine.py": 11,
    "app/domain/workflows/executors/common.py": 2,
    "app/domain/workflows/executors/content.py": 5,
    "app/domain/workflows/executors/dub_lipsync.py": 2,
    "app/domain/workflows/executors/entities.py": 2,
    "app/domain/workflows/executors/subjobs.py": 5,
    "app/domain/workflows/executors/talking.py": 1,
    "app/domain/workflows/plugin_references.py": 1,
    "app/domain/workflows/revisions.py": 2,
}

#: app/api 下每个文件里 ensure_workspace_perm / ensure_workspace_access 的调用数。
ROUTE_AUTHORIZATION: dict[str, int] = {
    "app/api/routes/agent.py": 3,
    "app/api/routes/agent_browser.py": 2,
    "app/api/routes/agent_tools.py": 1,
    "app/api/routes/blender.py": 8,
    "app/api/routes/boards.py": 9,
    "app/api/routes/browser_profiles.py": 5,
    "app/api/routes/collaboration.py": 6,
    "app/api/routes/confirmations.py": 2,
    "app/api/routes/documents.py": 4,
    "app/api/routes/feishu.py": 7,
    "app/api/routes/fonts.py": 4,
    "app/api/routes/generation.py": 5,
    "app/api/routes/jobs.py": 1,
    "app/api/routes/luts.py": 4,
    "app/api/routes/notifications.py": 4,
    "app/api/routes/plugins.py": 1,
    "app/api/routes/publish.py": 9,
    "app/api/routes/scheduler.py": 7,
    "app/api/routes/sequences.py": 5,
    "app/api/routes/session_groups.py": 5,
    "app/api/routes/settings/provider_pricing.py": 1,
    "app/api/routes/shares.py": 1,
    "app/api/routes/voices.py": 11,
    "app/api/routes/workflows.py": 19,
    "app/api/routes/workspaces.py": 6,
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
