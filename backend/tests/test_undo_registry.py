"""结构性约束:**记进操作日志的每一种操作,都要登记它的逆操作。**

不接的话失败方式极其隐蔽。撤销是往回找「最新的、还没撤销过的」那一条;从前那个查询还额外
按 kind 过滤,于是一条没登记逆操作的编辑会被**静默跳过**,撤销落到更早的一条上 —— 200,
没有报错,can_undo 一直是 true。用户按一次 ⌘Z 想撤销刚做的事,消失的却是上一件不相干的编辑,
而时间线上没有任何东西提示他刚才发生了什么。

例外只能写进 undo.NOT_UNDOABLE,并说明为什么不需要 —— 只减不增,和
tests/test_agent_workflow_parity.py、test_data_ownership_ratchet.py 是同一套棘轮。
"""

from __future__ import annotations

import re
from pathlib import Path

from app.domain.sequences import undo as undo_registry
from tests.util import fresh_client, make_video_asset

OPERATIONS = Path(__file__).resolve().parents[1] / "app/domain/sequences/operations.py"


def _recorded_kinds() -> set[str]:
    """operations.py 里 _record_operation(kind="…") 实际会写进日志的所有 kind。"""
    source = OPERATIONS.read_text("utf-8")
    calls = re.findall(r"_record_operation\((.*?)\n    \)", source, re.S)
    assert calls, "没有解析到任何 _record_operation 调用 —— 解析式该跟着代码改了"
    return {m.group(1) for m in (re.search(r'kind="([a-z_]+)"', call) for call in calls) if m}


def test_每一种记录下来的操作都登记了逆操作() -> None:
    recorded = _recorded_kinds()
    known = set(undo_registry.undoable_kinds()) | set(undo_registry.NOT_UNDOABLE)
    missing = sorted(recorded - known)
    assert missing == [], (
        "这些操作会写进撤销日志,却没有登记逆操作 —— 用户按 ⌘Z 时会撤掉更早的一条编辑:\n  "
        + "\n  ".join(missing)
    )


def test_注册表里没有已经不再记录的操作() -> None:
    """只减不增。留一条指向已删操作的登记,下一个人会以为那条路还活着。"""
    recorded = _recorded_kinds()
    # undo / redo 是撤销机制自己追加的记账,不在 operations.py 的静态文本里,单独放行。
    bookkeeping = {"undo", "redo"}
    stale = sorted((set(undo_registry.undoable_kinds()) | set(undo_registry.NOT_UNDOABLE)) - recorded - bookkeeping)
    assert stale == [], f"登记了不存在的操作: {stale}"


def test_两个方向必须成对() -> None:
    """只写逆向不写正向的话,撤销好使、重做时才炸 —— 而那时用户已经把东西撤掉了。"""
    for kind in undo_registry.undoable_kinds():
        pair = undo_registry._REGISTRY[kind]
        assert callable(pair.inverse) and callable(pair.forward), kind


def test_撤销不会跳过没登记的操作去撤更早的那条() -> None:
    """这条钉的是那个静默跳过的行为本身。

    实测过的原始症状:插入一个片段 → 记一条没登记逆操作的操作 → 按一次撤销,
    返回 200,而**片段没了**。现在它应当明确报错,片段留在原地。
    """
    from app.core.db import SessionLocal
    from app.db.models import Sequence
    from app.domain.sequences.operations import _record_operation

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    asset = make_video_asset(client, ws["id"])
    seq = client.post(
        "/api/sequences", json={"workspace_id": ws["id"], "project_id": project["id"], "name": "S"}
    ).json()
    track = next(t for t in seq["tracks"] if t["kind"] == "video")
    client.post(
        f"/api/sequences/{seq['id']}/clips",
        json={"track_id": track["id"], "asset_id": asset["id"], "timeline_start": 0, "src_in": 0, "src_out": 5},
    )

    db = SessionLocal()
    _record_operation(
        db,
        db.get(Sequence, seq["id"]),
        kind="some_unregistered_kind",
        payload={},
        summary={"operation": "没登记的操作"},
        actor_id=None,
    )
    db.commit()
    db.close()

    denied = client.post(f"/api/sequences/{seq['id']}/undo")
    assert denied.status_code == 422, denied.text
    assert "不支持撤销" in denied.json()["detail"]

    after = client.get(f"/api/sequences/{seq['id']}").json()
    clips = next(t for t in after["tracks"] if t["kind"] == "video")["clips"]
    assert len(clips) == 1, "撤销跳过了最新那条,把更早的插入撤了"
