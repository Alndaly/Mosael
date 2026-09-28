"""画板上连进生成格的文档由服务端按连线取,整篇交给模型;请求里的 `prompt` 只是用户写的那句。

此前前端把文档正文拼进提示词再提交:生成记录里存的是拼过的字,AI 工作台的用户气泡把文档正文当成用户说的话
画出来,给模型什么也由前端说了算。现在画板照连线取(boards.actions.upstream_documents),漏斗把它们写成一段
「参考文档」记进 `prompt_notes`(generation.operations.documents_note),交给供应商时再接上。
"""

from __future__ import annotations

import time
from unittest.mock import patch as mock_patch

import pytest

from app.core.db import SessionLocal
from app.core.i18n import DEFAULT_LOCALE, set_current_locale
from app.domain.generation import create_generation_job
from app.domain.generation import operations
from app.domain.generation.operations import ReferenceDocument, prompt_for_provider
from tests.test_entity_generation_paths import _seedance, _workspace
from tests.util import board_revision, fresh_client, run_on_board


@pytest.fixture(autouse=True)
def _external(monkeypatch) -> None:
    """只看漏斗写下了什么,不真的跑。"""
    from app.domain import jobs as jobs_bus

    monkeypatch.setattr(jobs_bus, "_EXECUTION_MODES", {**jobs_bus._EXECUTION_MODES, "ai_generation": "external"})


def _parsed_document(client, ws: str, name: str, body: str) -> str:
    """导入一份文本文档,等本机解析做完。"""
    made = client.post("/api/assets/import", data={"workspace_id": ws},
                       files={"file": (name, body.encode(), "application/octet-stream")}).json()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        listed = client.get(f"/api/assets/{made['id']}/extractions").json()
        if listed and listed[0]["status"] == "succeeded":
            return made["id"]
        time.sleep(0.1)
    raise AssertionError("解析一直没做完")


def _board(client, ws: str, items: list[dict], sources: list[str]) -> str:
    """一张板:给定的几格,按 `sources` 的先后各连一根线到生成格 `shot`。"""
    board_id = client.post("/api/boards", json={"workspace_id": ws}).json()["id"]
    canvas = {
        "items": [*items, {"id": "shot", "kind": "image", "x": 600, "y": 0}],
        "edges": [{"id": f"{one}->shot", "source": one, "target": "shot"} for one in sources],
    }
    saved = client.patch(f"/api/boards/{board_id}", json={
        "workspace_id": ws, "canvas": canvas, "base_revision": board_revision(client, board_id, ws),
    })
    assert saved.status_code == 200, saved.text
    return board_id


def _run(client, ws: str, board_id: str):
    seen: dict = {}

    def spy(db, **kwargs):
        seen.update(kwargs)
        raise RuntimeError("到这儿就够了")

    with mock_patch("app.domain.generation.create_generation_job", side_effect=spy):
        try:
            response = run_on_board(client, board_id, ws, producer="generate", item_id="shot", kind="image", x=600, y=0,
                                    form={"prompt": "照这份脚本画第一幕", "provider": "openai", "model": "gpt-image-1"})
        except RuntimeError:
            return seen, None
    return seen, response


def test_连进来的文档按连线先后取_笔记给钉住的那一版_素材给解析出的全文() -> None:
    client = fresh_client()
    ws = _workspace(client)
    note = client.post("/api/notes", json={"workspace_id": ws, "title": "企划", "markdown": "第一版正文"}).json()
    edited = client.patch(f"/api/notes/{note['id']}", json={
        "workspace_id": ws, "base_revision": note["revision"], "title": "企划", "markdown": "第二版正文",
    })
    assert edited.status_code == 200, edited.text
    brief = _parsed_document(client, ws, "brief.md", "# 简报\n今天发布。")
    board_id = _board(client, ws, [
        {"id": "plan", "kind": "document", "x": 0, "y": 0, "note_id": note["id"], "note_revision": note["revision"]},
        {"id": "brief", "kind": "document", "x": 0, "y": 200, "asset_id": brief},
    ], sources=["brief", "plan"])

    seen, _ = _run(client, ws, board_id)
    assert seen["prompt"] == "照这份脚本画第一幕", "提示词只是用户写的那句"
    assert [one.title for one in seen["documents"]] == ["brief", "企划"], "按连线的先后"
    assert "今天发布。" in seen["documents"][0].markdown
    assert seen["documents"][1].markdown == "第一版正文", "钉住的那一版,不是最新版"


def test_连着却读不到的文档_不生成() -> None:
    client = fresh_client()
    ws = _workspace(client)
    board_id = _board(client, ws, [{"id": "empty", "kind": "document", "x": 0, "y": 0, "text": "空文档"}], sources=["empty"])

    seen, response = _run(client, ws, board_id)
    assert seen == {}, "没到漏斗"
    assert response is not None and response.status_code == 400, response.text if response else None
    assert "空文档" in response.json()["detail"]


def _create(ws: str, profile: str, prompt: str, documents: list[ReferenceDocument]) -> dict:
    with SessionLocal() as db:
        generation, _job = create_generation_job(
            db, workspace_id=ws, session_id=None, project_id=None, created_by=None, provider="bytedance",
            provider_profile_id=profile, model="doubao-seedance-2-0-260128", kind="video", prompt=prompt,
            negative_prompt="", parameters={}, source_assets=[], documents=documents,
        )
        return dict(generation.request)


def test_文档记在补充里_模型收到的是提示词接着整篇文档() -> None:
    client = fresh_client()
    ws = _workspace(client)
    profile = _seedance(client)
    documents = [ReferenceDocument("脚本", "# 第一幕\n\n清晨的码头"), ReferenceDocument("设定", "黑白胶片")]
    set_current_locale("en")
    try:
        request = _create(ws, profile, "draw the first act", documents)
    finally:
        set_current_locale(DEFAULT_LOCALE)
    assert request["prompt"] == "draw the first act"
    assert request["prompt_notes"] == [
        "Reference documents (source material):\n\n脚本\n# 第一幕\n\n清晨的码头\n\n设定\n黑白胶片"
    ]
    # 和此前前端拼出来的一样(只少了笔记那条只在应用里打得开的链接)。
    assert prompt_for_provider(request) == (
        "draw the first act\n\nReference documents (source material):\n\n脚本\n# 第一幕\n\n清晨的码头\n\n设定\n黑白胶片"
    )


def test_抬头按这次请求的语言() -> None:
    client = fresh_client()
    ws = _workspace(client)
    profile = _seedance(client)
    request = _create(ws, profile, "画第一幕", [ReferenceDocument("脚本", "清晨的码头")])
    assert request["prompt_notes"] == ["参考文档(素材):\n\n脚本\n清晨的码头"]


def test_不收提示词的模型_不给文档(monkeypatch) -> None:
    client = fresh_client()
    ws = _workspace(client)
    profile = _seedance(client)
    monkeypatch.setattr(operations, "prompt_mode", lambda _capabilities: "none")
    request = _create(ws, profile, "", [ReferenceDocument("脚本", "清晨的码头")])
    assert "prompt_notes" not in request
