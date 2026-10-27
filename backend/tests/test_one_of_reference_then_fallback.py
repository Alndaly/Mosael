"""one_of 认「引用在前、兜底在后」;「只填一样」那次迁移删掉的兜底从修订历史里找回来。

## 现场

「点击」的选择器写 `{{上游.选择器}}`、文字填一个兜底 —— 上游给空时执行器按顺序落到文字那格(点击先认选择器、
等待按「元素 → 网址 → 文字」)。one_of 却把它判成「只能填一个」,1.8.1 的迁移照这条规矩把兜底删了。

规矩(和前端 analyze / fieldActivation 同一条):同组按声明顺序,最后一个填了的之前,填了的每一格都是整格一条
引用(`^\\s*\\{\\{\\s*[\\w.-]+\\s*\\}\\}\\s*$`)或接了数据边,就放行。两样都给就报错的组(浏览器上传,
`one_of_strict`)照旧恰好一个。
"""

from __future__ import annotations

import pytest

from app.domain.workflows import validate_graph


def _graph(*nodes: dict, edges: list | None = None) -> dict:
    return {
        "nodes": [{"id": "start", "type": "start", "config": {"params": {"sel": "#x", "url": "/done"}}},
                  {"id": "t", "type": "template", "config": {"template": "#a"}}, *nodes],
        "edges": edges or [],
    }


def _errors(node: dict, edges: list | None = None) -> list[str]:
    """这一个节点的运行前报错。报错按节点的标题说,给它起个认得出的名字再按名字挑。"""
    named = {**node, "name": f"节点{node['id']}"}
    return [one for one in validate_graph(_graph(named, edges=edges)) if f"「节点{node['id']}」" in one]


@pytest.mark.parametrize(("config", "ok"), [
    ({"selector": "{{t.text}}", "text": "去"}, True),
    ({"selector": " {{ t.text }} ", "text": "去"}, True),
    ({"selector": "#go", "text": "去"}, False),
    ({"selector": "#go", "text": "{{t.text}}"}, False),
    ({"selector": "{{t.text}} 后面还有字", "text": "去"}, False),
])
def test_点击_引用在前兜底在后放行_字面量在前不行(config: dict, ok: bool) -> None:
    errors = _errors({"id": "c", "type": "browser_click", "config": {"session": "s", **config}})
    assert (not errors) is ok, errors


def test_等待_前两格都是引用或接了数据边_最后一格兜底() -> None:
    edges = [{"id": "d", "source": "t", "target": "w", "kind": "data", "source_output": "text", "target_input": "url_contains"}]
    assert not _errors({"id": "w", "type": "browser_wait",
                        "config": {"session": "s", "selector": "{{start.sel}}", "url_contains": "", "text": "完成"}},
                       edges)
    assert _errors({"id": "w", "type": "browser_wait",
                    "config": {"session": "s", "selector": "{{start.sel}}", "url_contains": "/done", "text": "完成"}})


def test_浏览器上传两样都给就报错_不认兜底() -> None:
    errors = _errors({"id": "u", "type": "browser_upload",
                      "config": {"session": "s", "asset_id": "{{t.text}}", "file_path": "/tmp/a.png"}})
    assert errors == ["「节点u」的 素材 / 文件路径 只能填一个"]
