"""删工作区、删账号之后,它们的文件不留在盘上;已经留下的孤儿只列出来,管理员确认后才删(SEC-7)。

此前删工作区只清了 3D 模型和技能文件夹:素材原件、代理、缩略图、波形,音色样本(声纹),LUT,字体全留在盘上 ——
确认框写着「永久移除」。删账号连那两样都没清:它直接 `db.delete` 独占的工作区,绕过了 `members.delete_workspace`。
"""

from __future__ import annotations

import inspect
import os
import time
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import User
from app.media import paths

RATCHET = True


def _png(path: Path) -> Path:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), "red").save(path)
    return path


def _files_of(workspace_id: str) -> list[str]:
    return sorted(str(p.relative_to(settings.media_dir)) for p in settings.media_dir.rglob("*")
                  if p.is_file() and f"/{workspace_id}/" in f"/{p.relative_to(settings.media_dir).as_posix()}")


def _fill(client, workspace_id: str, tmp_path: Path) -> None:
    """往工作区里放每一类按工作区存的东西:素材(经接口导入,带缩略图)、音色、LUT、字体、3D 模型、场景预览。"""
    with _png(tmp_path / "pic.png").open("rb") as handle:
        imported = client.post("/api/assets/import", data={"workspace_id": workspace_id},
                               files={"file": ("pic.png", handle, "image/png")})
    assert imported.status_code == 200, imported.text
    for directory in (paths.voice_dir(workspace_id, "v1"), paths.lut_dir(workspace_id, "l1"),
                      paths.font_dir(workspace_id, "f1"), paths.scene_model_dir(workspace_id),
                      paths.scene_preview_dir(workspace_id)):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "payload.bin").write_bytes(b"x" * 64)


def test_删工作区_它在_media_下的文件全部删掉(tmp_path) -> None:
    from tests.util import fresh_client

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "要删的"}).json()["id"]
    _fill(client, workspace, tmp_path)
    assert len(_files_of(workspace)) >= 6
    assert client.delete(f"/api/workspaces/{workspace}").status_code == 204
    assert _files_of(workspace) == [], "删了工作区,素材、音色、LUT、字体、3D 模型、预览都不该还在盘上"
    for directory in paths.workspace_media_dirs(workspace):
        assert not directory.exists()


def test_删账号_独占工作区的文件和头像一起删(tmp_path) -> None:
    from tests.util import fresh_client, login_as, second_client, user_id

    admin = fresh_client()
    member = second_client("leaver")
    workspace = member.post("/api/workspaces", json={"name": "独占"}).json()["id"]
    _fill(member, workspace, tmp_path)
    with _png(tmp_path / "me.png").open("rb") as handle:
        assert member.post("/api/auth/me/avatar", files={"file": ("me.png", handle, "image/png")}).status_code == 200
    with SessionLocal() as db:
        avatar = settings.data_dir / db.get(User, user_id("leaver")).avatar_key
    assert avatar.is_file()

    login_as(admin, "tester")
    assert admin.delete(f"/api/admin/users/{user_id('leaver')}").status_code == 204
    assert _files_of(workspace) == []
    assert not avatar.exists(), "删了账号,他的头像文件不该还在"


def test_每一类按工作区存的目录都登记在册() -> None:
    """media/paths 里每个按工作区分的 *_dir 都要在 WORKSPACE_MEDIA_CATEGORIES 里 —— 漏了,删工作区时那一类文件就留在盘上。"""
    expected = set(paths.workspace_media_dirs("WS"))
    for name, function in inspect.getmembers(paths, inspect.isfunction):
        if not name.endswith("_dir") or function.__module__ != paths.__name__:
            continue
        parameters = list(inspect.signature(function).parameters)
        if not parameters or parameters[0] != "workspace_id":
            continue
        produced = function("WS", *["ITEM"] * (len(parameters) - 1))
        root = Path(*produced.parts[: produced.parts.index("WS") + 1])
        assert root in expected, f"{name} 按工作区存文件,但 {root} 不在 WORKSPACE_MEDIA_CATEGORIES 里"


def _age(path: Path, seconds: float) -> None:
    """把这处东西(连同里面的文件)的修改时间往前拨。"""
    stamp = time.time() - seconds
    for one in [path, *path.rglob("*")] if path.is_dir() else [path]:
        os.utime(one, (stamp, stamp))


def test_已经留下的孤儿只列出来_确认后才删_删的那一刻再判一遍(tmp_path) -> None:
    from app.domain.storage_cleanup import ORPHAN_GRACE_SECONDS
    from tests.util import fresh_client, second_client

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "在的"}).json()["id"]
    with _png(tmp_path / "keep.png").open("rb") as handle:
        kept = client.post("/api/assets/import", data={"workspace_id": workspace},
                           files={"file": ("keep.png", handle, "image/png")}).json()["id"]
    gone_workspace = settings.media_dir / "assets" / "workspace-that-is-gone"
    gone_row = settings.media_dir / "assets" / workspace / "asset-that-is-gone"
    unused_avatar = settings.data_dir / "avatars" / "nobody-1.png"
    fresh = settings.media_dir / "assets" / workspace / "still-importing"
    for one in (gone_workspace / "x" / "a.mp4", gone_row / "b.mp4", fresh / "c.mp4"):
        one.parent.mkdir(parents=True, exist_ok=True)
        one.write_bytes(b"y" * 128)
    _png(unused_avatar)
    for one in (gone_workspace, gone_row, unused_avatar, settings.media_dir / "assets" / workspace / kept):
        _age(one, ORPHAN_GRACE_SECONDS + 60)

    listed = client.get("/api/admin/storage/orphans")
    assert listed.status_code == 200, listed.text
    keys = {item["key"]: item["reason"] for item in listed.json()["items"]}
    assert keys == {
        "media/assets/workspace-that-is-gone": "workspace_gone",
        f"media/assets/{workspace}/asset-that-is-gone": "row_gone",
        "avatars/nobody-1.png": "avatar_unused",
    }, "在用的素材、刚开始导入的目录都不算孤儿"
    assert gone_workspace.exists(), "列出来不等于删"

    assert second_client().get("/api/admin/storage/orphans").status_code == 403, "只有部署管理员看得到这张清单"

    deleted = client.post("/api/admin/storage/orphans/delete", json={"keys": [
        "media/assets/workspace-that-is-gone",
        f"media/assets/{workspace}/{kept}",  # 在用的:不在清单里,跳过
        "../outside",  # 借它删别的路径:跳过
    ]}).json()
    assert deleted == {"deleted": ["media/assets/workspace-that-is-gone"],
                       "skipped": [f"media/assets/{workspace}/{kept}", "../outside"]}
    assert not gone_workspace.exists()
    assert gone_row.exists() and unused_avatar.exists(), "没勾选的不动"
    assert (settings.media_dir / "assets" / workspace / kept).exists()


@pytest.fixture(autouse=True)
def _clean_media():
    yield
    for name in ("workspace-that-is-gone",):
        target = settings.media_dir / "assets" / name
        if target.exists():
            import shutil

            shutil.rmtree(target, ignore_errors=True)
