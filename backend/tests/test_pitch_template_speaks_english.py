"""带货口播给英文界面的人:完成通知、念不完的提醒、新项目的名字是英文;运行时才说的那几句(用的是哪把嗓子、
口播收紧了哪几段)也按发起运行的人的语言说。

此前这张模板的通知只有中文,官网英文副本里也是中文;运行时那几句在后台线程里生成,一律落成缺省语言。
"""

from __future__ import annotations

import re
import time
from types import SimpleNamespace

import pytest

from app.domain.workflows.templates import ModelChoice, blank_template_graphs
from app.domain.workflows.templates_business import PRODUCT_PITCH_SHORT, product_pitch_short_graph
from tests.util import fresh_client

_CJK = re.compile(r"[一-鿿]")
CHAT = ModelChoice(profile_id="chat", provider="openai", model="chat-model")
SEEDREAM = ModelChoice(profile_id="image", provider="bytedance", model="doubao-seedream-4-0-250828")


def _nodes(graph: dict) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for node in graph["nodes"]:
        found[node["id"]] = node
        body = (node.get("config") or {}).get("body")
        if isinstance(body, dict):
            found |= _nodes(body)
    return found


def _without_refs(text: str) -> str:
    return re.sub(r"\{\{[^}]*\}\}", "", text)


@pytest.mark.parametrize("graph", [
    pytest.param(lambda: product_pitch_short_graph(chat=CHAT, image=SEEDREAM, voice_id="", locale="en"), id="建图"),
    pytest.param(lambda: blank_template_graphs("en")[PRODUCT_PITCH_SHORT], id="官网英文副本"),
])
def test_英文的那一份_通知和项目名都是英文(graph) -> None:
    nodes = _nodes(graph())
    for node_id in ("done_notice", "overflow_notice"):
        for key in ("title", "body"):
            text = _without_refs(nodes[node_id]["config"][key])
            assert text.strip() and not _CJK.search(text), (node_id, key, text)
    assert not _CJK.search(_without_refs(nodes["pitch_project"]["config"]["name"]))


def test_中文的那一份照旧是中文() -> None:
    nodes = _nodes(product_pitch_short_graph(chat=CHAT, image=SEEDREAM, voice_id="", locale="zh"))
    assert "带货短片已导出" == nodes["done_notice"]["config"]["title"]


@pytest.mark.parametrize(("language", "expected"), [("en-US", "Narrated in"), ("zh-CN", "配音用的是")])
def test_运行时说的话按发起运行的人的语言(monkeypatch, language: str, expected: str) -> None:
    from app.domain.voices import voices
    from app.domain.workflows.executors import subjobs

    monkeypatch.setattr(voices, "start_synthesis", lambda db, **kwargs: SimpleNamespace(id="child"))
    monkeypatch.setattr(subjobs, "wait_for_job", lambda job_id, release=None: SimpleNamespace(result={"asset_id": "a1"}))
    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "voice", "type": "synthesize_speech", "name": "念", "config": {
                "text": "hello", "engine": "builtin:edge", "voice": "en-US-AriaNeural"}},
        ],
        "edges": [{"id": "e", "source": "start", "target": "voice"}],
    }
    workflow = client.post("/api/workflows", json={"workspace_id": workspace_id, "name": "W", "graph": graph}).json()
    job_id = client.post(f"/api/workflows/{workflow['id']}/run", json={"params": {}},
                         headers={"Accept-Language": language}).json()["id"]
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.05)
    assert job["status"] == "succeeded", job
    assert expected in job["result"]["context"]["voice"]["voice_note"], job["result"]["context"]["voice"]
