"""按内容哈希存的文件被一份提交引用时的核对:是不是这个人上传过的、内容对不对得上。

画板快照(api/shares.py)和资产分享包(submissions.submit_asset)都只按哈希引用文件,文件先走三步上传。
引用之前要确认两件事,两处用的是这一份:

- 这个哈希**是这个人上传过的**(BlobOwner)—— 否则知道别人一张图的哈希,就能把它挂进自己的分享里;
- 内容**核对过**:经服务自己收的上传在 PUT 时边收边算过;S3 直传的,在这里读回来算一遍,对不上就删掉那份对象。
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable

from sqlalchemy.orm import Session

from community.context import Context
from community.db import utcnow
from community.errors import ApiError
from community.logs import log_event
from community.models import BLOB_READY, Blob, BlobOwner, User

logger = logging.getLogger(__name__)


def verify_remote(ctx: Context, blob: Blob) -> bool:
    """S3 直传的文件:读回来算一遍哈希。对不上就删掉那份对象。"""
    digest = hashlib.sha256()
    size = 0
    try:
        for chunk in ctx.storage.iter_chunks(blob.storage_key):
            size += len(chunk)
            if size > ctx.settings.share_max_file_bytes:
                break
            digest.update(chunk)
    except Exception as exc:  # noqa: BLE001 - 对象不存在 / 读不出都算「没上传」
        log_event(logger, "remote blob unreadable", logging.INFO, error=type(exc).__name__)
        return False
    if digest.hexdigest() != blob.sha256 or size > ctx.settings.share_max_file_bytes:
        ctx.storage.delete(blob.storage_key)
        return False
    blob.size = size
    return True


def claim_ready(ctx: Context, db: Session, user: User, hashes: Iterable[str]) -> dict[str, Blob]:
    """这些哈希都是 `user` 上传过、内容核对过的文件;返回哈希 → Blob。有一个不是就 422 `unknown_blob`。"""
    found: dict[str, Blob] = {}
    for sha in sorted(set(hashes)):
        blob = db.get(Blob, sha)
        if blob is None or db.get(BlobOwner, (user.id, sha)) is None:
            raise ApiError(422, "unknown_blob", sha256=sha)
        if blob.status != BLOB_READY:
            if ctx.storage.uploads_through_service or not verify_remote(ctx, blob):
                raise ApiError(422, "unknown_blob", sha256=sha)
            blob.status, blob.verified_at = BLOB_READY, utcnow()
        found[sha] = blob
    return found


__all__ = ["claim_ready", "verify_remote"]
