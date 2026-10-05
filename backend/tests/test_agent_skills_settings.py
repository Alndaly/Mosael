"""设置 → 智能体 → 技能 的接口(ADR 0040 §7):新建、改名、删除、开关、复制、文件、导入审阅、导出、存成技能、权限。

运行时那一半(目录、工具、「/」)在 test_agent_skills.py。
"""

from __future__ import annotations

import io
import json
import zipfile
from unittest.mock import patch as mock_patch

import pytest

from app.core.db import SessionLocal
from app.domain.agent.skills import catalog
from tests.util import add_provider, fresh_client, second_client

REAL_WORLD = """---
name: pdf-processing
description: >-
  Extracts text and tables from PDF files, fills PDF forms, and merges multiple PDFs.
  Use when working with PDF documents.
license: "Apache-2.0"
metadata:
  author: example-org
  version: "1.0"
allowed-tools:
  - Read
disable-model-invocation: true
---

# PDF Processing

1. Read the file.
2. See [the reference](references/REFERENCE.md).
"""


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _skill(name: str, description: str = "做一件事", body: str = "步骤一\n", title: str = "") -> dict:
    return {"name": name, "title": title, "description": description, "body": body}


def _zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _refs(client, ws: str) -> dict[str, dict]:
    return {one["ref"]: one for one in client.get(f"/api/workspaces/{ws}/skills").json()}


# ---------------------------------------------------------------- 写


