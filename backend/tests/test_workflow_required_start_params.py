"""开始节点点名为必填的参数(`required_params`),空着运行前就拦住。

官方模板里要用户自己填的东西(商品名、卖点、主题、素材标签)住在开始节点的参数里,由别的节点用 `{{start.x}}`
引用 —— 而引用本身在必填检查里算"填了"。于是空着也能启动:模型对着空白写脚本,后面的付费生成照样扣费;
此前模板索性在那一格里写一句「请把这里改成……」,没改就跑的话这句话被当成了真参数。
"""

from __future__ import annotations

from app.domain.workflows import validate_graph, with_run_params
from app.domain.workflows.templates import TEMPLATE_CATALOG, ModelChoice
from app.domain.workflows.templates_business import (
    fabric_lookbook_graph,
    footage_montage_graph,
    product_on_model_graph,
    product_pitch_short_graph,
)
from tests.util import fresh_client


def _graph(required: str, **params: object) -> dict:
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": params, "required_params": required}},
            {"id": "t", "type": "template", "config": {"template": "{{start.topic}}"}},
        ],
        "edges": [{"id": "e", "source": "start", "target": "t"}],
    }


def test_点名的参数空着就报_说清是哪一个() -> None:
    assert validate_graph(_graph("topic, tag", topic="面馆", tag="  ")) == ["节点 start 缺少必填配置 params.tag"]
    #: 0 和 false 是值,不是空。
    assert validate_graph(_graph("topic，count", topic="面馆", count=0)) == []
    #: 没点名的参数照旧可以空着。
    assert validate_graph(_graph("", topic="")) == []


def test_这一次运行带了值就不拦() -> None:
    graph = _graph("topic", topic="")
    assert validate_graph(graph) != []
    assert validate_graph(with_run_params(graph, {"topic": "面馆"})) == []
    assert graph["nodes"][0]["config"]["params"] == {"topic": ""}, "只叠在这一次的副本上,不改存着的图"


def test_官方模板把要用户填的那几格都点名了_而且默认是空的() -> None:
    chat, image, video = ModelChoice(model="c"), ModelChoice(model="i"), ModelChoice()
    expected = {
        "product_on_model": (product_on_model_graph(chat=chat, image=image, video=video), {"product_name", "product_brief"}),
        "product_pitch_short": (product_pitch_short_graph(chat=chat, image=image, voice_id="v"), {"product_name", "selling_points"}),
        "product_pitch_presenter": (product_pitch_short_graph(chat=chat, image=image, presenter=True),
                                    {"product_name", "selling_points"}),
        "fabric_lookbook": (fabric_lookbook_graph(chat=chat, image=image), {"fabric_name"}),
        "footage_montage": (footage_montage_graph(chat=chat, voice_id=""), {"topic", "footage_tag"}),
    }
    for template_id, (graph, names) in expected.items():
        start = next(node for node in graph["nodes"] if node["type"] == "start")["config"]
        assert {one.strip() for one in start["required_params"].split(",")} == names, template_id
        #: 默认空着 —— 不放「请把这里改成……」那种会被当成真参数的说明文字。
        assert all(start["params"][name] == "" for name in names), template_id
        errors = validate_graph(graph)
        assert all(f"params.{name}" in "".join(errors) for name in names), (template_id, errors)
    assert {card["id"] for card in TEMPLATE_CATALOG} >= set(expected)


def test_按下运行时空着拦下_带着参数跑就过了这一关() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    made = client.post("/api/workflows", json={"workspace_id": workspace, "name": "带货", "template_id": "product_pitch_short"})
    assert made.status_code == 200, made.text
    blank = client.post(f"/api/workflows/{made.json()['id']}/run", json={"params": {}})
    assert blank.status_code == 422 and "params.selling_points" in blank.json()["detail"], blank.text
    given = client.post(f"/api/workflows/{made.json()['id']}/run",
                        json={"params": {"product_name": "开衫", "selling_points": "不起球"}})
    #: 商品图还没挑,照样拦 —— 但不再是因为这两个参数。
    assert given.status_code == 422 and "params." not in given.json()["detail"], given.text
