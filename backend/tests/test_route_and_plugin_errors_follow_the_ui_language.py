"""路由、插件、笔记、AI 调用这些报错跟着界面语言走。

此前它们是写死的中文句子:英文界面里点一下删评论、装一个坏插件、存一份过期的笔记,弹出来的都是
中文。现在领域错误带文案 key(`LocalizedError`),路由里直接写的报错用 `tr`,都按**这次请求**的
Accept-Language 翻;上游的原话(插件进程、MCP 服务说的)原样放进翻好的句子里,不翻也不猜。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.i18n import set_current_locale
from tests.util import fresh_client

EN = {"Accept-Language": "en-US"}
ZH = {"Accept-Language": "zh-CN"}


@pytest.fixture(autouse=True)
def _reset_locale():
    yield
    set_current_locale("zh")


def test_a_route_level_404_answers_in_the_requested_language() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    en = client.delete(f"/api/comments/nope?workspace_id={ws}", headers=EN)
    assert en.status_code == 404
    assert en.json()["detail"] == "Comment not found."
    zh = client.delete(f"/api/comments/nope?workspace_id={ws}", headers=ZH)
    assert zh.json()["detail"] == "评论不存在"


def test_a_domain_conflict_answers_in_the_requested_language() -> None:
    """笔记的 409 走 main.py 的领域异常出口 —— `str(exc)` 本身就跟着请求语言。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    note = client.post("/api/notes", json={"workspace_id": ws, "title": "t", "markdown": "a"}).json()
    body = {**note, "base_revision": 1, "markdown": "b"}
    assert client.patch(f"/api/notes/{note['id']}", json=body).status_code == 200
    stale = client.patch(f"/api/notes/{note['id']}", json=body, headers=EN)
    assert stale.status_code == 409
    assert stale.json()["detail"] == "The note was changed elsewhere. Keep your draft and reload."


def test_workflow_errors_raised_in_a_route_are_rendered_for_the_reader() -> None:
    """WorkflowDomainError 的 `str(exc)` 是缺省语言那一句(给落库用);路由按请求语言重翻 key。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    body = {"workspace_id": ws, "name": "x", "template_id": "anything", "graph": {"nodes": [], "edges": []}}
    en = client.post("/api/workflows", json=body, headers=EN)
    assert en.status_code == 422
    assert en.json()["detail"] == "When creating a workflow, send either a template or a custom graph, not both."


def test_plugin_runtime_errors_follow_the_language_and_keep_the_plugins_own_words(tmp_path: Path) -> None:
    from app.domain.plugins.runtime import PluginRuntimeError, execute_tool

    plugin_dir = tmp_path / "p"
    plugin_dir.mkdir()
    with pytest.raises(PluginRuntimeError) as missing:
        execute_tool(plugin_dir, "nope.py", "t", {})
    set_current_locale("en")
    assert str(missing.value) == "Entry script not found: nope.py"
    set_current_locale("zh")
    assert str(missing.value) == "entry 脚本不存在: nope.py"

    # 插件自己报的原因:原样给,不套进任何一种语言的句子里。
    (plugin_dir / "main.py").write_text(
        'import json, sys\nprint(json.dumps({"ok": False, "error": "quota exhausted (upstream)"}))\n', encoding="utf-8"
    )
    with pytest.raises(PluginRuntimeError) as said:
        execute_tool(plugin_dir, "main.py", "t", {})
    set_current_locale("en")
    assert str(said.value) == "quota exhausted (upstream)"


def test_ai_call_errors_translate_the_label_too() -> None:
    """`label` 说的是「哪一次调用」:给 key 就跟着语言翻,给一句现成的话就原样用。"""
    from app.domain.ai_chat import AiChatError

    keyed = AiChatError("aiChatErr_networkRetried", label="aiChat_labelDefault", tries=3, detail="timed out")
    literal = AiChatError("aiChatErr_failed", label="Board copy", detail="boom")
    set_current_locale("en")
    assert str(keyed) == "AI call failed (network/connection, still failing after 3 retries): timed out"
    assert str(literal) == "Board copy failed: boom"
    set_current_locale("zh")
    assert str(keyed) == "AI 调用失败(网络/连接,已重试 3 次仍失败):timed out"


def test_connection_errors_speak_through_whatever_error_type_the_caller_chose() -> None:
    """require_connection 用调用方给的错误类型报错:带 key 的收 key,别的收一句按当前语言翻好的话。"""
    from app.domain.ai_chat import AiChatError
    from app.domain.providers import _connection_error

    set_current_locale("en")
    keyed = _connection_error(AiChatError, "providerErr_noKey", name="Kimi")
    assert str(keyed) == "Provider \"Kimi\" doesn't have your key yet. Add it in Settings first."
    plain = _connection_error(RuntimeError, "providerErr_noConnection")
    assert str(plain).startswith("No AI provider connection is available")
