"""棘轮:**从 config 拿实体 id 的节点,必须把它收进本工作流的工作区**。

工作流的 config 有两个来源:作者手填,和上游节点的输出。两者都可能是任何地方的 id ——
`{{code.result}}` 里返回什么由那段代码说了算。所以「拿到 id 就用」等于让 A 工作区的工作流
去动 B 工作区的东西,而三个节点各自漏过一次:

· `edit_timeline` —— 直接把 sequence_id 交给 apply_edit_operations(它没有工作区的概念),
  于是能**改**别的工作区的时间线;
· `transcribe_asset` —— 转写结果要**返回到工作流输出里**,于是能把别人的内容读出来;
· `export_sequence` —— start_export 把渲染任务建在**序列所属的那个工作区**,于是能在别人
  的工作区里起一个渲染任务并拿到产出。

三个都不是"忘了写校验"这种偶然:同一个文件里 `_sequence_in` 就摆在那儿,兄弟节点都在用。
少的是一条会失败的规矩,所以补在这里。

判据走 AST,**不看源码文本**。第一版是拿字符串在函数体里搜 `workspace_id`,结果被自己的
注释骗过去了 —— 那条注释恰好在解释"为什么要收进工作区",于是节点看起来合规。一个能被注释
满足的棘轮比没有更糟:它会在真出事的时候安静地绿着。

所以现在认的是真的代码:调用了 `_sequence_in` / `_asset_in`,或者取过某个东西的
`.workspace_id` 属性。豁免只给**确实不该收**的那几个,一条一条写明。
"""

from __future__ import annotations

import ast
import pathlib

RATCHET = True

EXECUTORS = pathlib.Path(__file__).resolve().parents[1] / "app" / "domain" / "workflows" / "executors"

#: 出现这些键就意味着「这个节点要去动一个已有的实体」。
ID_KEYS = frozenset({"sequence_id", "asset_id", "asset_ids", "clip_id", "board_id", "account_id"})

#: 算作"收进工作区了"的调用。
SCOPING_CALLS = frozenset({"_sequence_in", "_asset_in"})

#: 豁免:这些节点里出现的 id 键不是"去动一个已有实体"。**只减不增**,每条写明理由。
EXEMPT = {
    # 它**创建**项目和序列,project_id 是产出不是入参;真要复用已有项目时它自己比对工作区。
    "project_create",
    "project_sequence_create",
}


def _takes_entity_id(fn: ast.AST) -> bool:
    """函数体里出现了实体 id 的**字符串常量**(config.get("asset_id") 这种)。

    只认 ast.Constant,所以注释和文档串里提到这些名字不算 —— 那正是这份棘轮第一版栽的地方。
    """
    return any(
        isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in ID_KEYS
        for node in ast.walk(fn)
    )


def _scopes_to_workspace(fn: ast.AST) -> bool:
    """调用了收敛助手,或者取过 `.workspace_id`。同样只认代码,不认注释。"""
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in SCOPING_CALLS:
            return True
        if isinstance(node, ast.Attribute) and node.attr == "workspace_id":
            return True
    return False


def _executors() -> list[tuple[str, ast.AST]]:
    """(节点名, 函数的 AST 节点)。"""
    out: list[tuple[str, ast.AST]] = []
    for path in sorted(EXECUTORS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            names = {
                arg.value
                for dec in fn.decorator_list
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name) and dec.func.id == "register"
                for arg in dec.args
                if isinstance(arg, ast.Constant)
            }
            for name in names:
                out.append((name, fn))
    return out


def test_拿了实体_id_的节点都把它收进了工作区() -> None:
    offenders = sorted(
        name
        for name, fn in _executors()
        if name not in EXEMPT and _takes_entity_id(fn) and not _scopes_to_workspace(fn)
    )
    assert not offenders, (
        "这些节点从 config 拿了实体 id 却没有收进本工作流的工作区 —— A 工作区的工作流"
        "能借此动 B 工作区的东西。用同文件里的 _sequence_in / _asset_in:\n  "
        + "\n  ".join(offenders)
    )


def test_豁免名单里的节点还都在() -> None:
    """棘轮只能缩:节点改名或删掉时,豁免要跟着删,否则它会悄悄替新节点背书。"""
    live = {name for name, _ in _executors()}
    stale = sorted(EXEMPT - live)
    assert not stale, f"这些节点已经不在了,从 EXEMPT 里删掉:{stale}"
