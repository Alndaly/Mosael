"""只改属性不记版本:收藏、移进回收站、改标签 / 主题 / 所属项目,不再在版本记录里多出一版。

版本记录里一版是「正文的一个样子」—— 标题、正文、来源。此前每次写入都开一版,于是点一下收藏、移进回收站再移出来,
版本记录里就多出几版「属性有改动」,正文一个字没变。现在这些写入照样 +1 保存序号(并发要认它),版本号不动。

恢复也只恢复正文:把第 1 版找回来,不会顺手把收藏取消、把标签抹掉、把它从回收站里拎出来。
"""

from __future__ import annotations

from tests.util import fresh_client


def _setup():
    c = fresh_client()
    ws = c.post("/api/workspaces", json={"name": "W"}).json()["id"]
    note = c.post("/api/notes", json={"workspace_id": ws, "title": "周报", "markdown": "周一"}).json()
    return c, ws, note


def _save(c, ws: str, note: dict, **change) -> dict:
    response = c.patch(f"/api/notes/{note['id']}", json={**note, **change, "workspace_id": ws, "base_save_seq": note["save_seq"]})
    assert response.status_code == 200, response.text
    return response.json()


def _versions(c, ws: str, note_id: str) -> list[int]:
    return [one["revision"] for one in c.get(f"/api/notes/{note_id}/revisions", params={"workspace_id": ws}).json()]


def test_收藏_回收站_标签_主题都不开新版_保存序号照样往上走() -> None:
    c, ws, note = _setup()
    for change in ({"favorite": True}, {"tags": ["脚本"]}, {"topics": ["宣传片"]}, {"trashed": True}, {"trashed": False}):
        saved = _save(c, ws, note, **change)
        assert saved["revision"] == 1, change
        assert saved["save_seq"] == note["save_seq"] + 1, change
        note = saved
    assert _versions(c, ws, note["id"]) == [1]
    assert note["favorite"] is True and note["tags"] == ["脚本"] and note["topics"] == ["宣传片"]


def test_正文和属性一起改_开一版() -> None:
    c, ws, note = _setup()
    saved = _save(c, ws, note, markdown="周一开会", favorite=True)
    assert saved["revision"] == 2
    assert _versions(c, ws, note["id"]) == [2, 1]


def test_恢复只恢复正文_收藏_标签_回收站照现在的() -> None:
    c, ws, note = _setup()
    note = _save(c, ws, note, title="第一周", markdown="周一开会")
    note = _save(c, ws, note, favorite=True, tags=["脚本"])
    assert note["revision"] == 2

    restored = c.post(f"/api/notes/{note['id']}/restore", json={"workspace_id": ws, "base_save_seq": note["save_seq"], "revision": 1})
    assert restored.status_code == 200, restored.text
    body = restored.json()
    assert (body["title"], body["markdown"]) == ("周报", "周一")
    assert body["favorite"] is True and body["tags"] == ["脚本"], "恢复正文,不动属性"
    assert body["revision"] == 3

    same = c.post(f"/api/notes/{note['id']}/restore", json={"workspace_id": ws, "base_save_seq": body["save_seq"], "revision": 3})
    assert same.json()["revision"] == 3, "恢复成和现在一模一样的正文,什么都不开"
