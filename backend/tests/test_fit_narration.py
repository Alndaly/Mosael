"""口播按时长收紧:脚本写出来之后用代码量每一段念出来要多久,超了就让模型只重写那几段(最多两轮);
还超的照旧交给时间线那一步加速 / 裁剪,并说清楚是哪几段。

隔离环境里真跑 10 秒的带货口播:脚本给 2 秒那一拍写了 12 个字(每秒约 4 个字,该是 8 个字以内),画外音念不完,
加速到 1.5 倍还多 0.08 秒、尾巴被裁。提示词里写了「宁短勿长」,模型照样超 —— 这条约束得由代码量。
"""

from __future__ import annotations

from typing import Any

import jsonschema
import pytest

from app.core.unit_of_work import unit_of_work
from app.db.models import Workflow
from app.domain.workflows.executors import ai as ai_nodes
from app.domain.workflows.engine import execute_graph
from app.domain.workflows.executors.ai import speech_seconds
from tests.util import fresh_client


def _workflow() -> str:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with unit_of_work() as db:
        workflow = Workflow(workspace_id=ws, name="W", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        return workflow.id


BEATS = [
    {"narration": "夏天久坐也不闷", "seconds": 3, "caption": "久坐不闷"},
    {"narration": "五五亚麻加棉,透气看得见", "seconds": 2, "caption": "透气"},
    {"narration": "点下方链接", "seconds": 2, "caption": "链接"},
]


class _Writer:
    """假的大模型:按给它的那一轮交回改写。先按节点给的 JSON Schema 校验一遍形状。"""

    def __init__(self, rounds: list[dict[int, str]]) -> None:
        self.rounds = rounds
        self.prompts: list[str] = []

    def __call__(self, db, scope, config: dict[str, Any]) -> dict[str, Any]:
        self.prompts.append(config["prompt"])
        answer = {"rewrites": [{"index": index, "narration": text} for index, text in self.rounds[len(self.prompts) - 1].items()]}
        jsonschema.validate(answer, config["json_schema"])
        return {"text": "", "json": answer, "response_format_used": "json_schema"}


def _fit(monkeypatch, writer: _Writer, beats: list[dict[str, Any]] = BEATS) -> dict[str, Any]:
    monkeypatch.setattr(ai_nodes, "llm", writer)
    node = {"id": "fit", "type": "fit_narration", "config": {
        "items": beats, "text_field": "narration", "seconds_field": "seconds", "profile_id": "chat", "model": "m",
    }}
    context, _ = execute_graph({"nodes": [node], "edges": []}, wf_id=_workflow(), entry_is_root=True)
    return context["fit"]


def test_念出来要多久_中文每秒约四个字_英文每秒约两个半词() -> None:
    assert speech_seconds("五五亚麻加棉,透气看得见") == pytest.approx(11 / 4)
    assert speech_seconds("Breathable linen for long days") == pytest.approx(5 / 2.5)


def test_都念得完_不调大模型_原样交出(monkeypatch) -> None:
    writer = _Writer([])
    out = _fit(monkeypatch, writer, [BEATS[0], BEATS[2]])
    assert writer.prompts == []
    assert out["items"] == [BEATS[0], BEATS[2]] and out["rewritten"] == 0 and out["over"] == [] and out["note"] == ""


def test_超了的那一段让模型重写_只改那一段(monkeypatch) -> None:
    writer = _Writer([{2: "亚麻加棉,透气"}])
    out = _fit(monkeypatch, writer)
    assert len(writer.prompts) == 1
    assert "第 2 段" in writer.prompts[0] and "2 秒" in writer.prompts[0] and "8 个字" in writer.prompts[0], writer.prompts[0]
    assert "夏天久坐也不闷" not in writer.prompts[0], "念得完的不发给它"
    assert [beat["narration"] for beat in out["items"]] == ["夏天久坐也不闷", "亚麻加棉,透气", "点下方链接"]
    assert out["items"][1]["caption"] == "透气", "别的字段原样"
    assert (out["rewritten"], out["over"]) == (1, [])
    assert "第 2 段" in out["note"] and "改短" in out["note"], out["note"]


def test_改了两轮还超_留着最短的那一版_说清楚会加速或裁掉(monkeypatch) -> None:
    writer = _Writer([{2: "五五亚麻加棉,透气又凉快看得见"}, {2: "亚麻加棉,透气看得见"}])
    out = _fit(monkeypatch, writer)
    assert len(writer.prompts) == 2, "最多两轮"
    assert out["items"][1]["narration"] == "亚麻加棉,透气看得见", "比原文短,就留它"
    assert out["over"] == [2]
    assert "第 2 段" in out["note"] and "加速" in out["note"] and "裁" in out["note"], out["note"]
