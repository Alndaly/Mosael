"""这台电脑上的文件,是**部署主人的**私有资源。

后端跑在某一台机器上。单机用时那台机器就是用户自己的,读本机任意路径天经地义;可一旦同事经团队
部署或远程访问进了同一个后端,「本机路径」指的就是**别人电脑上的文件** —— 工作流上传节点填一个
`~/.ssh/id_rsa`,浏览器会话替他把私钥塞进任意网页的文件框;智能体「在本机跑代码」更是整台机器。

规则只有一条,判在读的那一刻、只判在这里:

- 这次的人是**部署管理员**(`User.is_deployment_admin`)—— 整台机器都可以。单机用时唯一的那个人
  就是管理员,所以本机用户零摩擦;
- 否则只能读两种:素材库里的文件(`asset_file`,按工作区校验过的素材),或者落在管理员**明确共享
  给成员的本机文件夹**里的路径(部署级设置,见 `set_shared_folders`)。

判断前一律 realpath:符号链接、`..`、大小写之外的一切绕路都先展开成真实位置,再做包含判断 ——
否则共享文件夹里放一个指向 `~/.ssh` 的软链接,就把整个家目录共享出去了。

`actor` 是**必填**的关键字参数,没有默认值;说不出是谁在读(None)一律拒绝,连共享文件夹也不给 ——
和 `sharing.may_use` 同一个口径。放行的结果是一个 `HostFile`:只有这个模块造得出它,于是「把这个
文件交给浏览器上传」之类的下游(`browser.upload_file`)只收它、不收裸字符串,路径绕不过这里。
棘轮:`tests/test_host_files_belong_to_the_deployment_owner.py`。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.db.models import Asset, User
from app.domain import deployment
from app.domain.authority import Actor, Voucher, ensure
from app.domain.permissions import PermissionDenied


class HostFileError(LocalizedError, ValueError):
    """路径本身不对(不是绝对路径、不是文件、共享文件夹设不进去)。带文案 key(`hostErr_*`),api 回 422。"""


class HostFileNotAllowed(PermissionDenied):
    """这个人不能读这台电脑上的这个位置。是 `PermissionDenied`,api 回 403。"""


class HostFileNotVouched(HostFileNotAllowed):
    """跑的人读得了,但被执行的那一版工作流是别人改的,改它的人读不了 —— 要管理员认可这一版。

    `details["attest"]` 说是哪条工作流的哪一版(见 domain/authority)。
    """

    def __init__(self, key: str, voucher: Voucher) -> None:
        super().__init__(key, workflow=voucher.workflow_name, revision=voucher.revision)
        self.details = voucher.attest_details()


@dataclass(frozen=True)
class HostFile:
    """一份**已经放行**的本机文件(真实路径)。只有本模块构造它 —— 见模块说明。"""

    path: Path

    def __str__(self) -> str:
        return str(self.path)


def _real(raw: str | os.PathLike[str]) -> Path:
    return Path(os.path.realpath(os.path.expanduser(os.fspath(raw))))


def _is_admin(db: Session, actor: str | None) -> bool:
    if not actor:
        return False
    user = db.get(User, actor)
    return bool(user is not None and user.is_deployment_admin)


def shared_folders(db: Session) -> list[str]:
    """管理员共享给成员的本机文件夹(存的时候已展开成真实路径)。"""
    return list(deployment.shared_host_folders(db))


def _in_shared_folder(db: Session, real: Path) -> bool:
    for folder in shared_folders(db):
        # 存的时候展开过一次,这里**再展开一次**:文件夹本身可能在那之后被换成了软链接。
        root = _real(folder)
        if root.parent == root:
            continue  # 根目录不算共享(见 set_shared_folders),库里就算混进来也不认
        if real == root or real.is_relative_to(root):
            return True
    return False


def may_read(db: Session, path: str | os.PathLike[str], *, actor: str | None) -> bool:
    """这**一个人**读不读得了这个位置(不查文件存不存在)。一次运行的全部授权见 `ensure_readable`。"""
    if not actor:
        return False
    if _is_admin(db, actor):
        return True
    return _in_shared_folder(db, _real(path))


def ensure_readable(db: Session, path: str | os.PathLike[str], *, actor: Actor) -> HostFile:
    """读本机一个**用户给出的**路径之前,必须先过这里。返回放行后的真实路径。

    先判权限、再判存在:没权限的人不该从「文件不存在 / 存在」的区别里探出别人机器上有什么。
    工作流里 `actor` 是这次运行的 `Authority`:被执行的每一版图也要有一个读得了它的担保人。
    """
    raw = os.fspath(path).strip() if isinstance(path, str) else os.fspath(path)
    if not raw or not Path(os.path.expanduser(raw)).is_absolute():
        raise HostFileError("hostErr_notAbsolute")
    real = _real(raw)
    ensure(
        actor,
        lambda user: may_read(db, real, actor=user),
        denied=lambda: HostFileNotAllowed("hostErr_notReadable"),
        unvouched=lambda voucher: HostFileNotVouched("hostErr_notVouched", voucher),
    )
    if not real.is_file():
        raise HostFileError("hostErr_notAFile")
    return HostFile(real)


def asset_file(asset: Asset) -> HostFile:
    """素材库里的一份文件。**调用方负责先确认这份素材在它的工作区里** —— 素材库本身就是按工作区
    授权的,它的文件落在数据目录下,不是任何人电脑上的私有路径。"""
    from app.media.paths import resolve_key

    if not asset.file_key:
        raise HostFileError("hostErr_notAFile")
    return HostFile(resolve_key(asset.file_key))


def ensure_whole_machine(db: Session, *, actor: Actor) -> None:
    """在这台电脑上**直接跑代码**(不隔离):它能读写任何文件,所以只认部署管理员,共享文件夹不算数。"""
    ensure(
        actor,
        lambda user: _is_admin(db, user),
        denied=lambda: HostFileNotAllowed("hostErr_codeNeedsAdmin"),
        unvouched=lambda voucher: HostFileNotVouched("hostErr_notVouched", voucher),
    )


def set_shared_folders(db: Session, folders: list[str]) -> list[str]:
    """改「共享给成员的本机文件夹」。**调用方负责 `ensure_deployment_admin`。**

    每一项都得是这台机器上存在的绝对路径的文件夹;存真实路径(展开软链接和 `..`),去重保序。
    根目录不收 —— 共享 `/` 等于把整台机器交出去,那不是「一个文件夹」。
    """
    cleaned: list[str] = []
    for raw in folders:
        text = str(raw or "").strip()
        if not text:
            continue
        if not Path(os.path.expanduser(text)).is_absolute():
            raise HostFileError("hostErr_folderNotAbsolute", path=text)
        real = _real(text)
        if real.parent == real:
            raise HostFileError("hostErr_folderIsRoot")
        if not real.is_dir():
            raise HostFileError("hostErr_folderMissing", path=text)
        if str(real) not in cleaned:
            cleaned.append(str(real))
    deployment.set_shared_host_folders(db, cleaned)
    return cleaned
