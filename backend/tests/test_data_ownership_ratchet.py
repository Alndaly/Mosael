"""数据归属棘轮:表的行创建只能发生在拥有它的领域模块里(ownership.py)。

AST 扫描 app/ 下所有模型构造调用,归属地图之外的记录为越界。存量越界冻结在
ALLOWLIST 里**只减不增**:
- 新增越界 → 测试失败,提示改调拥有方领域函数;
- 修掉一处存量越界 → 测试失败提示从 ALLOWLIST 删掉它(棘轮收紧)。

覆盖范围是「行创建」(Model(...) 构造);属性赋值式的更新不在此棘轮内——
那由各领域函数的接口纪律约束。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import ast
from pathlib import Path

from app.domain.ownership import EXEMPT_PREFIXES, TABLE_OWNERS

BACKEND_ROOT = Path(__file__).resolve().parent.parent

# (文件, 模型) 存量越界——每一条都是已知债务,修复后从这里删除。
# 2026-07-21 清零:AuthSession 铸造收敛进 core.security.mint_service_session,
# AgentMessage 写入收敛进 agent host 的 append_message。保持为空。
ALLOWLIST: frozenset[tuple[str, str]] = frozenset()


def _scan() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in sorted((BACKEND_ROOT / "app").rglob("*.py")):
        rel = str(path.relative_to(BACKEND_ROOT))
        if any(rel.startswith(prefix) for prefix in EXEMPT_PREFIXES):
            continue
        tree = ast.parse(path.read_text(), filename=rel)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in TABLE_OWNERS
            ):
                owners = TABLE_OWNERS[node.func.id]
                if not any(rel.startswith(owner) for owner in owners):
                    found.add((rel, node.func.id))
    return found


def test_no_new_cross_domain_row_creation() -> None:
    violations = _scan()
    new = violations - ALLOWLIST
    assert not new, (
        "新增跨领域建行:\n"
        + "\n".join(f"  {rel}: {model}" for rel, model in sorted(new))
        + "\n请改调拥有方领域函数(归属见 app/domain/ownership.py),不要直接构造模型。"
    )


def test_the_ratchet_only_tightens() -> None:
    """修掉的存量越界必须同步从 ALLOWLIST 删除,否则名单会掩护未来的回归。"""
    violations = _scan()
    stale = ALLOWLIST - violations
    assert not stale, (
        "这些 allowlist 条目已不再越界,请从 ALLOWLIST 删除以收紧棘轮:\n"
        + "\n".join(f"  {rel}: {model}" for rel, model in sorted(stale))
    )


def test_every_model_has_an_owner() -> None:
    """models.py 新增表时必须同步登记归属——否则棘轮对它是盲的。"""
    import app.db.models as models

    model_names = {
        name
        for name, obj in vars(models).items()
        if isinstance(obj, type) and hasattr(obj, "__tablename__")
    }
    unowned = model_names - set(TABLE_OWNERS)
    assert not unowned, f"这些模型没有登记数据归属(app/domain/ownership.py): {sorted(unowned)}"


def test_归属地图里没有已经删掉的表() -> None:
    """反向也要查:表删了而归属还留着,下一个人会以为那块领域还在。

    实际发生过 —— 「移除交付目标功能」删掉了 DeliveryTarget / DeliveryTask,归属地图里那两条
    却留了下来,而上面那条 test_every_model_has_an_owner 只查「模型有没有归属」,查不到反向。
    """
    import app.db.models as models

    model_names = {
        name for name, obj in vars(models).items() if isinstance(obj, type) and hasattr(obj, "__tablename__")
    }
    stale = sorted(set(TABLE_OWNERS) - model_names)
    assert not stale, f"这些表已经不存在了,请从 app/domain/ownership.py 删除归属登记: {stale}"
