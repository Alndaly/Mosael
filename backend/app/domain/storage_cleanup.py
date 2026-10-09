"""数据目录里**没人认领的文件**:删工作区、删账号时清掉它们的文件;历史上留下的孤儿列出来,部署管理员确认后才删。

为什么要有:行由外键 CASCADE 带走,文件没人管。删工作区此前只清了 3D 模型和技能文件夹,素材(原件 + 代理 + 缩略图 + 波形)、
音色样本、LUT、字体全留在盘上 —— 确认框写着「永久移除」,声纹样本却还在本机;删账号连那两样都没清(它直接 `db.delete`
独占的工作区,绕过了 `members.delete_workspace`)。入库失败、导出被打断也会留下没人认领的目录。

**已经留下的不自动删。** 判断「没人认领」靠的是此刻库里没有对应的行:恢复到一半的备份、换过数据目录的库,都可能让一份
其实有用的文件看起来像孤儿。所以只列出来,由部署管理员在管理控制台看过、勾选、确认之后才删;删的那一刻再判一遍,只删仍然
是孤儿、而且已经放了足够久的(刚开始导入的素材,目录先于那一行落库,`ORPHAN_GRACE` 之内不算)。
"""

from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings

logger = logging.getLogger(__name__)
from app.db.models import Asset, Font, Lut, User, Voice, Workspace
from app.media.paths import WORKSPACE_MEDIA_CATEGORIES, workspace_media_dirs

#: 放了多久才算孤儿。导入一份大视频时,素材目录先建、文件先落盘,那一行要等写完才提交 —— 那段时间它看起来没人认领。
ORPHAN_GRACE_SECONDS = 3600

#: 按工作区分目录、目录下再按行 id 分的几类:目录名就是那一行的 id。
_PER_ROW = {"assets": Asset, "voices": Voice, "luts": Lut, "fonts": Font}


@dataclass(frozen=True)
class Orphan:
    """一处没人认领的文件(或目录)。`key` 是相对数据目录的路径,删的时候就按它对。"""

    key: str
    #: 为什么说它没人认领:workspace_gone(工作区已经删了)/ row_gone(那一条素材、音色、LUT、字体已经删了)/
    #: avatar_unused(没有账号用这张头像)
    reason: str
    bytes: int
    modified_at: datetime


def delete_workspace_files(workspace_id: str) -> None:
    """删工作区之后,它在 media/ 下的全部目录一起删。由 `members.delete_workspace` 在**提交之后**调。

    rmtree 失败(占用/权限)要留痕:确认框承诺的是「永久移除」,清不掉却没人知道,那批文件就
    永远留在盘上 —— 这正是孤儿扫描存在的理由,它会发现它们。
    """
    for directory in workspace_media_dirs(workspace_id):
        if not directory.is_dir():
            continue
        try:
            shutil.rmtree(directory)
        except OSError as exc:
            logger.warning("删工作区 %s 的目录 %s 没删干净: %s(孤儿扫描会再发现它们)", workspace_id, directory, exc)


def delete_user_files(avatar_key: str) -> None:
    """删账号之后,他的头像文件一起删。只认 avatars/ 下的键(和读头像的路由同一条防线)。"""
    key = (avatar_key or "").strip()
    if key.startswith("avatars/") and ".." not in Path(key).parts:
        (settings.data_dir / key).unlink(missing_ok=True)


def find_orphans(db: Session, *, now: float | None = None) -> list[Orphan]:
    """数据目录里此刻没人认领、而且放了足够久的那些。只读,什么都不删。"""
    moment = time.time() if now is None else now
    workspaces = set(db.scalars(select(Workspace.id)))
    found: list[Orphan] = []
    for category in WORKSPACE_MEDIA_CATEGORIES:
        root = settings.media_dir / category
        if not root.is_dir():
            continue
        model = _PER_ROW.get(category)
        for workspace_dir in sorted(_children(root)):
            if workspace_dir.name not in workspaces:
                found.extend(_orphan(workspace_dir, "workspace_gone", moment))
                continue
            if model is None:
                continue
            ids = {str(one) for one in db.scalars(select(model.id).where(model.workspace_id == workspace_dir.name))}
            for item_dir in sorted(_children(workspace_dir)):
                if item_dir.name not in ids:
                    found.extend(_orphan(item_dir, "row_gone", moment))
    avatars = settings.data_dir / "avatars"
    if avatars.is_dir():
        used = {str(key) for key in db.scalars(select(User.avatar_key)) if key}
        for avatar in sorted(avatars.iterdir()):
            if avatar.is_file() and f"avatars/{avatar.name}" not in used:
                found.extend(_orphan(avatar, "avatar_unused", moment))
    #: 老版本的导出中转目录。现在的导出写在暂存目录里、编完搬进素材库(见 domain/render、media/scratch),这里不会
    #: 再有新东西;留下的是老版本被打断的半截成片、没删的 .ass / 文字图片(某台机器上攒过几百 MB)。早年的版本里它也许
    #: 是某次导出唯一的一份,所以不自动删:列出来,管理员看过再删(MED-6)。
    #: 整个目录算一项(一台机器上攒过两百多个文件,一行一个没法看)。
    exports = settings.data_dir / "exports"
    if exports.is_dir() and not exports.is_symlink() and any(exports.iterdir()):
        found.extend(_orphan(exports, "export_leftover", moment))
    return found


def delete_orphans(db: Session, keys: list[str]) -> tuple[list[str], list[str]]:
    """删掉管理员勾选的那些孤儿。**删的那一刻再判一遍**:只删此刻仍然没人认领(而且放够了时间)的,其余原样跳过。
    返回 (删掉的, 跳过的)。键不在此刻的孤儿清单里的一律跳过 —— 交上来的只能是清单里的东西,不能借它删别的路径。"""
    current = {orphan.key: orphan for orphan in find_orphans(db)}
    deleted: list[str] = []
    skipped: list[str] = []
    for key in dict.fromkeys(keys):
        if key not in current:
            skipped.append(key)
            continue
        target = settings.data_dir / key
        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("孤儿 %s 没删掉: %s", key, exc)
        # 没删成的**不许**报「已删除」—— 控制台说删了而文件还在,那是说谎;归进跳过,管理员看得见。
        if target.exists():
            skipped.append(key)
            continue
        deleted.append(key)
    return deleted, skipped


def _children(directory: Path) -> list[Path]:
    return [child for child in directory.iterdir() if child.is_dir() and not child.is_symlink()]


def _orphan(path: Path, reason: str, moment: float) -> list[Orphan]:
    modified = _latest_mtime(path)
    if moment - modified < ORPHAN_GRACE_SECONDS:
        return []
    return [Orphan(
        key=path.relative_to(settings.data_dir).as_posix(),
        reason=reason,
        bytes=_size(path),
        modified_at=datetime.fromtimestamp(modified, UTC),
    )]


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(one.stat().st_size for one in path.rglob("*") if one.is_file() and not one.is_symlink())


def _latest_mtime(path: Path) -> float:
    """这处东西里最近一次被写的时间(目录按它里面最新的那个文件算 —— 导入时文件还在写,目录的时间不会动)。"""
    latest = path.stat().st_mtime
    if path.is_dir():
        for one in path.rglob("*"):
            try:
                latest = max(latest, one.stat().st_mtime)
            except OSError:
                continue
    return latest


__all__ = ["ORPHAN_GRACE_SECONDS", "Orphan", "delete_orphans", "delete_user_files", "delete_workspace_files", "find_orphans"]
