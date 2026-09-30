"""开始节点点名为必填的参数(`required_params`),空着运行前就拦住。

官方模板里要用户自己填的东西(商品名、卖点、主题、素材标签)住在开始节点的参数里,由别的节点用 `{{start.x}}`
引用 —— 而引用本身在必填检查里算"填了"。于是空着也能启动:模型对着空白写脚本,后面的付费生成照样扣费;
此前模板索性在那一格里写一句「请把这里改成……」,没改就跑的话这句话被当成了真参数。
"""

from __future__ import annotations

from app.domain.workflows import validate_graph, with_run_params


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
