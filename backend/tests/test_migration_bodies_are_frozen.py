"""棘轮:**跑过一次的迁移,身体不能再改。**

`schema_migrations` 只记名字。一个一次性迁移跑成功、记上账之后,这台机器再也不会碰它 ——
所以事后改它的函数体,**对所有已经升过的机器完全无效**。改的人以为修好了;新装的机器确实
是好的;而 bug 留在的恰恰是那些有历史数据、最需要修的库上,并且没有任何东西会说一声。

审计原话是「记账表没有内容指纹,修好的迁移在老机器上不会重跑」。指纹该记在哪,是个要想清楚的
问题 —— **记进库里并按指纹重跑是错的**:一次性迁移不保证可重入(搬文件、DROP COLUMN、
按旧形状回填),而改个变量名或调个顺序就重跑,等于把一次数据迁移随机地做两遍。

所以指纹记在**仓库里**,门开在**写代码的时候**:那时人还在,还能改。判据是「这个步骤的
可执行源码变了吗」——变了就说明它做的事变了,而已经记过账的机器不会跟着变。两条出路:

· 要修的是**行为** → 新开一个步骤名(新名字 = 新的一行账 = 老机器会跑)。这是这套记账本
  本来就成立的用法,不是绕路;
· 改的只是**注释、docstring、格式** → 指纹根本不会动(它算在 `executable_source` 上,
  注释和 docstring 已经剥掉了),什么都不用做。

指纹里没有排序:步骤在计划里的**位置**不受这条约束(这一轮就把 `migrate-deployment-admin`
往前挪过 —— 它加的列被三条更早的迁移读,老库启动直接炸)。位置由
`test_schema_migrations_cover_the_models` 那条端到端升级测试守着。

**函数名也不能改。** 步骤名由函数名派生(`migrations._steps`),而步骤名就是账本那一行的 key:改了名,已经升过的
库查不到这一行账,会把它当成新的一步再跑一遍。所以指纹里不含函数名 —— 只改了名的那一步,指纹和消失的那一步一模一样,
这里当场认出来、叫人改回去;此前它表现成「少了一步、多了一步」,提示还是「跑 freeze 补上」,照做就是给每台老机器重跑一遍。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import ast
import hashlib
import json
import pathlib

from app.db.migrations import migration_plan
from tests.util import executable_source

FINGERPRINTS = pathlib.Path(__file__).parent / "migration_bodies.json"


def _digest(operation: object) -> str:
    """函数体的指纹:可执行源码,函数名换成同一个(改名不算改身体 —— 改名另有一条规矩,见 `_problems`)。"""
    tree = ast.parse(executable_source(operation))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            node.name = "step"
    return hashlib.sha256(ast.unparse(tree).encode()).hexdigest()[:16]


def _fingerprints() -> dict[str, str]:
    return {step.name: _digest(step.operation) for step in migration_plan().steps if step.once}


def _problems(recorded: dict[str, str], current: dict[str, str]) -> list[str]:
    """记下的指纹和现在的对一遍,交回要说给人听的几段话;对得上就是空的。"""
    added = sorted(set(current) - set(recorded))
    gone = sorted(set(recorded) - set(current))
    renamed = [(old, new) for new in added for old in gone if current[new] == recorded[old]]
    if renamed:
        return [
            "这些一次性迁移只改了函数名(函数体一模一样):\n  "
            + "\n  ".join(f"{old} → {new}" for old, new in renamed)
            + "\n步骤名由函数名派生,而它就是 schema_migrations 里那一行账的 key:改了名,已经升过的库会把它当成新的一步"
            "**再跑一遍** —— 一次性迁移不保证能重跑(搬文件、按旧形状回填、重算账)。把函数名改回去。"
        ]
    problems = []
    changed = sorted(name for name, digest in current.items() if name in recorded and recorded[name] != digest)
    if changed:
        problems.append(
            "这些一次性迁移的函数体变了 —— 已经记过账的机器**不会重跑它们**,所以这次修改对"
            "真正需要修的那些库无效:\n  "
            + "\n  ".join(changed)
            + "\n要改行为就新开一个步骤名(新名字 = 新的一行账);确属无害的重构(换等价写法)"
            "再更新 tests/migration_bodies.json,并在提交信息里说明为什么结果不变。"
        )
    if gone:
        problems.append(
            "这些步骤已经不在计划里了:\n  "
            + "\n  ".join(gone)
            + "\n步骤名就是账本那一行的 key:要是改了函数名(顺手改了身体),改回去 —— 改名等于让老库再跑一遍。"
            "确实是删掉了这一步,再把它从 tests/migration_bodies.json 里删掉。"
        )
    elif added:
        problems.append(
            "新的一次性迁移还没记进 tests/migration_bodies.json:\n  "
            + "\n  ".join(added)
            + "\n跑 `python -m tests.freeze_migration_bodies` 补上。"
        )
    return problems


def test_一次性迁移的身体没有被改过() -> None:
    recorded: dict[str, str] = json.loads(FINGERPRINTS.read_text(encoding="utf-8"))
    problems = _problems(recorded, _fingerprints())
    assert not problems, "\n\n".join(problems)


def test_只改了函数名的一步_认得出是改名_不让跑freeze() -> None:
    recorded = {"backfill-usage-costs": "aaaa", "reprice-usage": "bbbb"}
    renamed = {"backfill-provider-usage-costs": "aaaa", "reprice-usage": "bbbb"}
    [said] = _problems(recorded, renamed)
    assert "backfill-usage-costs → backfill-provider-usage-costs" in said and "改回去" in said
    assert "freeze" not in said


def test_改了名又改了身体_也不叫人跑freeze() -> None:
    """名字和身体一起变:指纹对不上,认不出是改名 —— 那就按「少了一步」说,不给「跑 freeze 补上」那条路。"""
    said = "\n".join(_problems({"backfill-usage-costs": "aaaa"}, {"backfill-provider-usage-costs": "cccc"}))
    assert "backfill-usage-costs" in said and "改回去" in said
    assert "freeze" not in said


def test_指纹不含函数名(tmp_path: pathlib.Path) -> None:
    import importlib.util

    module = tmp_path / "steps.py"
    module.write_text("def _backfill_a(db):\n    db.run(1)\n\n\ndef _backfill_b(db):\n    db.run(1)\n", encoding="utf-8")
    spec = importlib.util.spec_from_file_location("steps_for_digest", module)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    assert _digest(loaded._backfill_a) == _digest(loaded._backfill_b)


def test_注释和格式不算改动(tmp_path: pathlib.Path) -> None:
    """判据算在可执行源码上 —— 否则每次给迁移补一行说明都要来改指纹,而那会教人学会盲目更新它。"""
    plain = tmp_path / "plain.py"
    plain.write_text("def step():\n    value = 1\n    return value\n", encoding="utf-8")
    annotated = tmp_path / "annotated.py"
    annotated.write_text(
        "def step():\n    \'\'\'为什么要有这一步。\'\'\'\n    # 一句解释\n\n    value = 1\n\n    return value\n",
        encoding="utf-8",
    )
    assert executable_source(plain) == executable_source(annotated)
