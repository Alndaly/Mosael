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


def _fit(monkeypatch, writer: _Writer, beats: list[dict[str, Any]] = BEATS, **config: Any) -> dict[str, Any]:
    monkeypatch.setattr(ai_nodes, "llm", writer)
    node = {"id": "fit", "type": "fit_narration", "config": {
        "items": beats, "text_field": "narration", "seconds_field": "seconds", "profile_id": "chat", "model": "m", **config,
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


def test_每一段一样长时直接给秒数_按它量_不读每段里的字段(monkeypatch) -> None:
    """带货口播「每一拍动起来」:每拍就是视频模型一段的长度(开始参数),脚本里没有各拍的 seconds。"""
    beats = [{"narration": "夏天久坐也不闷", "caption": "久坐不闷"}, {"narration": "五五亚麻加棉,透气看得见", "caption": "透气"}]
    writer = _Writer([{2: "亚麻加棉,透气"}])
    out = _fit(monkeypatch, writer, beats, seconds="2", seconds_field="")
    assert len(writer.prompts) == 1 and "第 2 段(2 秒" in writer.prompts[0], writer.prompts
    assert "夏天久坐也不闷" not in writer.prompts[0], "7 个字念 1.75 秒,放得进 2 秒"
    assert [beat["narration"] for beat in out["items"]] == ["夏天久坐也不闷", "亚麻加棉,透气"]
    #: 给了秒数就不看每段里写的:这里每段写着 9 秒(按它量就什么都不改),照样按 2 秒量、改短第 2 段。
    again = _Writer([{2: "亚麻加棉,透气"}])
    assert _fit(monkeypatch, again, [{**beat, "seconds": 9} for beat in beats], seconds=2)["rewritten"] == 1
    assert "第 2 段(2 秒" in again.prompts[0]


FIVE_BEATS = [
    {"narration": "手腕一戴就温柔", "caption": "钩子"},
    {"narration": "天然淡水珍珠", "caption": "珍珠"},
    {"narration": "白水晶通透交替", "caption": "水晶"},
    {"narration": "弹力绳谁戴都合手", "caption": "弹力绳"},
    {"narration": "点下方链接带走", "caption": "号召"},
]


def test_段数超出目标时长_从中间去掉_钩子和号召留着(monkeypatch) -> None:
    """付费实测:目标 10 秒、每拍 4 秒,提示词写明了 3 拍,模型照样写了 5 拍 —— 每一拍是一张图加一段视频的钱。"""
    writer = _Writer([])
    out = _fit(monkeypatch, writer, FIVE_BEATS, seconds="4", seconds_field="", max_total_seconds="10")
    assert [beat["caption"] for beat in out["items"]] == ["钩子", "珍珠", "号召"], "10 ÷ 4 四舍五入是 3 拍"
    assert out["dropped"] == [3, 4]
    assert "5 段" in out["note"] and "3 段" in out["note"] and "第 3、4 段" in out["note"], out["note"]
    assert writer.prompts == []


@pytest.mark.parametrize(("budget", "kept"), [("8", 2), ("9.9", 2), ("10", 3), ("14", 4), ("18", 5), ("60", 5)])
def test_每段一样长时_段数就是总时长除以每段秒数_四舍五入(monkeypatch, budget: str, kept: int) -> None:
    out = _fit(monkeypatch, _Writer([]), FIVE_BEATS, seconds="4", seconds_field="", max_total_seconds=budget)
    assert len(out["items"]) == kept
    assert (out["items"][0]["caption"], out["items"][-1]["caption"]) == ("钩子", "号召")


def test_每段各有时长时_按这一段的中点落不落在总时长里决定留不留(monkeypatch) -> None:
    beats = [{"narration": "一", "seconds": 3}, {"narration": "二", "seconds": 4}, {"narration": "三", "seconds": 1},
             {"narration": "四", "seconds": 2}]
    #: 首尾 3 + 2 = 5;第二段 4 秒的中点在 7,超了 6;第三段 1 秒的中点在 5.5,放得下。
    out = _fit(monkeypatch, _Writer([]), beats, max_total_seconds=6)
    assert [beat["narration"] for beat in out["items"]] == ["一", "三", "四"] and out["dropped"] == [2]


def test_段外也要念的话从总时长里扣掉(monkeypatch) -> None:
    """出镜版:主播说的开场和收尾也算在成片时长里。8 个字念 2 秒,10 秒只剩 8 秒给各拍,每拍 4 秒就是 2 拍。"""
    out = _fit(monkeypatch, _Writer([]), FIVE_BEATS, seconds="4", seconds_field="", max_total_seconds="10",
               reserved_text="姐妹们看这条\n快去下单")
    assert len(out["items"]) == 2 and out["dropped"] == [2, 3, 4]


def test_没给总时长_或者只有两段_一段都不删(monkeypatch) -> None:
    out = _fit(monkeypatch, _Writer([]), FIVE_BEATS, seconds="4", seconds_field="")
    assert len(out["items"]) == 5 and out["dropped"] == [] and out["note"] == ""
    two = _fit(monkeypatch, _Writer([]), FIVE_BEATS[:2], seconds="4", seconds_field="", max_total_seconds="1")
    assert len(two["items"]) == 2 and two["dropped"] == []


def test_先删再改写_要删的那一段不花改写的钱(monkeypatch) -> None:
    beats = [dict(beat) for beat in FIVE_BEATS]
    beats[3]["narration"] = "弹力绳穿制手围十五到十七厘米都能戴"
    writer = _Writer([])
    out = _fit(monkeypatch, writer, beats, seconds="4", seconds_field="", max_total_seconds="10")
    assert writer.prompts == [], "念不完的那一段本来就要删,不发给模型改"
    assert out["dropped"] == [3, 4]
