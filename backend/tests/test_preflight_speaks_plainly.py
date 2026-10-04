"""运行前检查的报错说人话:用节点的标题(没起名就是节点类型的显示名)和字段在界面上的名字,并跟随界面语言。

现场(上一轮工作流全量实测):「节点 shoot_beats 的循环体里:节点 beat_frame 缺少必填配置 provider」—— 只有中文,
说的是节点 id 和配置的原名,而画布上那两个节点叫「逐镜生成」「生成画面」、那一格叫「生成模型」。画布的就绪清单早就是
人话(「逐镜生成 › 生成画面 · 缺少必填:生成模型」),两边对同一个问题说两种话。

每条都断言**整句**:节点名就是那个节点的标题、字段名就是那一格的界面标签,英文界面整句是英文。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.core.i18n import set_current_locale
from app.domain.workflows import WorkflowDomainError, validate_graph
from app.domain.workflows.engine import check_runnable
from tests.util import fresh_client, user_id


@pytest.fixture(autouse=True)
def _locale():
    set_current_locale("zh")
    yield
    set_current_locale("zh")


def _start(params: dict | None = None) -> dict:
    return {"id": "start", "type": "start", "name": "填主题", "config": {"params": params or {"topic": "猫"}}}


def _shoot_beats(body_nodes: list[dict], **config) -> dict:
    return {
        "id": "shoot_beats", "type": "loop_foreach", "name": "逐镜生成",
        "config": {"items": "{{start.topic}}", "body": {"nodes": body_nodes, "edges": []}, **config},
    }


def _graph(*nodes: dict, edges: list[dict] | None = None) -> dict:
    ids = [node["id"] for node in nodes]
    return {
        "nodes": list(nodes),
        "edges": edges if edges is not None else [
            {"id": f"e{index}", "source": ids[index - 1], "target": ids[index]} for index in range(1, len(ids))
        ],
    }


def _errors(graph: dict) -> list[str]:
    return validate_graph(graph)


# ---- 现场那一句 ----

USER_CASE = _graph(
    _start(),
    _shoot_beats([{"id": "beat_frame", "type": "ai_generate", "name": "生成画面", "config": {"prompt": "{{loop.item}}"}}]),
)


def test_现场那一句_用标题和字段的界面名字_说清在哪一层() -> None:
    assert _errors(USER_CASE) == ["「逐镜生成 › 生成画面」缺少必填:生成模型"]


def test_英文界面整句是英文() -> None:
    set_current_locale("en")
    assert _errors(USER_CASE) == ["“逐镜生成 › 生成画面” is missing a required field: Generation model"]


def test_经运行接口按请求的语言回() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    saved = client.post("/api/workflows", json={"workspace_id": ws, "name": "W", "graph": USER_CASE}).json()
    zh = client.post(f"/api/workflows/{saved['id']}/run", json={"params": {}}, headers={"Accept-Language": "zh-CN"})
    en = client.post(f"/api/workflows/{saved['id']}/run", json={"params": {}}, headers={"Accept-Language": "en-US"})
    assert zh.status_code == en.status_code == 422
    assert zh.json()["detail"] == "「逐镜生成 › 生成画面」缺少必填:生成模型"
    assert en.json()["detail"] == "“逐镜生成 › 生成画面” is missing a required field: Generation model"


# ---- 没起名的节点用节点类型的显示名;字段用界面标签 ----


def test_没起名的节点用显示名_字段用界面标签() -> None:
    graph = _graph(_start(), {"id": "n1", "type": "http_request", "config": {"method": "GET"}})
    assert _errors(graph) == ["「HTTP 请求」缺少必填:网址"]
    set_current_locale("en")
    assert _errors(graph) == ["“HTTP request” is missing a required field: URL"]


def test_只能填一个和要填一个_列出那一组字段的界面名字() -> None:
    both = _graph(_start(), {"id": "c", "type": "browser_click", "name": "点登录", "config": {
        "session": "s", "selector": "#login", "text": "登录"}})
    none = _graph(_start(), {"id": "c", "type": "browser_click", "name": "点登录", "config": {"session": "s"}})
    assert "「点登录」的 元素选择器 / 文本 只能填一个" in _errors(both)
    assert "「点登录」的 元素选择器 / 文本 要填一个" in _errors(none)
    set_current_locale("en")
    assert "“点登录”: fill in one of Selector / Text" in _errors(none)


def test_开始节点勾了必填的参数空着() -> None:
    graph = _graph({"id": "start", "type": "start", "name": "填主题",
                    "config": {"params": {"topic": ""}, "required_params": ["topic"]}})
    assert _errors(graph) == ["「填主题」缺少必填:topic"]


# ---- 引用 ----


def test_引用了不存在的节点_说是哪个节点引用的_引用按名字说() -> None:
    graph = _graph(_start(), {"id": "t", "type": "template", "name": "拼文案", "config": {"template": "{{scirpt.text}}"}})
    assert _errors(graph) == ["「拼文案」引用了不存在的节点:scirpt · text"]


def test_引用了开始节点没有的参数() -> None:
    graph = _graph(_start(), {"id": "t", "type": "template", "name": "拼文案", "config": {"template": "{{start.tpoic}}"}})
    assert _errors(graph) == ["「拼文案」引用的开始参数不存在:填主题 · tpoic。在开始节点的参数里声明它,或运行时传进来"]


def test_循环体里引用外面的节点() -> None:
    graph = _graph(_start(), _shoot_beats([
        {"id": "say", "type": "template", "name": "拼台词", "config": {"template": "{{start.topic}} {{loop.item}}"}},
    ]))
    assert _errors(graph) == [
        "「逐镜生成 › 拼台词」引用了这一层看不见的 start:这里只看得见 loop、input 和同一层的节点,外面的值经容器的「输入」传进来"
    ]


def test_循环体里引用作用域没有的字段() -> None:
    graph = _graph(_start(), _shoot_beats([
        {"id": "say", "type": "template", "name": "拼台词", "config": {"template": "{{loop.itme}}"}},
    ]))
    assert _errors(graph) == ["「逐镜生成 › 拼台词」用到的 loop · itme 这里没有:只提供 loop · item、loop · index"]


def test_循环体是空的_和输出节点放进循环体() -> None:
    empty = _graph(_start(), _shoot_beats([]))
    assert _errors(empty) == ["「逐镜生成」里面还没有节点:至少放一个"]
    with_output = _graph(_start(), _shoot_beats([{"id": "o", "type": "output", "name": "交付", "config": {}}]))
    assert "「逐镜生成 › 交付」:「输出」节点只在最外层算数,放在循环体或子图里,调用方拿不到它的产出" in _errors(with_output)


def test_一定不会跑的节点被引用_两边都用标题() -> None:
    graph = {
        "nodes": [
            _start(),
            {"id": "props", "type": "template", "name": "可用的 3D 道具", "config": {"template": "椅子"}},
            {"id": "stage", "type": "template", "name": "布景提示词", "config": {"template": "道具:{{props.text}}"}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "stage"}],
    }
    (message,) = _errors(graph)
    assert message.startswith("「布景提示词」引用了 可用的 3D 道具 · 文本,可「可用的 3D 道具」没接进流程")


def test_开始节点的数目() -> None:
    assert _errors({"nodes": [{"id": "t", "type": "template", "config": {"template": "x"}}], "edges": []}) == [
        "缺少开始节点,无法运行"
    ]
    two = _graph(_start(), {"id": "s2", "type": "start", "config": {"params": {}}})
    assert "只能有一个开始节点,现在有 2 个" in _errors(two)


def test_认不出的节点类型() -> None:
    graph = _graph(_start(), {"id": "x", "type": "teleport", "name": "传送", "config": {}})
    assert _errors(graph) == ["「传送」:未知的节点类型 teleport"]


def test_子工作流跑不起来时_说的是调用它的那个节点的标题() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    child = client.post("/api/workflows", json={"workspace_id": ws, "name": "子流程", "graph": _graph(
        _start(), {"id": "n1", "type": "http_request", "config": {}})}).json()
    graph = _graph(_start(), {"id": "call", "type": "call_workflow", "name": "调子流程",
                              "config": {"workflow_id": child["id"], "inputs": {}}})
    with SessionLocal() as db:
        with pytest.raises(WorkflowDomainError) as caught:
            check_runnable(db, graph, {}, user_id(), workspace_id=ws)
    assert str(caught.value) == "「调子流程」调用的工作流「子流程」现在跑不起来:「HTTP 请求」缺少必填:网址"
