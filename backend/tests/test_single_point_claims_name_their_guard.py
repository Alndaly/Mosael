"""说「唯一实现 / 唯一入口 / 只有一处」的注释,要么点名守着它的检查,要么进存量名单。

这类断言是这个仓库最有用的注释:它告诉下一个人「不用去找第二处」。也正因为如此,它错的时候
代价最大 —— 读的人**不会去验证**,那正是这句话存在的意义。

而它没有任何信号会腐烂。抽查三条:

    app/domain/jobs.py      「派发点只有 dispatch_job 一处」   假(当时有 4 个反例)
    app/domain/assets/…     「入库的唯一实现」                  假(POST /api/assets 直接建行)
    app/domain/ai_chat.py   「对话补全的唯一实现」              真

两条假的都不是写的时候就错 —— 是后来有人在别处加了第二条路,而那个人没有理由读到这句话。
措辞本身守不住任何东西;**能守住的是一个会红的检查**。

所以规矩和 `test_cross_runtime_claims_name_a_contract.py` 一样:说了这种话,就在同一段注释里
点名那个检查(`tests/test_*.py` 或 `contracts/*.json`)。点不出来,说明这句话现在只是个愿望。

`CLAIMS` 全部来自仓库里**实际出现过**的措辞,不是想象的 —— 通用的「唯一」正则会把「唯一解」
「唯一键」「唯一要回答的问题」这些普通中文一起收进来,那样这条棘轮就成了噪音。换了新说法而
被发现时,把它加进 `CLAIMS`,就又收紧一格。

`ALLOWLIST` 是存量:它们不一定是假的(ai_chat 那条就是真的),只是**还没有检查在守**。
只减不增 —— 给某一条补上守卫并从这里删掉,棘轮就前进一格。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent

#: 「全代码库范围内只此一处」的说法。逐条来自仓库现有注释。
CLAIMS = (
    "唯一装配入口",
    "唯一事实源",
    "唯一真相",
    "唯一真源",
    "唯一定义处",
    "唯一实现",
    "唯一的执行路径",
    "唯一的探测实现",
    "全项目唯一",
    "派发点只有",
    "唯一一道门",
    "只此一份",
    "唯一入口",
)

#: 认定「已经点名守卫」的写法。
GUARD_HINT = re.compile(r"tests?/test_[\w.]+\.py|test_[\w]+\.py|contracts/[\w.-]+\.json")

#: 断言前后各看几行 —— 一段注释的说明和它点名的检查通常隔着几句。
CONTEXT_LINES = 6

#: 存量:说了这话但还没有检查在守的地方,记成 `文件:行号:命中的措辞`。**只减不增。**
ALLOWLIST: frozenset[str] = frozenset({
    "app/ai/providers/__init__.py:4:唯一装配入口",
    "app/ai/providers/registry.py:1:唯一装配入口",
    "app/ai/runtime/asr_models.py:518:唯一的探测实现",
    "app/core/config.py:43:唯一真相",
    "app/core/usage_scope.py:40:唯一真源",
    "app/db/migrations.py:701:唯一真相",
    "app/db/models.py:713:唯一真相",
    "app/domain/agent/confirmations.py:91:唯一实现",
    "app/domain/ai_chat.py:1:唯一实现",
    "app/domain/assets/importer.py:141:唯一实现",
    "app/domain/deployment.py:12:唯一真相",
    "app/domain/plugins/tools.py:175:唯一的执行路径",
    "app/domain/plugins/tools.py:3:唯一的执行路径",
    "app/domain/workflows/__init__.py:531:唯一入口",
    "app/domain/workflows/binding.py:4:唯一实现",
})


def _scan() -> set[str]:
    found: set[str] = set()
    for path in sorted((BACKEND_ROOT / "app").rglob("*.py")):
        rel = str(path.relative_to(BACKEND_ROOT))
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            hit = next((claim for claim in CLAIMS if claim in line), None)
            if hit is None:
                continue
            window = "\n".join(
                lines[max(0, index - CONTEXT_LINES) : index + CONTEXT_LINES + 1]
            )
            if not GUARD_HINT.search(window):
                found.add(f"{rel}:{index + 1}:{hit}")
    return found


def test_单点断言要点名守着它的检查() -> None:
    offenders = sorted(_scan() - ALLOWLIST)
    assert not offenders, (
        "这些地方声称「只此一处」却没有任何检查在守 —— 加一道会红的检查并在注释里点名它,"
        f"或者把话说小一点。越界处:{offenders}"
    )


def test_存量清单只减不增() -> None:
    stale = sorted(ALLOWLIST - _scan())
    assert not stale, f"已经补上守卫了,从 ALLOWLIST 删掉:{stale}"
