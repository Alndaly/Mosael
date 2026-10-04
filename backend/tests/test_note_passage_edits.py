"""智能体按段改笔记(edit_note):把一段原文换掉、在一段原文前后插入,走确认卡。

笔记页的助手要能「改写选中的这段」「在光标处续写」。此前智能体对笔记只有 create_note / append_note:
要改中间一句只能整篇重写(覆盖掉用户的排版和刚打的字)或者追加到末尾(用户要的不是这个)。

钉住的几件事:
1. 走真入口 —— sidecar 发的就是 `/api/agent/tools/edit_note`,开出来的是一张 edit 档的确认卡,批准之后
   正文才变,旧的那一版留在版本记录里(撤得回);
2. 锚点是**原文本身**,必须恰好出现一次 —— 找不到、出现多次都在开卡之前就拒,并把原因说给模型;
3. 落在**批准那一刻**的正文上:开卡之后用户在别处又写了字,批准不会把它冲掉;那段原文已经被改掉了,
   批准就失败、什么都不写,而不是改到别的地方去。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.core.security import mint_service_session
from app.db.models import User
from app.domain.notes import NoteDomainError
from app.domain.notes.passages import apply_passage_edits
from tests.util import fresh_client


class Chat:
    """一次挂在工作区上的对话,工具经 sidecar 那条通道调(带对话令牌)。"""

    def __init__(self) -> None:
        self.client = fresh_client()
        self.workspace_id = self.client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        session_id = self.client.post(
            "/api/agent/sessions", json={"workspace_id": self.workspace_id, "title": "T"}
        ).json()["id"]
        with SessionLocal() as db:
            user = db.query(User).filter(User.username == "tester").one()
            self.token = mint_service_session(db, user.id, agent_session_id=session_id)

    def note(self, markdown: str, title: str = "周报") -> dict:
        created = self.client.post("/api/notes", json={"workspace_id": self.workspace_id, "title": title, "markdown": markdown})
        assert created.status_code == 200, created.text
        return created.json()

    def read(self, note_id: str) -> dict:
        return self.client.get(f"/api/notes/{note_id}", params={"workspace_id": self.workspace_id}).json()

    def edit(self, note_id: str, operations: list[dict]) -> dict:
        response = self.client.post(
            "/api/agent/tools/edit_note",
            json={"arguments": {"note_id": note_id, "operations": operations}, "requested_by": "pi"},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        assert response.status_code == 200, response.text
        return response.json()

    def approve(self, card_id: str) -> dict:
        return self.client.post(f"/api/confirmations/{card_id}/approve").json()

    def cards(self) -> list[dict]:
        return self.client.get("/api/confirmations", params={"workspace_id": self.workspace_id}).json()


def test_经工具通道开卡_批准后按段改好_旧的一版留在版本记录里() -> None:
    chat = Chat()
    note = chat.note("# 本周\n\n周一开了会。\n\n周二写了脚本。")

    card = chat.edit(note["id"], [
        {"kind": "replace", "find": "周一开了会。", "text": "周一和剪辑组对了节奏。"},
        {"kind": "insert", "after": "周二写了脚本。", "text": "\n\n周三拍了素材。"},
    ])["result"]

    row = chat.client.get(f"/api/confirmations/{card['confirmation_id']}").json()
    assert row["status"] == "pending", "改正文要先问人"
    assert row["permission"] == "edit", "笔记的每一版都留着,最坏也撤得回 —— 是 edit 档"
    assert "周报" in row["summary"], "卡上要说清改的是哪一篇"
    assert chat.read(note["id"])["markdown"] == note["markdown"], "批准之前正文一个字都不动"

    done = chat.approve(card["confirmation_id"])
    assert done["status"] == "executed", done.get("error")

    after = chat.read(note["id"])
    assert after["markdown"] == "# 本周\n\n周一和剪辑组对了节奏。\n\n周二写了脚本。\n\n周三拍了素材。"
    assert after["revision"] == note["revision"] + 1
    assert done["result"]["revision"] == after["revision"], "结果里带上新的修订号,模型接着改时不用再查一次"
    old = chat.client.get(
        f"/api/notes/{note['id']}/revisions/{note['revision']}", params={"workspace_id": chat.workspace_id}
    ).json()
    assert old["markdown"] == note["markdown"], "改之前的那一版还在,版本记录里能恢复"


def test_插入可以落在一段原文前面() -> None:
    chat = Chat()
    note = chat.note("开场白\n\n正片")

    card = chat.edit(note["id"], [{"kind": "insert", "before": "正片", "text": "片头\n\n"}])["result"]
    assert chat.approve(card["confirmation_id"])["status"] == "executed"

    assert chat.read(note["id"])["markdown"] == "开场白\n\n片头\n\n正片"


@pytest.mark.parametrize(("operations", "says"), [
    ([{"kind": "replace", "find": "不存在的一句", "text": "x"}], "不存在的一句"),
    #: 出现两次:改哪一处是猜的。说清出现了几次,让模型把原文取长一点。
    ([{"kind": "replace", "find": "镜头", "text": "x"}], "2"),
    ([{"kind": "insert", "after": "镜头", "text": "x"}], "2"),
    #: 前后都给 / 都不给:插在哪里说不清。
    ([{"kind": "insert", "after": "一号", "before": "二号", "text": "x"}], "after"),
    ([{"kind": "insert", "text": "x"}], "after"),
    ([{"kind": "rewrite", "text": "x"}], "rewrite"),
    ([], "operations"),
])
def test_说不清改哪里的_开卡之前就拒(operations: list[dict], says: str) -> None:
    chat = Chat()
    note = chat.note("一号镜头。\n\n二号镜头。")

    refused = chat.edit(note["id"], operations)

    assert "result" not in refused, refused
    assert says in refused["error"]
    assert chat.cards() == [], "一张注定执行不了的卡不该让用户去点"


def test_回收站里的笔记不改() -> None:
    chat = Chat()
    note = chat.note("正文")
    trashed = chat.client.patch(f"/api/notes/{note['id']}", json={
        "workspace_id": chat.workspace_id, "base_revision": note["revision"], "title": note["title"],
        "markdown": note["markdown"], "trashed": True,
    })
    assert trashed.status_code == 200, trashed.text

    refused = chat.edit(note["id"], [{"kind": "replace", "find": "正文", "text": "新的"}])

    assert "result" not in refused
    assert "回收站" in refused["error"]


def test_开卡之后用户在别处又写了字_批准落在当前正文上_不把它冲掉() -> None:
    chat = Chat()
    note = chat.note("第一段。\n\n第二段。")
    card = chat.edit(note["id"], [{"kind": "replace", "find": "第一段。", "text": "改过的第一段。"}])["result"]

    typed = chat.client.patch(f"/api/notes/{note['id']}", json={
        "workspace_id": chat.workspace_id, "base_revision": note["revision"], "title": note["title"],
        "markdown": "第一段。\n\n第二段。\n\n用户刚写的第三段。",
    })
    assert typed.status_code == 200, typed.text

    assert chat.approve(card["confirmation_id"])["status"] == "executed"
    assert chat.read(note["id"])["markdown"] == "改过的第一段。\n\n第二段。\n\n用户刚写的第三段。"


def test_开卡之后那段原文被改掉了_批准失败_什么都不写() -> None:
    chat = Chat()
    note = chat.note("第一段。\n\n第二段。")
    card = chat.edit(note["id"], [{"kind": "replace", "find": "第一段。", "text": "改过的第一段。"}])["result"]

    typed = chat.client.patch(f"/api/notes/{note['id']}", json={
        "workspace_id": chat.workspace_id, "base_revision": note["revision"], "title": note["title"],
        "markdown": "用户自己重写了开头。\n\n第二段。",
    })
    assert typed.status_code == 200, typed.text

    done = chat.approve(card["confirmation_id"])
    assert done["status"] == "failed"
    assert "第一段。" in done["error"]
    assert chat.read(note["id"])["markdown"] == "用户自己重写了开头。\n\n第二段。"


# ── 纯函数:算子按顺序落在上一步的结果上 ──────────────────────────────────────────


def test_算子依次落在上一步的结果上() -> None:
    text = apply_passage_edits("甲乙丙", [
        {"kind": "replace", "find": "乙", "text": "乙乙"},
        #: 上一步之后「乙乙」出现了 —— 这一步认的是改过之后的正文。
        {"kind": "insert", "after": "乙乙", "text": "!"},
        {"kind": "replace", "find": "丙", "text": ""},
    ])
    assert text == "甲乙乙!"


def test_重叠出现也算不唯一() -> None:
    """`str.count` 数的是不重叠的次数:「哈哈」在「哈哈哈」里数出 1 次,而它其实能落在两个位置上。"""
    with pytest.raises(NoteDomainError) as refused:
        apply_passage_edits("哈哈哈", [{"kind": "replace", "find": "哈哈", "text": "嘿"}])
    assert refused.value.key == "noteErr_passageAmbiguous"


def test_高亮的字照原文改_记号跟着走() -> None:
    """笔记里的高亮存成 `==文字==`(前端 notes/NoteHighlight):锚点照抄原文时连记号一起抄,改完记号还在。"""
    text = apply_passage_edits("开场 ==三十秒太慢== 以内。", [
        {"kind": "replace", "find": "==三十秒太慢==", "text": "==十五秒以内=="},
    ])
    assert text == "开场 ==十五秒以内== 以内。"
