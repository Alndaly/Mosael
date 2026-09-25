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


def test_报错里提到的字段名也跟着读的人的语言走() -> None:
    """知识库节点把「返回条数」「起始位置」这样的中文字段名当参数塞进报错:外层句子按 key 翻成了
    英文,嵌在里面的字段名还是中文。字段名也是文案 —— 以 key 的形状(fragment)进参数,
    落库之后、读的时候再和外层一起按读的人的语言翻。"""
    import re

    import pytest

    from app.api.schemas import JobOut
    from app.core.i18n import set_current_locale
    from app.db.models import Job, Workflow, now
    from app.domain.jobs import blame
    from app.domain.workflows import WorkflowDomainError
    from app.domain.workflows.executors.knowledge import note_search

    with pytest.raises(WorkflowDomainError) as caught:
        note_search(None, Workflow(workspace_id="w", name="W"), {"query": "x", "limit": "很多"})
    job = Job(
        id="j1", workspace_id="w", kind="workflow", status="failed", progress=1.0,
        message="", message_key="", message_params={}, payload={}, result={},
        created_at=now(), updated_at=now(), **blame(caught.value),
    )
    cjk = re.compile(r"[一-鿿]")
    try:
        set_current_locale("en")
        assert not cjk.search(str(caught.value)), str(caught.value)
        english = JobOut.model_validate(job).error
        assert not cjk.search(english) and "Limit" in english, english
        set_current_locale("zh")
        assert "条数上限" in JobOut.model_validate(job).error
    finally:
        set_current_locale("zh")


def test_数字字段填了不是数字_说是哪一格而不是一句_python_原话() -> None:
    """语速填了「快一点」(或者引用落成一段文字),此前执行体里一句 `float(...)` 直接抛出
    `could not convert string to float` —— 没有 key、英文、也不说是哪一格。声明成数字的字段,
    插值之后就按声明查一遍,所有节点一条规矩。"""
    from app.core.db import SessionLocal
    from app.db.models import Workflow
    from app.domain.workflows import WorkflowDomainError
    from app.domain.workflows.engine import execute_graph
    from tests.util import fresh_client

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="W", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        workflow_id = workflow.id
    graph = {
        "nodes": [{"id": "s", "type": "synthesize_speech",
                   "config": {"text": "你好", "engine": "edge", "voice": "v", "speed": "快一点"}}],
        "edges": [],
    }
    import pytest

    with pytest.raises(WorkflowDomainError) as caught:
        execute_graph(graph, wf_id=workflow_id, entry_is_root=True)
    assert caught.value.key == "wfErr_mustBeNumber"
    assert caught.value.params["field"] == {"__key": "wfField_speed", "params": {}}


def test_翻译转述上游的失败_带着上游的_key() -> None:
    """AI 翻译失败时此前是 `TranslateError(str(exc))`:上游那句话在抛出那一刻就翻成了字,key 丢了,
    落进任务失败原因的只剩缺省语言的一句话。"""
    import pytest

    from app.core.i18n import set_current_locale
    from app.domain import translate as tr
    from app.domain.ai_chat import AiChatError, ChatTarget

    def broken(*_args, **_kwargs):
        raise AiChatError("aiChatErr_network", label="aiChat_labelDefault", detail="timed out")

    target = ChatTarget(base_url="https://x", api_key="k", model="m")
    original = tr.chat
    tr.chat = broken
    try:
        with pytest.raises(tr.TranslateError) as caught:
            tr.ai_translate_with(target, "你好", "en")
    finally:
        tr.chat = original
    assert caught.value.key == "aiChatErr_network"
    try:
        set_current_locale("en")
        assert str(caught.value) == "AI call failed (network/connection): timed out"
    finally:
        set_current_locale("zh")


def test_报错里的一串名字按读的人的习惯连起来() -> None:
    """顿号是中文的连接号。此前列表在抛错的地方就用「、」连成了一个字符串,英文句子里夹着顿号。"""
    from app.core.i18n import set_current_locale
    from app.domain.jobs import blame
    from app.domain.workflows import WorkflowDomainError

    exc = WorkflowDomainError("pluginErr_manyInstances", params={"package": "p", "names": ["A 号", "B 号"]})
    assert blame(exc)["error_params"]["names"] == ["A 号", "B 号"], "列表该原样落库,读的时候再连"
    try:
        set_current_locale("en")
        assert "A 号, B 号" in str(exc)
        set_current_locale("zh")
        assert "A 号、B 号" in str(exc)
    finally:
        set_current_locale("zh")