def test_新建改名删除_开关跟着走_文件夹就是技能() -> None:
    client = fresh_client()
    ws = _workspace(client)
    created = client.post(f"/api/workspaces/{ws}/skills", json=_skill("brand-rules", title="品牌规范"))
    assert created.status_code == 201, created.text
    assert created.json()["enabled"] and created.json()["source_label"] == "工作区成员写的"
    folder = catalog.workspace_dir(ws) / "brand-rules"
    text = (folder / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: brand-rules\n") and 'mosael-title: "品牌规范"' in text

    renamed = client.put(f"/api/workspaces/{ws}/skills/brand-rules",
                         json=_skill("brand-guide", "新的说明", "新步骤\n", title="品牌规范"))
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["ref"] == "brand-guide" and renamed.json()["enabled"]
    assert not folder.exists() and (catalog.workspace_dir(ws) / "brand-guide" / "SKILL.md").exists()

    assert client.delete(f"/api/workspaces/{ws}/skills/brand-guide").status_code == 204
    assert not (catalog.workspace_dir(ws) / "brand-guide").exists()
    assert "brand-guide" not in _refs(client, ws)


@pytest.mark.parametrize(
    ("body", "status"),
    [
        (_skill("Bad Name"), 422),
        (_skill("creative-board"), 409),
        (_skill("ok", "d" * 1025), 422),
    ],
)
def test_新建的规矩(body: dict, status: int) -> None:
    client = fresh_client()
    ws = _workspace(client)
    assert client.post(f"/api/workspaces/{ws}/skills", json=body).status_code == status


def test_改的时候不认识的字段和别的metadata原样留着(tmp_path) -> None:
    client = fresh_client()
    ws = _workspace(client)
    staged = client.post(f"/api/workspaces/{ws}/skill-imports", files={"archive": ("pdf.zip", _zip({"SKILL.md": REAL_WORLD.encode()}))}).json()
    client.post(f"/api/workspaces/{ws}/skill-imports/{staged['import_id']}", json={"choices": [{"name": "pdf-processing"}]})
    detail = client.get(f"/api/workspaces/{ws}/skills/pdf-processing").json()
    assert detail["unknown_fields"] == ["disable-model-invocation"] and detail["allowed_tools"] == "Read"
    assert detail["metadata"] == {"author": "example-org", "version": "1.0"}
    client.put(f"/api/workspaces/{ws}/skills/pdf-processing", json=_skill("pdf-processing", "改过的说明", title="PDF"))
    text = (catalog.workspace_dir(ws) / "pdf-processing" / "SKILL.md").read_text(encoding="utf-8")
    assert "disable-model-invocation: true" in text and "  - Read" in text and 'author: "example-org"' in text
    assert 'mosael-title: "PDF"' in text and 'description: "改过的说明"' in text


def test_内置的改不了_复制成我的就能改() -> None:
    client = fresh_client()
    ws = _workspace(client)
    assert client.put(f"/api/workspaces/{ws}/skills/creative-board", json=_skill("creative-board")).status_code == 409
    assert client.delete(f"/api/workspaces/{ws}/skills/creative-board").status_code == 409
    copied = client.post(f"/api/workspaces/{ws}/skills/creative-board/copy", json={"name": "my-board"})
    assert copied.status_code == 201, copied.text
    assert copied.json()["editable"] and copied.json()["title"] == "创意画板"
    assert "list_board_producers" in copied.json()["body"]
    assert copied.json()["source_label"] == "复制来改的"


def test_开关_读不了的开不了() -> None:
    client = fresh_client()
    ws = _workspace(client)
    folder = catalog.workspace_dir(ws) / "broken"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nname: other-name\ndescription: x\n---\n", encoding="utf-8")
    assert client.put(f"/api/workspaces/{ws}/skills/broken/enabled", json={"enabled": True}).status_code == 409
    assert client.put(f"/api/workspaces/{ws}/skills/creative-board/enabled", json={"enabled": False}).json()["enabled"] is False
    assert _refs(client, ws)["creative-board"]["enabled"] is False


def test_文件_加换删_SKILL走表单_越界路径拒() -> None:
    client = fresh_client()
    ws = _workspace(client)
    client.post(f"/api/workspaces/{ws}/skills", json=_skill("refs"))
    added = client.put(f"/api/workspaces/{ws}/skills/refs/files/references/a.md", files={"file": ("a.md", "参考".encode())})
    assert added.status_code == 200, added.text
    assert {one["path"]: one["text"] for one in added.json()["files"]}["references/a.md"] == "参考"
    assert client.get(f"/api/workspaces/{ws}/skills/refs/files/references/a.md").content == "参考".encode()
    assert client.put(f"/api/workspaces/{ws}/skills/refs/files/SKILL.md", files={"file": ("SKILL.md", b"x")}).status_code == 422
    assert client.put(f"/api/workspaces/{ws}/skills/refs/files/a%5Cb.md", files={"file": ("x", b"x")}).status_code == 422
    assert client.get(f"/api/workspaces/{ws}/skills/refs/files/..%2F..%2Fmosael.db").status_code in (400, 404, 422)
    removed = client.delete(f"/api/workspaces/{ws}/skills/refs/files/references/a.md")
    assert [one["path"] for one in removed.json()["files"]] == ["SKILL.md"]
    assert not (catalog.workspace_dir(ws) / "refs" / "references").exists(), "空了的文件夹一起收掉"


def test_看的人只能看_改要编辑以上() -> None:
    owner = fresh_client()
    ws = _workspace(owner)
    viewer = second_client("viewer-x")
    owner.post(f"/api/workspaces/{ws}/invitations", json={"username": "viewer-x", "role": "viewer"})
    invitation = viewer.get("/api/invitations").json()["invitations"][0]
    viewer.post(f"/api/invitations/{invitation['id']}/accept")
    assert viewer.get(f"/api/workspaces/{ws}/skills").status_code == 200
    assert viewer.get(f"/api/workspaces/{ws}/skills/creative-board").status_code == 200
    assert viewer.post(f"/api/workspaces/{ws}/skills", json=_skill("x")).status_code == 403
    assert viewer.put(f"/api/workspaces/{ws}/skills/creative-board/enabled", json={"enabled": False}).status_code == 403
    assert viewer.post(f"/api/workspaces/{ws}/skill-imports", files={"archive": ("x.zip", b"zip")}).status_code == 403
    stranger = second_client("stranger-x")
    assert stranger.get(f"/api/workspaces/{ws}/skills").status_code in (403, 404)


# ---------------------------------------------------------------- 导入导出


def test_导入真实写法的压缩包_先看全文再落地_导出再导回来一样() -> None:
    client = fresh_client()
    ws = _workspace(client)
    archive = _zip({
        "pdf-processing-main/SKILL.md": REAL_WORLD.encode(),
        "pdf-processing-main/references/REFERENCE.md": "参考".encode(),
        "pdf-processing-main/scripts/extract.py": b"print('x')",
        "pdf-processing-main/assets/logo.png": b"\x89PNG\x00",
        "__MACOSX/pdf-processing-main/._SKILL.md": b"junk",
    })
    staged = client.post(f"/api/workspaces/{ws}/skill-imports", files={"archive": ("pdf.zip", archive)})
    assert staged.status_code == 200, staged.text
    preview = staged.json()
    [item] = preview["skills"]
    assert item["name"] == "pdf-processing" and item["folder"] == "pdf-processing-main"
    assert item["unknown_fields"] == ["disable-model-invocation"] and item["allowed_tools"] == "Read"
    files = {one["path"]: one for one in item["files"]}
    assert files["SKILL.md"]["text"] == REAL_WORLD, "审阅给全文"
    assert files["scripts/extract.py"]["script"] and files["assets/logo.png"]["binary"]
    assert "pdf-processing" not in _refs(client, ws), "审阅前什么都没装"

    committed = client.post(f"/api/workspaces/{ws}/skill-imports/{preview['import_id']}",
                            json={"choices": [{"name": "pdf-processing", "enable": True}]})
    assert committed.status_code == 200, committed.text
    [skill] = committed.json()
    assert skill["enabled"] and skill["origin"] == "imported" and skill["source_label"] == "从 pdf.zip 导入"
    on_disk = (catalog.workspace_dir(ws) / "pdf-processing" / "SKILL.md").read_text(encoding="utf-8")
    assert on_disk == REAL_WORLD, "没改名就原样落地,一个字节都不动"

    exported = client.get(f"/api/workspaces/{ws}/skills/pdf-processing/export")
    assert exported.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(exported.content)) as round_trip:
        names = set(round_trip.namelist())
        assert names == {"pdf-processing/SKILL.md", "pdf-processing/references/REFERENCE.md",
                         "pdf-processing/scripts/extract.py", "pdf-processing/assets/logo.png"}
        assert round_trip.read("pdf-processing/SKILL.md").decode() == REAL_WORLD
        assert round_trip.read("pdf-processing/references/REFERENCE.md") == "参考".encode()

    other = _workspace(client)
    again = client.post(f"/api/workspaces/{other}/skill-imports", files={"archive": ("x.zip", exported.content)}).json()
    assert {one["path"] for one in again["skills"][0]["files"]} == {one.split("/", 1)[1] for one in names}


