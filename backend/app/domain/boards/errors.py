"""画板领域的错误。和画布相关的每一层(形状、引用、读写、回执)都从这里抛。"""

from __future__ import annotations

from app.core.i18n import LocalizedError


class BoardDomainError(LocalizedError, ValueError):
    pass


class BoardNotFound(BoardDomainError):
    """这个工作区里没有这张板(或这一项)。"""


class BoardRevisionConflict(BoardDomainError):
    """The caller edited a projection older than the server's current board."""

    def __init__(self, base_revision: int, current_revision: int):
        self.base_revision = base_revision
        self.current_revision = current_revision
        super().__init__("boardErr_revisionConflict", base=base_revision, current=current_revision)


def item_not_found(item_id: str) -> BoardNotFound:
    """「画板项不存在」。没给 id 是另一句话 —— 把「(空)」当成 id 填进去就翻不动了。"""
    return BoardNotFound("boardErr_itemNotFound", item_id=item_id) if item_id else BoardNotFound("boardErr_itemIdMissing")


def _field_error(item_key: str, bare_key: str, field: str, item_id: str, **params: object) -> BoardDomainError:
    """坐标 / 尺寸不合法。带不带「画板项 xx 的」是两句话,不是往前面拼一截。"""
    if item_id:
        return BoardDomainError(item_key, item_id=item_id, field=field, **params)
    return BoardDomainError(bare_key, field=field, **params)
