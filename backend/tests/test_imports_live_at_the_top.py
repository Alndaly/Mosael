"""棘轮:**函数里的 `from app.… import` 只减不增。**

依赖写在模块开头,读的人一眼看得出这个模块认识谁;写在函数体里,依赖就藏起来了,import 写错也要等到第一次调用
才炸。此前 app/ 里有一千四百多处这样的导入,大多是当年为了绕开循环依赖 —— 分层检查(test_import_layering)
收紧到零环之后,它们已经没有存在的理由,统一挪到了顶部。

剩下的冻结在下面,多半是**有意**的:

- `main.py` 是组装根,`_wire_seams` 里逐条登记的接缝写在一起读;`cli.py` 要启动快,打包版里也只拉起用到的那一条;
- `core/`、`db/` 是底层:它们在函数里用到上层(迁移要调领域函数改数据)是分层规则允许的反向依赖,挪到顶部就违反分层;
- 其余是同一个本地名在不同函数里指不同的东西、写在 `try` 里的可选依赖,或者函数里给这个名字重新赋值 —— 挪上去会改写意思。

挪的时候**测试会打补丁的名字按属性取**(顶部 `from app.x import y`,调用处 `y.名字`):补丁打在定义处一个地方就够,
不必逐个调用方去打;其余名字直接 `from app.x.y import 名字`。

规则:新加一处 → 红(写到顶部去;真要留在函数里,在这张表里加一行并说清为什么)。少了一处 → 也红,把表里的数改小。
"""

from __future__ import annotations

# 进 docs/CONVENTIONS.md 的棘轮清单(scripts/sync-ratchet-docs.py 生成)。
RATCHET = True

import ast
import pathlib

APP = pathlib.Path(__file__).resolve().parents[1] / "app"

#: 文件(相对 app/)→ 函数里还剩几处 `from app.… / mosael_formats.… import`。只减不增。
FROZEN = {
    "api/routes/assets.py": 2,
    "api/routes/plugins.py": 1,
    "api/routes/settings/system.py": 1,
    "api/routes/workflows.py": 1,
    "cli.py": 5,
    "core/interpreter.py": 1,
    "core/secrets_at_rest.py": 1,
    "core/security.py": 5,
    "core/shell_origin.py": 1,
    "db/migration_runner.py": 3,
    "db/migrations.py": 15,
    "domain/agent/confirmable/blender.py": 1,
    "domain/agent/confirmable/external.py": 6,
    "domain/agent/confirmable/media.py": 4,
    "domain/analysis/service.py": 6,
    "domain/assets/denoise.py": 1,
    "domain/assets/from_url.py": 2,
    "domain/assets/use_cases.py": 2,
    "domain/documents/use_cases.py": 1,
    "domain/generation/plugin_connections.py": 2,
    "domain/model_library/__init__.py": 1,
    "domain/plugin_page.py": 1,
    "domain/plugins/tools.py": 1,
    "domain/publish/__init__.py": 1,
    "domain/server_workflows.py": 2,
    "domain/triggers/dispatch.py": 3,
    "domain/voices/engine_catalog.py": 8,
    "domain/voices/original_audio.py": 1,
    "domain/voices/speech.py": 2,
    "domain/voices/voices.py": 1,
    "domain/workbench/agent.py": 6,
    "domain/workflows/executors/basic.py": 1,
    "domain/workflows/executors/subjobs.py": 1,
    "domain/workflows/field_options.py": 4,
    "domain/workflows/templates.py": 2,
    "domain/workflows/use_cases.py": 1,
    "integrations/feishu/approvals.py": 2,
    "main.py": 70,
    "media/render_executor.py": 1,
}


def lazy_app_imports(source: str) -> int:
    """函数体里的 `from app.… import` / `from mosael_formats.… import` 有几处。"""
    tree = ast.parse(source)
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    count = 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ImportFrom) and node.module and node.level == 0):
            continue
        if node.module.split(".")[0] not in ("app", "mosael_formats"):
            continue
        cur = parents.get(node)
        while cur is not None and not isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            cur = parents.get(cur)
        count += cur is not None
    return count


def test_函数里的应用内导入只减不增() -> None:
    now = {
        path.relative_to(APP).as_posix(): found
        for path in sorted(APP.rglob("*.py"))
        if (found := lazy_app_imports(path.read_text(encoding="utf-8")))
    }
    grown = {name: (FROZEN.get(name, 0), found) for name, found in now.items() if found > FROZEN.get(name, 0)}
    assert not grown, (
        "这些文件的函数里多出了 `from app.… import`(存量 → 现在)。写到模块顶部:\n  "
        + "\n  ".join(f"{name}: {was} → {found}" for name, (was, found) in sorted(grown.items()))
    )
    shrunk = {name: (was, now.get(name, 0)) for name, was in FROZEN.items() if now.get(name, 0) < was}
    assert not shrunk, (
        "这些文件函数里的导入变少了,把表里的数改小(清零就删掉那一行):\n  "
        + "\n  ".join(f"{name}: {was} → {found}" for name, (was, found) in sorted(shrunk.items()))
    )


def test_口径自己有人看着() -> None:
    assert lazy_app_imports("def f():\n    from app.x import y\n    import os\nfrom app.z import w\n") == 1
