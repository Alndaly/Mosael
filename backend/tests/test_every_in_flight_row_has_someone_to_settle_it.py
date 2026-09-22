"""棘轮:**每一张会落「进行中」的表,都要说得出重启之后谁来收尾。**

后端一重启,进程内的线程、子进程、MCP 连接、执行器视图全没了。在调用**之前**就落库的那些行
自己不会醒过来 —— 它们停在最后一刻的样子,在界面上看起来像还在跑。

这条规矩在本仓库里被建立过**四次**,每次都写了很好的理由(jobs、agent session、browser、素材)。
第五、第六处照样漏了:

· `plugin_invocations` 永远停在 running,插件页的调用记录一直把它列出来;
· Blender 的 `transfer.json` 永远停在 sending —— `receive()` 要求 ready 所以接不回来,
  而 `history()` 会永远把它列在历史里。

所以判据不再是"记得加一个 reconciler",而是**从 ORM 推导出这个集合**,逐张问:状态列默认成
「进行中」那一类值的表,必须在 `domain/restart` 里登记 —— 要么给收尾函数,要么写清为什么
不需要(在等人、被别的机制自愈、派生自另一张表)。加一张新表时,这个问题自己会找上门。

推导面盯的是**默认值**,而不是「哪里写了 status="running"」:后者要扫全仓的赋值语句,
而默认值就写在表的定义上 —— 它是这件事的源头,也是新表一定会经过的地方。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

from app.db.models import Base
from app.domain.restart import NOT_ORPHANED_BY_RESTART, registered

#: 落下来就表示「这件事还没完」的那些状态值。
IN_FLIGHT = {"queued", "running", "pending", "sending", "checking"}


def _tables_that_start_in_flight() -> dict[str, str]:
    """表名 → 那一列的默认状态值。"""
    found: dict[str, str] = {}
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            default = getattr(column.default, "arg", None) if column.default is not None else None
            if isinstance(default, str) and default in IN_FLIGHT:
                found[table.name] = default
    return found


def test_每一张会落进行中的表都登记过() -> None:
    tables = _tables_that_start_in_flight()
    # 扫描面自己也要有人看着:推导不出东西时,下面那句断言天然成立。
    assert len(tables) >= 8, f"只推导出 {len(tables)} 张表 —— ORM 的形状变了,先修这条测试"

    declared = set(registered()) | set(NOT_ORPHANED_BY_RESTART)
    missing = sorted(set(tables) - declared)
    assert not missing, (
        "这些表一落库就是「进行中」,而重启之后没有任何人收尾 —— 它们会永远停在那一刻,"
        "在界面上看起来像还在跑:\n  "
        + "\n  ".join(f"{name}(默认 {tables[name]!r})" for name in missing)
        + "\n在 app/domain/restart.py 里登记:给一个收尾函数(registered()),"
        "或者写清为什么不需要(NOT_ORPHANED_BY_RESTART)。"
    )


def test_登记的都还是真表() -> None:
    """登记一张已经不存在的表 = 在守一个不存在的约定,而且会掩护下一个同名的表。"""
    live = {table.name for table in Base.metadata.sorted_tables}
    ghosts = sorted((set(registered()) | set(NOT_ORPHANED_BY_RESTART)) - live)
    assert not ghosts, f"restart.py 里登记的这些表已经不在模型里了:{ghosts}"


def test_不需要收尾的每一条都说得出理由() -> None:
    for table, why in NOT_ORPHANED_BY_RESTART.items():
        assert len(why.strip()) > 10, f"{table} 的豁免没写清理由"
