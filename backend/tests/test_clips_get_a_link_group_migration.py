"""链接组的两条迁移:`_migrate_clips_get_a_link_group`(加列)与
`_migrate_detached_audio_joins_its_video`(升级前分离出去、还对得严丝合缝的音频补进画面的组)。"""

from __future__ import annotations

from sqlalchemy import text

from app.core.db import engine
from tests.test_linked_clips import _detached
from tests.test_clips_never_overlap import Timeline


def _columns() -> set[str]:
    with engine.connect() as conn:
        return {row[1] for row in conn.execute(text("PRAGMA table_info(clips)"))}


def test_老库的片段表补上链接组这一列() -> None:
    from app.db.migrations import _migrate_clips_get_a_link_group

    Timeline()  # 建好当前的库
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE clips DROP COLUMN link_group"))
    assert "link_group" not in _columns()
    _migrate_clips_get_a_link_group()
    assert "link_group" in _columns()
    _migrate_clips_get_a_link_group()  # 再跑一次不报 duplicate column


def _forget_links() -> None:
    """模拟升级前:那时分离音频不分组。"""
    with engine.begin() as conn:
        conn.execute(text("UPDATE clips SET link_group = NULL"))


def _groups(line: Timeline) -> dict[str, str | None]:
    """查库,不走接口:接口按 revision 缓存响应,而 _forget_links 是绕过算子直接改的行。"""
    with engine.connect() as conn:
        return dict(conn.execute(text(
            "SELECT tracks.kind, clips.link_group FROM clips JOIN tracks ON tracks.id = clips.track_id "
            "WHERE clips.sequence_id = :s"), {"s": line.id}).all())


def test_升级前分离出去的音频补进画面的组_挪开过的和撤销了的不补() -> None:
    from app.db.migrations import _migrate_detached_audio_joins_its_video

    aligned = Timeline()
    _detached(aligned)
    moved_apart = Timeline(aligned.client)
    video, audio, _ = _detached(moved_apart)
    moved_apart.ok(moved_apart.client.patch(
        f"/api/sequences/{moved_apart.id}/clips/{audio['id']}/move", json={"timeline_start": 7, "linked": False}))
    undone = Timeline(aligned.client)
    _detached(undone)
    undone.ok(undone.client.post(f"/api/sequences/{undone.id}/undo"))
    _forget_links()

    revision = aligned.get()["revision"]
    _migrate_detached_audio_joins_its_video()
    linked = _groups(aligned)
    assert aligned.get()["revision"] == revision + 1, "补过组的序列换一个版本号,编辑器才会重新取"
    assert linked["video"] and linked["video"] == linked["audio"]
    assert set(_groups(moved_apart).values()) == {None}, "用户已经把它们挪开过,不替他绑回去"
    assert set(_groups(undone).values()) == {None}

    _migrate_detached_audio_joins_its_video()
    assert _groups(aligned) == linked, "再跑一次不换组号"
