"""`one_of`:同组的字段恰好填一个 —— 运行前就报,不等执行到那一步。

浏览器上传的素材(asset_id)和本机路径(file_path)是一组。此前两个都填时执行器悄悄挑了路径:先填路径
试跑、后来把素材接到上游却忘了清路径,每次运行传的都是那份旧的本地文件,运行照样显示成功。
"""

from __future__ import annotations

from app.domain.workflows import NODE_TYPES, validate_graph


def _graph(upload_config: dict, *, bound: str = "") -> dict:
    edges = [{"id": "e1", "source": "start", "target": "up"}]
    if bound:
        edges.append({"id": "e2", "source": "start", "target": "up", "kind": "data", "target_input": bound})
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "up", "type": "browser_upload", "config": {"session": "{{start.session}}", **upload_config}},
        ],
        "edges": edges,
    }


def _one_of_errors(graph: dict, **kwargs) -> list[str]:
    return [error for error in validate_graph(graph, **kwargs) if "asset_id / file_path" in error]


def test_上传节点的素材和路径声明成一组() -> None:
    config = NODE_TYPES["browser_upload"]["config"]
    assert config["asset_id"]["one_of"] == config["file_path"]["one_of"]


def test_恰好填一个才过() -> None:
    assert _one_of_errors(_graph({"asset_id": "a1"})) == []
    assert _one_of_errors(_graph({"file_path": "/tmp/x.mp4"})) == []
    assert _one_of_errors(_graph({"asset_id": "{{start.asset_id}}"})) == []


def test_两个都填或都没填_运行前就报() -> None:
    assert _one_of_errors(_graph({"asset_id": "a1", "file_path": "/tmp/x.mp4"})) == [
        "节点 up 的 asset_id / file_path 只能填一个"
    ]
    assert _one_of_errors(_graph({})) == ["节点 up 的 asset_id / file_path 要填一个"]


def test_接了上游也算填了() -> None:
    assert _one_of_errors(_graph({}, bound="asset_id")) == []
    assert _one_of_errors(_graph({"file_path": "/tmp/x.mp4"}, bound="asset_id")) == [
        "节点 up 的 asset_id / file_path 只能填一个"
    ]


def test_保存时不拦_还没配完是常态() -> None:
    assert _one_of_errors(_graph({}), require_config=False) == []
    assert _one_of_errors(_graph({"asset_id": "a1", "file_path": "/tmp/x.mp4"}), require_config=False) == []
