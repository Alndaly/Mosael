"""棘轮:**新加的迁移,必须带一条喂它旧形状数据的测试。**

`migration_plan()` 里七十多个步骤,只有二十几个在 `backend/tests/` 里被任何测试**点过名**;
其余的确实每条测试都在跑(`fresh_client()` → `init_db()`),但那是空库 —— BEFORE_SCHEMA 的
迁移第一行就 `if 表不存在: return`,跑的是 no-op 分支。

仓库对迁移的纪律是「不写兼容代码,旧数据用迁移」(ADR-0006)。这条纪律把**全部**兼容风险押在
迁移的正确性上,而那份正确性此前是三分之一的覆盖。

**这条和 `test_schema_migrations_cover_the_models` 里那条端到端的种子测试是两回事,缺一不可**:
那条让**每一条**迁移都在一个有数据的老库上真的跑一遍(跑得通、真搬了东西、重跑不出事),
是一道地板;这条要的是**这一条迁移自己做对了没有** —— 它搬成什么样、边界怎么处理、
第二次跑是不是真的什么都不做。那只有写它的人说得清。

`WITHOUT_A_TEST` 是存量:**只减不增**。给其中一条补上测试并从这里删掉,棘轮就前进一格;
新加一条迁移而不写测试,它会在这里被拦下来。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import pathlib

from app.db.migrations import migration_plan

TESTS = pathlib.Path(__file__).parent

#: 还没有任何测试点过名的迁移步骤。**只减不增。**
WITHOUT_A_TEST: frozenset[str] = frozenset({
    "adopt-deepseek-vendor",
    "backfill-activity-events",
    "backfill-plugin-instances",
    "backfill-provider-models",
    "drop-clip-linked-clip-id",
    "drop-generation-models",
    "drop-legacy-profile-columns",
    "drop-member-perm-overrides",
    "drop-shared-credentials",
    "merge-openai-tts-engine",
    "merge-split-vendors",
    "migrate-agent-notice-envelope-out-of-content",
    "migrate-agent-pending-view",
    "migrate-agent-session-groups",
    "migrate-agent-session-order",
    "migrate-agent-session-plan",
    "migrate-agent-thinking-level",
    "migrate-board-revision",
    "migrate-browser-action-leases",
    "migrate-browser-pool",
    "migrate-client-surface",
    "migrate-client-version",
    "migrate-clip-offline-asset",
    "migrate-comment-canvas-context",
    "migrate-confirmation-summary-i18n",
    "migrate-drop-the-knowledge-base",
    "migrate-generation-capability-profiles",
    "migrate-generation-job-message-keys",
    "migrate-job-message-i18n",
    "migrate-job-parent",
    "migrate-model-structured-output",
    "migrate-node-names-are-not-i18n-keys",
    "migrate-permission-modes",
    "migrate-plugin-registry-url",
    "migrate-prepared-publish-tasks",
    "migrate-provider-capabilities",
    "migrate-provider-default-model-fk",
    "migrate-provider-defaults-per-person",
    "migrate-provider-model-capability-ref",
    "migrate-publish-task-claimed-by",
    "migrate-publish-task-options",
    "migrate-session-groups-serve-both",
    "migrate-shared-venvs",
    "migrate-source-assets-get-a-role",
    "migrate-tool-confirmations-session",
    "migrate-track-role",
    "migrate-tts-pip-index",
    "migrate-workflow-source-assets",
})


def _named_by_a_test() -> tuple[set[str], set[str]]:
    """(被点过名的, 没被点过名的)。

    判据是「测试文件里出现过这个步骤名或它的函数名」—— 这不是证明它测对了,而是把
    "谁也没提过它"这件事变成可见的。真正验它跑得通的是那条端到端的种子测试。
    """
    corpus = "\n".join(
        path.read_text(encoding="utf-8")
        for path in TESTS.glob("test_*.py")
        if path.name != pathlib.Path(__file__).name
    )
    named: set[str] = set()
    missing: set[str] = set()
    for step in migration_plan().steps:
        function = getattr(step.operation, "__name__", "")
        (named if (step.name in corpus or (function and function in corpus)) else missing).add(step.name)
    return named, missing


def test_扫描面站得住() -> None:
    named, missing = _named_by_a_test()
    assert len(named) + len(missing) > 60, "迁移计划只解析出几步 —— 计划的形状变了,先修这条测试"
    assert named, "一条被点名的迁移都没扫到 —— 扫描面坏了"


def test_没有新的迁移绕过测试() -> None:
    _, missing = _named_by_a_test()
    fresh = sorted(missing - WITHOUT_A_TEST)
    assert not fresh, (
        "这些迁移没有任何测试点过名 —— 它们只在空库上跑过 no-op 分支:\n  "
        + "\n  ".join(fresh)
        + "\n写一条喂它旧形状数据的测试(参考 tests/test_scene_models_move_to_disk_migration.py:"
        "既验搬对了,也验再跑一次什么都不做)。"
    )


def test_存量名单只减不增() -> None:
    """补上测试之后要顺手从名单里删掉 —— 留着的那条会掩护下一个同名的迁移。"""
    _, missing = _named_by_a_test()
    covered = sorted(WITHOUT_A_TEST - missing)
    assert not covered, (
        "这些迁移已经有测试点名了,从 WITHOUT_A_TEST 里删掉,让棘轮前进一格:\n  " + "\n  ".join(covered)
    )
