"""文本处理节点:说的和做的对上。

- 查找串为空时,replace 在**每个字符之间**插一遍替换串("ab" → "XaXbX"),正则永远匹配空串。
- op=length 时 `length` 输出算的是结果串 "12" 的长度(2)。
- 正则写错抛的是 re 的英文原话。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.db.models import Workflow
from app.domain.workflows import NODE_TYPES, WorkflowDomainError, validate_graph
from app.domain.workflows.engine import execute_graph
from tests.util import fresh_client


def _wf_id() -> str:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="节点", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        return workflow.id


def _node(node_type: str, config: dict, params: dict | None = None) -> dict:
    """真跑一遍引擎:开始节点 → 这一个节点。"""
    graph = {
        "nodes": [{"id": "start", "type": "start", "config": {}}, {"id": "n", "type": node_type, "config": config}],
        "edges": [{"id": "e1", "source": "start", "target": "n"}],
    }
    context, _ = execute_graph(graph, wf_id=_wf_id(), params=params or {})
    return context["n"]


# ---- 文本处理 ----

@pytest.mark.parametrize("op", ["replace", "regex_extract"])
def test_查找串为空_报错而不是每个字符之间插一遍(op: str) -> None:
    with pytest.raises(WorkflowDomainError) as caught:
        _node("text_transform", {"text": "ab", "op": op, "find": "", "replace": "X"})
    assert caught.value.key == "wfErr_textFindEmpty"
    # 声明里也标了:运行前的校验就拦下,不必等跑到它。
    errors = validate_graph({
        "nodes": [{"id": "start", "type": "start", "config": {}},
                  {"id": "n", "type": "text_transform", "config": {"text": "ab", "op": op}}],
        "edges": [{"id": "e1", "source": "start", "target": "n"}],
    })
    assert errors == ["「文本处理」缺少必填:查找"], errors


def test_其它处理不要求填查找串() -> None:
    assert _node("text_transform", {"text": " ab ", "op": "trim"})["text"] == "ab"
    assert NODE_TYPES["text_transform"]["config"]["find"]["active_when"] == {"op": ["replace", "regex_extract"]}


def test_取长度_length_是原文的长度() -> None:
    out = _node("text_transform", {"text": "一二三四五六七八九十一二", "op": "length"})
    assert out == {"text": "12", "length": 12}


def test_正则写错_用工作流的话说出是哪个正则() -> None:
    with pytest.raises(WorkflowDomainError) as caught:
        _node("text_transform", {"text": "ab", "op": "regex_extract", "find": "(a"})
    assert caught.value.key == "wfErr_textRegexInvalid"
    assert caught.value.params["pattern"] == "(a"
