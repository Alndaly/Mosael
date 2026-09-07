"""结构性约束:**领域层不认识 HTTP。**

领域逻辑正是要能脱离 HTTP 被 worker / MCP / 飞书 / 工作流执行器复用。一旦某个领域模块
抛起 `HTTPException`,这些非 HTTP 的调用方就得反过来 catch 它、再翻回自己的领域错误 ——
那是把倒置换成了另一个更糟的倒置。

**这条测试是补写的,因为它真的破过。** `domain/notes.py` 曾直接抛十二处 HTTPException,
代价当场就显形在两个地方:`domain/boards.py` 校验画板引用的文档时要 catch 它,
`workflows/executors/knowledge.py` 的两个节点也要。当时 `domain/permissions.py` 的文档字符串
还写着"领域层此前 HTTPException 是 0 处" —— 措辞守不住不变量。

状态码的翻译收在边界:`main.py` 的异常处理器,或路由里的 try/except。

两条不同强度的守卫:
  ・`HTTPException` —— **硬规则,没有 allowlist**。它是 HTTP 控制流,领域层里一处都不该有;
  ・其余 fastapi 耦合 —— **棘轮**。存量冻在下面的名单里,只减不增。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

DOMAIN = Path(__file__).resolve().parents[1] / "app" / "domain"


def _modules() -> list[Path]:
    return sorted(path for path in DOMAIN.rglob("*.py") if "__pycache__" not in path.parts)


def _ids() -> list[str]:
    return [str(path.relative_to(DOMAIN)) for path in _modules()]


def _fastapi_imports(tree: ast.AST) -> list[str]:
    """`from fastapi import X` / `import fastapi` —— 函数体里的延迟导入也算。"""
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "fastapi":
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.Import):
            found += [a.name for a in node.names if a.name.split(".")[0] == "fastapi"]
    return found


RATCHET = True

#: 存量的 fastapi 耦合,**只减不增**。这些不是 HTTP 控制流,是把 `UploadFile` 当参数类型
#: 用 —— 危害小得多(领域函数仍然可以被非 HTTP 调用方喂一个鸭子类型),但它依然让领域层
#: 认识了一个 web 框架的类型。想清掉的话:收一个自己的「上传的文件」协议(名字 + 可读流),
#: 路由那侧把 UploadFile 适配过去。
_FASTAPI_ALLOWLIST = {
    "assets/importer.py": ["UploadFile"],
    "fonts.py": ["UploadFile"],
    "luts.py": ["UploadFile"],
}


@pytest.mark.parametrize("path", _modules(), ids=_ids())
def test_领域层一处都不抛_HTTPException(path: Path) -> None:
    """硬规则。领域异常 + 边界翻译是唯一的写法。"""
    imported = _fastapi_imports(ast.parse(path.read_text(encoding="utf-8")))
    assert "HTTPException" not in imported, (
        f"{path.relative_to(DOMAIN)} 导入了 HTTPException —— 领域层不该认识 HTTP 状态码。\n"
        "  抛一个领域异常,让边界去翻(见 domain/permissions 与 domain/notes 的写法)。"
    )


@pytest.mark.parametrize("path", _modules(), ids=_ids())
def test_其余_fastapi_耦合只减不增(path: Path) -> None:
    key = str(path.relative_to(DOMAIN))
    imported = sorted(name for name in _fastapi_imports(ast.parse(path.read_text(encoding="utf-8")))
                      if name != "HTTPException")
    allowed = sorted(_FASTAPI_ALLOWLIST.get(key, []))
    assert imported == allowed, (
        f"{key}:fastapi 导入是 {imported},名单说是 {allowed}。\n"
        "  新增越界要去掉;已经修好的要把它从 _FASTAPI_ALLOWLIST 里删掉(棘轮只减不增)。"
    )


def test_边界确实在翻领域异常() -> None:
    """反向守卫:上面那条只说领域层不抛 HTTP,不说有人接。**没人接 = 500。**"""
    main = (DOMAIN.parent / "main.py").read_text(encoding="utf-8")
    for name in ("NotVisible", "PermissionDenied", "NoteDomainError"):
        assert f"@app.exception_handler({name})" in main, f"{name} 没有装处理器,漏出去就是 500"
