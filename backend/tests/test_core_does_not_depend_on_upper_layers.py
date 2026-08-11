"""`app/core` 是最底层:**谁都可以 import 它,它不 import 任何人**。

此前它反向依赖着上层:

    app/core/db.py:964  from app.audio import asr_models
    app/core/db.py:965  from app.domain import tts_config

而且是**写在函数体里**的 import —— 那不是技巧,是"层分错了"的自白:写在文件顶上会立刻成环
(core.db → domain.tts_config → core.config → …),挪进函数里只是把环推迟到运行时。

根因是 `core/db.py` 同时是两个东西:**引擎与会话**(最底层,二十几处 import 它)和
**迁移编排器**(最顶层,它要认识每一个领域)。两个方向相反的职责挤在一个模块里,就只能靠
函数内 import 硬撑。拆开之后,迁移住到 `app/db/migrations.py` —— 它在依赖序的顶端,
爱 import 谁 import 谁。
"""

from __future__ import annotations

import ast
import pathlib

#: core 不许 import 的层。db 不在其中:models/迁移都建立在 core 的 Base 之上,方向是对的。
UPPER_LAYERS = {"domain", "audio", "media", "ai", "api", "integrations", "workers"}


def _upward_imports() -> list[str]:
    offenders: list[str] = []
    for path in sorted(pathlib.Path("app/core").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                parts = node.module.split(".")
                if parts[:1] == ["app"] and len(parts) > 1 and parts[1] in UPPER_LAYERS:
                    offenders.append(f"{path}:{node.lineno} → {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    parts = alias.name.split(".")
                    if parts[:1] == ["app"] and len(parts) > 1 and parts[1] in UPPER_LAYERS:
                        offenders.append(f"{path}:{node.lineno} → {alias.name}")
    return offenders


def test_core_imports_nothing_from_above() -> None:
    offenders = _upward_imports()

    assert offenders == [], (
        "最底层反过来依赖上层了。写在函数里也算 —— 那只是把环推迟到运行时:\n  "
        + "\n  ".join(offenders)
    )


def test_core_db_is_only_engine_and_session() -> None:
    """`core/db.py` 只负责引擎/会话/Base。迁移逻辑一旦回流,上一条迟早跟着红。"""
    source = pathlib.Path("app/core/db.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    migrations = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and (node.name.startswith("_migrate") or node.name.startswith("_backfill") or node.name.startswith("_drop"))
    ]

    assert migrations == [], (
        "迁移函数又长回 core/db.py 了 —— 它们要认识领域层,而这个模块是被所有人 import 的底座:\n  "
        + "\n  ".join(migrations)
    )