def test_导入撞名_内置的必须改名_工作区的可以替换() -> None:
    client = fresh_client()
    ws = _workspace(client)
    client.post(f"/api/workspaces/{ws}/skills", json=_skill("mine", "旧的"))
    archive = _zip({
        "a/SKILL.md": b"---\nname: creative-board\ndescription: fake\n---\n",
        "b/SKILL.md": b"---\nname: mine\ndescription: new\n---\n",
    })
    preview = client.post(f"/api/workspaces/{ws}/skill-imports", files={"archive": ("x.zip", archive)}).json()
    assert {one["name"]: one["conflict"] for one in preview["skills"]} == {"creative-board": "builtin", "mine": "workspace"}
    url = f"/api/workspaces/{ws}/skill-imports/{preview['import_id']}"
    assert client.post(url, json={"choices": [{"name": "creative-board"}]}).status_code == 409
    assert client.post(url, json={"choices": [{"name": "mine"}]}).status_code == 409
    done = client.post(url, json={"choices": [{"name": "creative-board", "rename_to": "fake-board"},
                                              {"name": "mine", "replace": True}]})
    assert done.status_code == 200, done.text
    skills = _refs(client, ws)
    assert skills["mine"]["description"] == "new" and not skills["fake-board"]["enabled"], "没勾启用的装好也关着"
    renamed = (catalog.workspace_dir(ws) / "fake-board" / "SKILL.md").read_text(encoding="utf-8")
    assert renamed.startswith("---\nname: fake-board\n"), "改名改的是头里的 name,文件夹跟着它"


def test_导入暂存只认它的工作区() -> None:
    client = fresh_client()
    ws = _workspace(client)
    other = _workspace(client)
    preview = client.post(f"/api/workspaces/{ws}/skill-imports",
                          files={"archive": ("x.zip", _zip({"SKILL.md": b"---\nname: a\ndescription: d\n---\n"}))}).json()
    response = client.post(f"/api/workspaces/{other}/skill-imports/{preview['import_id']}",
                           json={"choices": [{"name": "a"}]})
    assert response.status_code == 404


