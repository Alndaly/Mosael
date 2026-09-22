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
#
# 2026-07-21 清零过一次。**2026-09-23 重新装上 11 条,不是退步,是把藏起来的债务摆出来**:
# `app/api/routes/` 此前整层写在 `ownership.EXEMPT_PREFIXES` 里,理由是"路由是薄转译" ——
# 于是那下面的 19 处直接建行一处都不会被看见,而 ADR-0003、ARCHITECTURE.md 和一次审计的
# 「没有发现问题的地方」三处都把"棘轮强制"当成了既成事实。
#
# **一个被普遍相信的保证,和一个没有的保证,不是同一种风险 —— 前者更坏**,因为它让人不再去看。
# 豁免写在**被检查方**(domain/ownership)而不是检查方,读这条测试的人也看不到它。
#
# 名单只减不增:每修掉一处就从这里删一行,测试会提醒。
ALLOWLIST: frozenset[tuple[str, str]] = frozenset({
    ("app/api/routes/assets.py", "Asset"),
    ("app/api/routes/feishu.py", "FeishuBot"),
    ("app/api/routes/oauth.py", "User"),
    ("app/api/routes/projects.py", "Workspace"),
    ("app/api/routes/projects.py", "WorkspaceMember"),
    ("app/api/routes/sequences.py", "Sequence"),
    ("app/api/routes/sequences.py", "Track"),
    ("app/api/routes/settings/provider_profiles.py", "ProviderProfile"),
    ("app/api/routes/settings/system.py", "AiRuntimeConfig"),
    ("app/api/routes/settings/system.py", "TtsConfig"),
    ("app/api/routes/voices.py", "TtsConfig"),
})


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
