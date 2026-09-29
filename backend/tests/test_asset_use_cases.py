"""素材用例(domain/assets/use_cases):闸在领域里,事务在入口层。

这是「一次用例一个事务,授权在领域里」的第一个领域。要钉住的是两件此前做不到的事:

- **不经过 HTTP 也过得了同一道闸**。智能体工具、工作流节点直接调这些函数,拿到的是同一种拒绝。
- **一批删除要么全删、要么全不删**,文件只在提交之后才从盘上清掉。此前每删一份就提交一次,
  删到一半出错时前面的已经没了。
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.unit_of_work import unit_of_work
from app.db.models import Asset, User
from app.domain.assets import use_cases
from app.domain.permissions import NotVisible, PermissionDenied
from tests.util import fresh_client, insert_asset, second_client


def _workspace_with(role: str) -> tuple[str, str]:
    owner = fresh_client()
    ws = owner.post("/api/workspaces", json={"name": "W"}).json()
    mate = second_client("mate")
    owner.post(f"/api/workspaces/{ws['id']}/invitations", json={"username": "mate", "role": role})
    invitation = mate.get("/api/invitations").json()["invitations"][0]
    mate.post(f"/api/invitations/{invitation['id']}/accept")
    return ws["id"], "mate"


def _user(db, username: str) -> User:
    return db.query(User).filter(User.username == username).one()


def _asset_with_file(workspace_id: str, name: str) -> tuple[str, object]:
    folder = settings.media_dir / f"uc-{name}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "f.png").write_bytes(b"png")
    return insert_asset(workspace_id, kind="image", name=name, file_key=f"media/uc-{name}/f.png"), folder


def test_a_viewer_is_refused_by_the_domain_itself_not_only_by_a_route() -> None:
    workspace_id, viewer = _workspace_with("viewer")
    asset_id = insert_asset(workspace_id, kind="image", name="a")
    with SessionLocal() as db:
        who = _user(db, viewer)
        assert use_cases.readable(db, who, asset_id).id == asset_id, "看得到"
        with pytest.raises(PermissionDenied):
            use_cases.update_asset(db, who, asset_id, name="改名")
        with pytest.raises(PermissionDenied):
            use_cases.delete_asset(db, who, asset_id)


def test_an_outsider_does_not_even_learn_the_asset_exists() -> None:
    workspace_id, _ = _workspace_with("viewer")
    asset_id = insert_asset(workspace_id, kind="image", name="a")
    second_client("stranger")
    with SessionLocal() as db:
        with pytest.raises(NotVisible):
            use_cases.readable(db, _user(db, "stranger"), asset_id)


def test_a_batch_delete_is_all_or_nothing_and_files_go_only_after_commit() -> None:
    workspace_id, editor = _workspace_with("editor")
    first, first_dir = _asset_with_file(workspace_id, "one")
    second, second_dir = _asset_with_file(workspace_id, "two")

    with pytest.raises(RuntimeError), unit_of_work() as db:
        who = _user(db, editor)
        use_cases.delete_asset(db, who, first)
        use_cases.delete_asset(db, who, second)
        raise RuntimeError("第三步失败")
    with SessionLocal() as db:
        assert db.get(Asset, first) is not None and db.get(Asset, second) is not None, "回滚了就一份都不少"
    assert first_dir.is_dir() and second_dir.is_dir(), "回滚了文件也不能先被清掉"

    with unit_of_work() as db:
        who = _user(db, editor)
        use_cases.delete_asset(db, who, first)
        assert first_dir.is_dir(), "提交之前文件还在"
    assert not first_dir.is_dir(), "提交之后清掉"
    assert second_dir.is_dir()


def test_update_tidies_tags_and_leaves_the_commit_to_the_caller() -> None:
    workspace_id, editor = _workspace_with("editor")
    asset_id = insert_asset(workspace_id, kind="image", name="a")
    with SessionLocal() as db:
        use_cases.update_asset(db, _user(db, editor), asset_id, tags=[" x ", "x", "", "y" * 50])
        db.rollback()
    with SessionLocal() as db:
        assert db.get(Asset, asset_id).tags in (None, []), "领域函数自己不提交"
    with unit_of_work() as db:
        use_cases.update_asset(db, _user(db, editor), asset_id, tags=[" x ", "x", "", "y" * 50])
    with SessionLocal() as db:
        assert db.get(Asset, asset_id).tags == ["x", "y" * use_cases.TAG_MAX_CHARS]