def test_导入文件夹_文件与相对路径同序上传() -> None:
    client = fresh_client()
    ws = _workspace(client)
    response = client.post(
        f"/api/workspaces/{ws}/skill-imports",
        files=[("files", ("SKILL.md", b"---\nname: folder-skill\ndescription: d\n---\nbody\n")),
               ("files", ("a.md", b"x"))],
        data={"paths": ["folder-skill/SKILL.md", "folder-skill/refs/a.md"]},
    )
    assert response.status_code == 200, response.text
    [item] = response.json()["skills"]
    assert item["name"] == "folder-skill" and {one["path"] for one in item["files"]} == {"SKILL.md", "refs/a.md"}
    assert response.json()["source_name"] == "folder-skill"


@pytest.mark.parametrize(
    "entries",
    [{"../SKILL.md": b"---\nname: a\ndescription: d\n---\n"}, {"x/readme.md": b"x"}, {"SKILL.md": b"no header"}],
)
def test_不合格的压缩包当场说清(entries: dict[str, bytes]) -> None:
    client = fresh_client()
    ws = _workspace(client)
    response = client.post(f"/api/workspaces/{ws}/skill-imports", files={"archive": ("x.zip", _zip(entries))})
    assert response.status_code == 422 and response.json()["detail"]


# ---------------------------------------------------------------- 存成技能


def _configured() -> None:
    with SessionLocal() as db:
        add_provider(db, name="P", vendor="openai-compatible", base_url="http://localhost:1/v1",
                     api_key="k", model="m", capability_ids=["chat"])
        db.commit()


def test_存成技能_用会话的模型起草_不保存() -> None:
    client = fresh_client()
    _configured()
    ws = _workspace(client)
    session = client.post("/api/agent/sessions", json={"workspace_id": ws}).json()
    from app.db.models import AgentMessage

    with SessionLocal() as db:
        db.add(AgentMessage(session_id=session["id"], role="user", content="把这条长视频切成三段竖屏"))
        db.add(AgentMessage(session_id=session["id"], role="assistant", content="切好了",
                            payload={"timeline": [{"type": "tool", "tool": {"name": "transcribe_asset"}}]}))
        db.commit()
    seen: dict = {}

    def fake_chat(target, messages, **kwargs):
        seen["messages"] = messages
        seen["kwargs"] = kwargs
        return json.dumps({"name": "Long To Short!", "title": "长视频切竖屏", "description": "把长视频切成竖屏短片",
                           "body": "1. 转写\n2. 挑段落"}, ensure_ascii=False)

    with mock_patch("app.domain.ai_chat.chat", side_effect=fake_chat):
        draft = client.post(f"/api/agent/sessions/{session['id']}/skill-draft")
    assert draft.status_code == 200, draft.text
    assert draft.json() == {"name": "long-to-short", "title": "长视频切竖屏", "description": "把长视频切成竖屏短片",
                            "body": "1. 转写\n2. 挑段落\n"}
    transcript = seen["messages"][-1]["content"]
    assert "把这条长视频切成三段竖屏" in transcript and "transcribe_asset" in transcript
    assert seen["kwargs"]["json_object"] is True and seen["kwargs"]["call"] is not None, "这是一次计费的调用"
    assert "long-to-short" not in _refs(client, ws), "起草不保存"

    with mock_patch("app.domain.ai_chat.chat", return_value="不是 JSON"):
        assert client.post(f"/api/agent/sessions/{session['id']}/skill-draft").status_code == 502

    saved = client.post(f"/api/workspaces/{ws}/skills", json={**draft.json(), "from_conversation": True})
    assert saved.status_code == 201 and saved.json()["origin"] == "conversation"


def test_存成技能_空对话说清楚_别人的对话看不见() -> None:
    client = fresh_client()
    _configured()
    ws = _workspace(client)
    session = client.post("/api/agent/sessions", json={"workspace_id": ws}).json()
    with mock_patch("app.domain.ai_chat.chat") as chat:
        assert client.post(f"/api/agent/sessions/{session['id']}/skill-draft").status_code == 409
        assert not chat.called, "没东西可起草就不花这一次模型调用"
    stranger = second_client("stranger-y")
    assert stranger.post(f"/api/agent/sessions/{session['id']}/skill-draft").status_code == 404
