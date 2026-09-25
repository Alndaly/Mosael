"""棘轮:插件字段的说明里写着「可以不填」,清单里就得声明 `required: false`。

清单里没写 `required` 的字段**按必填算**(manifest.py:`entry.get("required") is not False`)。
这个默认值本身没错 —— 漏标的代价应当是「多要了一项」而不是「少要了一项」。可三个对象存储
插件的「端点」说明写着「通常留空,按区域自动拼」,清单里却没标 —— 于是留空的用户在运行按钮
旁边看到「缺少配置:端点」,照着说明做反而用不了。

判据是说明文字:写了「留空 / 不填 / 可选 / empty / optional / leave」,就是在告诉用户可以不填。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import json
import re
from pathlib import Path

PLUGINS = Path(__file__).resolve().parents[2] / "plugins" / "examples"
SAYS_OPTIONAL = re.compile(r"留空|不填|可选|\bempty\b|\boptional\b|\bleave\b", re.IGNORECASE)


def _fields():
    for manifest in sorted([*PLUGINS.glob("*/mosael.plugin.json"), *(PLUGINS.parent / "bundled").glob("*/mosael.plugin.json")]):
        instance = json.loads(manifest.read_text(encoding="utf-8")).get("instance") or {}
        for group in ("config", "credentials"):
            for field in instance.get(group) or []:
                yield manifest.parent.name, field


def test_扫得到字段() -> None:
    assert sum(1 for _ in _fields()) > 15, "一个字段都没扫到 —— 清单结构变了,先修这条测试"


def test_说可以不填的字段_都声明了非必填() -> None:
    offenders = [
        f"{plugin}: {field['key']}"
        for plugin, field in _fields()
        if SAYS_OPTIONAL.search(json.dumps(field.get("help", ""), ensure_ascii=False))
        and field.get("required") is not False
    ]
    assert not offenders, "说明写着可以不填,清单却按必填算(界面会拦住留空的用户):\n  " + "\n  ".join(offenders)
