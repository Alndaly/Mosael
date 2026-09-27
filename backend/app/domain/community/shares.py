"""把一张画板分享成一个链接(ADR 0026 §5)。

「生成链接」和「更新分享」是**同一件事**:做一份快照、传上去、提交。服务端按画板的 `board_key` 认出
「同一张画板的新版本」,于是第二次起链接不变、版本加一。上传走三步:

1. `POST /shares/uploads`:报上每个文件的哈希、大小、类型,服务端回**缺的那几个**的上传地址
   (已经有的跳过 —— 这就是去重,也是「断了能续」:上一次传了一半,这一次只剩没传完的);
2. 逐个 `PUT`:流式读盘、不整份进内存;单个文件失败重试几次;
3. `POST /shares`:提交快照,拿回 `{slug, url, version}`,记进本机(`board_shares`)。

整件事是一个任务(`board_share`):进度在任务中心里,能取消(每传完一个文件看一眼)。标题、可见性的
修改和撤回是同步的一次请求。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.db.models import Board, BoardShare, Job
from app.domain.community import snapshot as snapshots
from app.domain.community.accounts import CommunityClient, read_json
from app.domain.community.errors import CommunityError, Rejected, Unreachable
from app.domain.community.transport import absolute
from app.domain.jobs import create_job, dispatch_job, emit_job_event, finish_job, run_job_guarded, say, was_cancelled

logger = logging.getLogger(__name__)

VISIBILITIES = ("unlisted", "public")
MAX_TITLE_CHARS = 180
#: 一个文件最多传几次(第一次 + 重试)。
UPLOAD_ATTEMPTS = 3
UPLOAD_TIMEOUT_SECONDS = 600.0
_UPLOAD_CHUNK = 1024 * 1024


def pause(seconds: float) -> None:
    """重试之间等一会儿。测试换成不等。"""
    time.sleep(seconds)


def _clean_title(title: str, board: Board) -> str:
    return (title or "").strip()[:MAX_TITLE_CHARS] or board.name


def _check_visibility(visibility: str) -> str:
    if visibility not in VISIBILITIES:
        raise CommunityError("communityErr_badVisibility", value=visibility)
    return visibility


def current(db: Session, board: Board) -> BoardShare | None:
    return db.get(BoardShare, board.id)


def start(db: Session, *, board: Board, user_id: str, title: str, visibility: str) -> Job:
    """排一个分享任务。连没连、超没超限额,在排之前就说 —— 不要让人等进度条走完才知道。"""
    CommunityClient.for_user(db, user_id)
    _check_visibility(visibility)
    snapshots.check_limits(db, board)
    job = create_job(
        db,
        workspace_id=board.workspace_id,
        kind="board_share",
        created_by=user_id,
        payload={"board_id": board.id, "subject": board.name, "title": _clean_title(title, board), "visibility": visibility},
        message="jobMsg_boardShareQueued",
    )
    db.commit()
    job_id, board_id = job.id, board.id
    dispatch_job(db, job, lambda: run_job_guarded(job_id, lambda: _body(job_id, board_id, user_id), what="画板分享"))
    return job


def _progress(db: Session, job: Job, fraction: float) -> None:
    job.progress = max(0.0, min(1.0, fraction))
    db.commit()


def _cancelled(db: Session, job: Job) -> bool:
    db.refresh(job)
    return was_cancelled(job)


def _body(job_id: str, board_id: str, user_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        board = db.get(Board, board_id)
        if job is None:
            return
        if not finish_job(db, job, status="running", progress=0.02):
            db.commit()
            return
        say(job, "jobMsg_boardShareRunning")
        emit_job_event(db, job.id, "job.running", {})
        db.commit()
        if board is None:
            raise CommunityError("communityErr_boardGone")
        payload = dict(job.payload or {})
        client = CommunityClient.for_user(db, user_id)

        made = snapshots.build(db, board)
        _progress(db, job, 0.2)

        missing = _missing_files(client, made)
        by_hash = {one.sha256: one for one in made.files}
        for index, (digest, target) in enumerate(missing):
            if _cancelled(db, job):
                return
            _upload(client, by_hash[digest], target)
            _progress(db, job, 0.2 + 0.7 * (index + 1) / max(1, len(missing)))
        if _cancelled(db, job):
            return

        result = client.call(
            "POST",
            "/shares",
            json={
                "board_key": board.board_key,
                "title": payload.get("title") or board.name,
                "visibility": payload.get("visibility") or "unlisted",
                "snapshot": made.body,
            },
        )
        share = _remember(db, board, user_id, result, title=str(payload.get("title") or board.name),
                          visibility=str(payload.get("visibility") or "unlisted"), origin=client.origin)
        outcome = {"board_id": board.id, "slug": share.slug, "url": share.url, "version": share.version,
                   "uploaded": len(missing), "files": len(made.files)}
        if finish_job(db, job, status="succeeded", progress=1.0, result=outcome):
            say(job, "jobMsg_boardShareDone", version=share.version)
            emit_job_event(db, job.id, "job.succeeded", dict(outcome))
        db.commit()
        logger.info("画板 %s 分享为 %s(第 %s 版,传了 %s/%s 个文件)", board.id, share.slug, share.version,
                    len(missing), len(made.files))


def _missing_files(client: CommunityClient, made: snapshots.Snapshot) -> list[tuple[str, dict[str, Any]]]:
    """第一步:问服务端缺哪几个。回 `[(sha256, {"url": …, "headers": {…}})]`,只含缺的。"""
    if not made.files:
        return []
    answer = client.call(
        "POST",
        "/shares/uploads",
        json={"files": [{"sha256": one.sha256, "size": one.size, "content_type": one.content_type} for one in made.files]},
    )
    known = {one.sha256 for one in made.files}
    wanted: list[tuple[str, dict[str, Any]]] = []
    for entry in answer.get("uploads") or []:
        if not isinstance(entry, dict) or entry.get("sha256") not in known or not entry.get("url"):
            continue
        headers = entry.get("headers") if isinstance(entry.get("headers"), dict) else {}
        wanted.append((str(entry["sha256"]), {"url": absolute(client.origin, str(entry["url"])),
                                             "headers": {str(k): str(v) for k, v in headers.items()}}))
    return wanted


def _chunks(path: Path) -> Iterator[bytes]:
    with path.open("rb") as handle:
        while block := handle.read(_UPLOAD_CHUNK):
            yield block


def _upload(client: CommunityClient, file: snapshots.SnapshotFile, target: dict[str, Any]) -> None:
    """第二步:把一个文件 PUT 上去(流式)。连不上 / 对方 5xx 就重试;对方明确拒绝(4xx)不重试。"""
    url = target["url"]
    headers = {"Content-Type": file.content_type, "Content-Length": str(file.size), **target["headers"]}
    last: CommunityError | None = None
    for attempt in range(UPLOAD_ATTEMPTS):
        if attempt:
            pause(min(8.0, 1.5 * 2 ** (attempt - 1)))
        try:
            response = client.request(
                "PUT",
                url,
                # 服务自己的地址(本地存储)要带令牌;预签名的对象存储地址不能带 —— 签名里不含它,S3 会拒。
                authed=client.owns(url),
                headers=headers,
                content=lambda: _chunks(file.path),
                timeout=UPLOAD_TIMEOUT_SECONDS,
            )
        except Unreachable as exc:
            last = exc
            logger.info("上传 %s 第 %s 次没成:%s", file.sha256[:12], attempt + 1, exc)
            continue
        if response.status_code >= 500:
            last = Unreachable(f"HTTP {response.status_code}")
            continue
        read_json(response)  # 4xx:对方拒绝了这个文件 —— 重试也一样,原话报出去
        return
    raise CommunityError("communityErr_uploadFailed", detail=str(last) if last else "")


def _remember(db: Session, board: Board, user_id: str, result: dict[str, Any], *, title: str, visibility: str,
              origin: str) -> BoardShare:
    """第三步的回包记进本机:面板下次打开就知道「已分享 · 第几版」。"""
    slug = str(result.get("slug") or "")
    if not slug:
        raise CommunityError("communityErr_badResponse")
    row = db.get(BoardShare, board.id)
    if row is None:
        row = BoardShare(board_id=board.id, slug=slug, url="")
        db.add(row)
    row.slug = slug
    row.url = absolute(origin, str(result.get("url") or f"/b/{slug}"))
    row.version = int(result.get("version") or 1)
    row.title = title
    row.visibility = visibility
    row.shared_by = user_id
    db.commit()
    db.refresh(row)
    return row


def update(db: Session, *, board: Board, user_id: str, title: str | None, visibility: str | None) -> BoardShare:
    """改标题 / 可见性(`PATCH /shares/{slug}`),不发新版本。"""
    row = current(db, board)
    if row is None:
        raise CommunityError("communityErr_notShared")
    body: dict[str, Any] = {}
    if title is not None:
        body["title"] = _clean_title(title, board)
    if visibility is not None:
        body["visibility"] = _check_visibility(visibility)
    if not body:
        return row
    client = CommunityClient.for_user(db, user_id)
    client.call("PATCH", f"/shares/{row.slug}", json=body)
    row.title = body.get("title", row.title)
    row.visibility = body.get("visibility", row.visibility)
    db.commit()
    db.refresh(row)
    return row


def withdraw(db: Session, *, board: Board, user_id: str) -> None:
    """撤回(`DELETE /shares/{slug}`):链接立刻失效。对方说「本来就没有了」也算撤回成功。"""
    row = current(db, board)
    if row is None:
        return
    client = CommunityClient.for_user(db, user_id)
    try:
        client.call("DELETE", f"/shares/{row.slug}")
    except Rejected as exc:
        if exc.status not in (404, 410):
            raise
    db.delete(row)
    db.commit()
