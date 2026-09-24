"""智能体、时间线、工作流、沙箱、白模渲染的报错:英文界面读到的是英文。

此前这些错误是写死的中文句子,英文界面里原样弹出来。现在它们带文案 key,`str(exc)` 按当时的
语言翻(请求里是请求方的语言,后台线程里是缺省语言)。这里挑几条有代表性的,断言英文那一句。
"""

from __future__ import annotations

import threading
from contextlib import contextmanager

import pytest

from app.core.i18n import DEFAULT_LOCALE, set_current_locale


@contextmanager
def english():
    set_current_locale("en")
    try:
        yield
    finally:
        set_current_locale(DEFAULT_LOCALE)


def test_问题卡的报错_英文() -> None:
    from app.domain.agent import questions

    with pytest.raises(questions.QuestionError) as raised:
        questions.normalize([{"question": "Which one?", "options": [{"label": "A"}]}])
    assert raised.value.key == "questionErr_tooFewOptions"
    with english():
        assert str(raised.value) == '"Which one?" needs at least 2 options — with only one there is nothing to ask.'
    # 缺省语言那一句和此前写死的一字不差。
    assert str(raised.value) == "「Which one?」至少要给 2 个选项 —— 只有一个的话不必问"
    # 仍然是 ValueError:路由里 `except ValueError` 照样接得住。
    assert isinstance(raised.value, ValueError)


def test_计划与判断者的报错_英文() -> None:
    from app.domain.agent import judge, plan

    with pytest.raises(ValueError) as raised:
        plan.normalize([])
    with english():
        assert str(raised.value) == "A plan needs at least one step."

    with pytest.raises(ValueError) as raised:
        judge._parse('{"reason": "x"}', model="m")
    with english():
        assert str(raised.value) == 'The judge\'s answer has no boolean "allow": {"reason": "x"}'


def test_登录失败原因按读的时候的语言翻() -> None:
    """登录在后台线程里失败(看门狗超时),翻译发生在轮询的那次请求里。"""
    from app.domain.agent import login

    session = login.LoginSession(login_id="l", profile_id="p")
    login._finish(session, "error", "agentErr_loginTimeout")
    assert session.error == "授权超时,请重新发起登录"
    with english():
        assert session.error == "Authorization timed out. Start the sign-in again."

    # sidecar 回的原话不是 key:原样给,不当模板填。
    upstream = login.LoginSession(login_id="l2", profile_id="p")
    login._finish(upstream, "error", "device code expired {oops}")
    with english():
        assert upstream.error == "device code expired {oops}"


def test_智能体回合的线程带着发消息的人的语言(monkeypatch) -> None:
    """失败时写进对话里的那句话在工作线程里生成 —— 线程不继承请求的 ContextVar。"""
    from app.core.i18n import get_current_locale
    from app.domain.agent import host

    seen: list[str] = []
    done = threading.Event()

    def fake_turn(session_id: str, prompt: str, token: str) -> None:
        seen.append(get_current_locale())
        done.set()

    monkeypatch.setattr(host, "_run_turn_thread", fake_turn)
    with english():
        host._start_turn("s-locale", "hi", "tok")
    done.wait(timeout=5)
    assert seen == ["en"]


def test_时间线撤销的报错_英文() -> None:
    from app.domain.sequences.errors import SequenceDomainError
    from app.domain.sequences.undo import _pair

    with pytest.raises(SequenceDomainError) as raised:
        _pair("no-such-op")
    with english():
        assert str(raised.value) == '"no-such-op" can\'t be undone.'


def test_工作流错误在请求里按请求语言说() -> None:
    """编辑器里同步报的图操作错误,路由拿 str(exc) 当 detail —— 此前永远是缺省语言。"""
    from app.domain.workflows import WorkflowDomainError
    from app.domain.workflows.graph_ops import apply_graph_ops

    with pytest.raises(WorkflowDomainError) as raised:
        apply_graph_ops({"nodes": [], "edges": []}, [{"kind": "explode"}])
    assert str(raised.value) == "不支持的图操作:explode"
    with english():
        assert str(raised.value) == "Unsupported graph operation: explode"


def test_转述别的领域的错误时带着_key() -> None:
    """`WorkflowDomainError.from_error` 留住 key/参数 —— 落库的失败原因才能按读的人翻。"""
    from app.domain.sandbox import SandboxUnavailable
    from app.domain.workflows import WorkflowDomainError

    wrapped = WorkflowDomainError.from_error(SandboxUnavailable("sandboxErr_dockerMissing"))
    assert wrapped.key == "sandboxErr_dockerMissing"
    with english():
        assert str(wrapped) == "Install and start Docker to run code."

    plain = WorkflowDomainError.from_error(RuntimeError("upstream said {no}"))
    assert plain.key == ""
    assert str(plain) == "upstream said {no}"


def test_没有沙箱时的报错_英文(monkeypatch) -> None:
    from app.domain import sandbox

    monkeypatch.setattr(sandbox, "_BACKENDS", ())
    sandbox.active_backend.cache_clear()
    try:
        with pytest.raises(sandbox.SandboxUnavailable) as raised:
            sandbox.run_code("output = 1", {})
    finally:
        sandbox.active_backend.cache_clear()
    with english():
        assert str(raised.value).startswith("No code sandbox is available on this machine")


def test_Schema_没被强制时换一句话() -> None:
    from app.domain.workflows.executors.ai import _BadJson, _json_result

    config = {
        "response_format": "json_schema",
        "json_schema": {"type": "object", "properties": {"n": {"type": "number", "minimum": 2}}, "required": ["n"]},
    }
    with pytest.raises(_BadJson) as raised:
        _json_result('{"n": 1}', '{"n": 1}', config, "m", used_tier="json_object")
    assert raised.value.key == "wfErr_jsonSchemaMismatchUnenforced"
    assert raised.value.params["tier"] == "json_object"


def test_白模渲染与导入模型的报错_英文() -> None:
    from app.domain.scene_render.model_mesh import UnsupportedModel, _refuse_compressed

    with pytest.raises(UnsupportedModel) as raised:
        _refuse_compressed({"extensionsRequired": ["KHR_draco_mesh_compression"]})
    with english():
        assert str(raised.value) == (
            "The model uses Draco mesh compression, which the graybox renderer can't decode. "
            "Export the GLB with compression turned off."
        )


def test_接口按_Accept_Language_回英文() -> None:
    """端到端:撤销一个没有历史的序列,英文界面拿到英文。"""
    from tests.util import fresh_client

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": workspace["id"], "name": "P"}).json()
    sequence = client.post(
        "/api/sequences", json={"workspace_id": workspace["id"], "project_id": project["id"], "name": "S"}
    ).json()
    response = client.post(f"/api/sequences/{sequence['id']}/undo", headers={"Accept-Language": "en"})
    assert response.status_code in (400, 409, 422), response.text
    assert response.json()["detail"] == "Nothing to undo."
