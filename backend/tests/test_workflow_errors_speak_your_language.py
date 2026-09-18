"""棘轮:工作流跑失败时那句话,也得跟着读的人的语言走。

失败原因会**落库**(Job.error / error_key / error_params),而任务记录活得比一次请求久 ——
写入时就翻会把语言冻死在那一刻。所以和任务消息同构:存 key + 参数,接口按请求方的语言翻。

这里守两件事:
1. 执行器里不再有写死的句子(新报错一律给 key,数据走 params——拼进句子它就只有一种语言了);
2. 每个用到的 key 都在 MESSAGES 里、两种语言都有。
"""

from __future__ import annotations

import ast
import pathlib

RATCHET = True

WORKFLOWS = pathlib.Path(__file__).resolve().parents[1] / "app" / "domain" / "workflows"


def _raised_messages() -> list[tuple[str, int, ast.AST]]:
    out: list[tuple[str, int, ast.AST]] = []
    for path in sorted(WORKFLOWS.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)):
                continue
            if getattr(node.exc.func, "id", "") != "WorkflowDomainError" or not node.exc.args:
                continue
            out.append((str(path.relative_to(WORKFLOWS)), node.lineno, node.exc.args[0]))
    return out


def test_报错不写死句子() -> None:
    literals: list[str] = []
    for where, line, first in _raised_messages():
        if isinstance(first, ast.JoinedStr):
            literals.append(f"{where}:{line} 用了 f-string —— 数据走 params,别拼进句子")
        elif isinstance(first, ast.Constant) and not str(first.value).startswith("wfErr_"):
            literals.append(f"{where}:{line} 写死了一句话:{first.value}")
    assert not literals, "\n".join(literals)


def test_用到的每个_key_都有中英两份() -> None:
    from app.core.i18n import LOCALES, MESSAGES

    used = {
        first.value
        for _where, _line, first in _raised_messages()
        if isinstance(first, ast.Constant) and str(first.value).startswith("wfErr_")
    }
    assert len(used) >= 50, "扫描没扫到东西,多半是异常改了名字"
    missing = [key for key in sorted(used) if not all(MESSAGES.get(key, {}).get(locale) for locale in LOCALES)]
    assert not missing, f"这些失败原因缺翻译:{missing}"


def test_失败原因按读的人的语言翻() -> None:
    """端到端:同一条失败,中文界面和英文界面读到的是各自的语言。"""
    from app.api.schemas import JobOut
    from app.core.i18n import set_current_locale
    from app.db.models import Job, now

    job = Job(
        id="j1", workspace_id="w", kind="workflow", status="failed", progress=1.0,
        message="", message_key="", message_params={}, payload={}, result={},
        error="节点类型 demo 没有执行器", error_key="wfErr_noExecutor", error_params={"type": "demo"},
        created_at=now(), updated_at=now(),
    )
    try:
        set_current_locale("en")
        assert JobOut.model_validate(job).error == "No executor for node type demo"
        set_current_locale("zh")
        assert JobOut.model_validate(job).error == "节点类型 demo 没有执行器"
    finally:
        set_current_locale("zh")


def test_领域异常自己就说得出缺省语言那一句() -> None:
    """`str(exc)` 给的是缺省语言那句话 —— 日志、拼进别的错误里、直接读库的脚本都读它。"""
    from app.domain.jobs import blame
    from app.domain.workflows import WorkflowDomainError

    exc = WorkflowDomainError("wfErr_noExecutor", params={"type": "demo"})
    assert str(exc) == "节点类型 demo 没有执行器"
    assert blame(exc) == {
        "error": "节点类型 demo 没有执行器",
        "error_key": "wfErr_noExecutor",
        "error_params": {"type": "demo"},
    }
    #: 别的领域抛过来的原话没有 key —— 只留那句话,我们翻不了它。
    assert blame(ValueError("对方服务 502"))["error_key"] == ""
