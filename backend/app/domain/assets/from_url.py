"""从链接导入素材:一个任务下若干条,逐条下完就入库。

**为什么是一个任务而不是每条一个**:用户勾的是「这几条」,他关心的是这一批什么时候好。拆成
N 个任务的话,任务中心会被一次勾选刷屏,而"还剩几条"要自己数。

**一条失败不拖垮整批**:已经下好的留在素材库里,失败的条数最后报出来。半小时的下载因为第七条
被下架而全部作废,是最不该发生的事。

入库走 `register_file_asset` —— 上传、本机注册、渲染产出、配音产出用的都是它(见 assets/importer
的说明)。这里只是第四个"字节从哪来",后面的探测、缩略图、波形、建记录完全一样。
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.db.models import Job
from app.domain.assets import register_file_asset
from app.domain.assets.source_url import remember_asset_source
from app.domain.jobs import create_job, dispatch_job, emit_job_event, say
from app.media import ytdlp

logger = logging.getLogger(__name__)

#: 一次最多勾多少条。播放列表能有几百条 —— 真要全下,分几次比一个跑三小时、中途失败说不清
#: 进度的任务好。
MAX_ITEMS = 50


class UrlImportError(RuntimeError):
    pass


def start_url_import(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
    items: list[dict[str, str]],
    kind: str,
    created_by: str | None,
    profile_id: str | None = None,
    max_height: int = 0,
) -> Job:
    """给这些链接排一次下载。`items` 是 `[{url, title}]` —— 标题来自探测,用于任务消息。"""
    chosen = [item for item in items if str(item.get("url") or "").strip()]
    if not chosen:
        raise UrlImportError("没有选中任何条目")
    if len(chosen) > MAX_ITEMS:
        raise UrlImportError(f"一次最多下载 {MAX_ITEMS} 条,先分几次来")
    if kind not in ("video", "audio"):
        raise UrlImportError("只能下载视频或音频")

    job = create_job(
        db,
        workspace_id=workspace_id,
        kind="url_import",
        created_by=created_by,
        payload={
            "project_id": project_id,
            "subject": str(chosen[0].get("title") or chosen[0].get("url") or "")[:80]
            + (f" 等 {len(chosen)} 条" if len(chosen) > 1 else ""),
            "items": chosen,
            "kind": kind,
            "profile_id": profile_id or "",
            "max_height": max_height,
        },
        message="jobMsg_urlImportRunning",
        message_params={"done": 0, "total": len(chosen)},
    )
    job_id = job.id
    dispatch_job(db, job, lambda: _run(job_id))
    return job


def _run(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        payload = job.payload or {}
        workspace_id = job.workspace_id
        project_id = payload.get("project_id")
        items: list[dict[str, Any]] = list(payload.get("items") or [])
        kind = str(payload.get("kind") or "video")
        profile_id = str(payload.get("profile_id") or "")
        max_height = int(payload.get("max_height") or 0)
        job.status = "running"
        emit_job_event(db, job.id, "job.running", {})
        db.commit()

    done = 0
    failed = 0
    failures: list[tuple[str, str]] = []
    asset_ids: list[str] = []
    total = len(items)
    workdir = Path(tempfile.mkdtemp(prefix="mosael-url-import-"))
    cookie_file = _cookie_file(workspace_id, profile_id, workdir) if profile_id else None
    try:
        for index, item in enumerate(items):
            title = str(item.get("title") or item.get("url") or "")
            try:
                def report(fraction: float, _text: str, index: int = index, title: str = title) -> None:
                    # 整批的进度 = 已完成的条数 + 当前这条的进度。只报当前条的话,进度条会在
                    # 每条开头掉回 0;只报条数的话,一条 20 分钟的下载看起来像卡住了。
                    with SessionLocal() as progress_db:
                        live = progress_db.get(Job, job_id)
                        if live is None:
                            return
                        live.progress = (index + fraction) / max(1, total)
                        say(live, "jobMsg_urlImportItem", n=index + 1, total=total, title=title[:40])
                        progress_db.commit()

                path = ytdlp.download(
                    item["url"],
                    kind=kind,
                    target_dir=workdir,
                    on_progress=report,
                    cookie_file=cookie_file,
                    max_height=max_height,
                )
            except ytdlp.YtdlpError as exc:
                failed += 1
                # 原因**本来就是现成的**:ytdlp._explain 已经把「HTTP Error 403」这类翻成了
                # 「站点拒绝了匿名取流,请选择已登录的浏览器档案」。它此前只进日志,而用户看到的
                # 是一句「没有一条下载成功」—— 既不说是哪一条,也不说该怎么办。
                failures.append((title[:40] or str(item.get("url") or "")[:40], str(exc)))
                logger.warning("从链接导入:第 %s 条失败:%s", index + 1, str(exc)[:200])
                continue

            with SessionLocal() as db:
                asset = register_file_asset(
                    db,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    source_path=path,
                    name=path.name,
                    source="downloaded",
                )
                remember_asset_source(asset, item["url"])
                db.commit()
                asset_ids.append(asset.id)
            path.unlink(missing_ok=True)
            done += 1

        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is None:
                return
            if done == 0:
                job.status = "failed"
                say(job, "jobMsg_urlImportFailed")
                job.error = failure_report(failures)
                emit_job_event(db, job.id, "job.failed", {})
            else:
                job.status = "succeeded"
                job.progress = 1.0
                # 部分失败也是成功的一种,但**不能都说成「完成」** —— 下好的那些是真的下好了,
                # 而少掉的几条只有说出来用户才知道要去补。
                if failed:
                    say(job, "jobMsg_urlImportPartial", done=done, failed=failed)
                    # 成功的任务也带 error:任务详情里它就显示在消息下面。「20 条成功 3 条失败」
                    # 里的那 3 条,不说清是哪几条、为什么,用户只能自己一条条比对。
                    job.error = failure_report(failures)
                else:
                    say(job, "jobMsg_urlImportDone", done=done)
                job.result = {"asset_ids": asset_ids, "done": done, "failed": failed}
                emit_job_event(db, job.id, "job.succeeded", {"asset_ids": asset_ids})
            db.commit()
    except Exception as exc:  # noqa: BLE001 — 任何意外都要落进任务行,否则它永远停在 running
        logger.exception("从链接导入任务 %s 失败", job_id)
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is not None:
                job.status = "failed"
                say(job, "jobMsg_urlImportFailed")
                job.error = str(exc)[:600]
                emit_job_event(db, job.id, "job.failed", {})
                db.commit()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


#: 失败清单最多列几条。一批 50 条全挂时,把 50 行原因糊进任务详情只会让人一行都不看;
#: 前几条加一句「还有 N 条」足够定位,而完整的那份仍在日志里。
_MAX_LISTED_FAILURES = 8


def failure_report(failures: list[tuple[str, str]]) -> str:
    """没下成的那几条各自为什么。

    yt-dlp 的原始报错混着 URL、格式 id 和 traceback,但 ytdlp._explain 已经把它翻成了一句
    能行动的话。这里只负责把那几句**带着是哪一条**交到用户面前。
    """
    if not failures:
        return "没有一条下载成功"
    reasons = {reason for _, reason in failures}
    if len(reasons) == 1 and len(failures) > 1:
        # 整批同一个原因(多半是登录态或代理),说一遍就够 —— 逐条重复同一句话只是噪音。
        return f"{len(failures)} 条都失败了:{failures[0][1]}"
    lines = [f"「{title}」:{reason}" for title, reason in failures[:_MAX_LISTED_FAILURES]]
    if len(failures) > _MAX_LISTED_FAILURES:
        lines.append(f"…… 还有 {len(failures) - _MAX_LISTED_FAILURES} 条,完整清单见日志")
    return "\n".join(lines)


def probe_url(url: str, *, workspace_id: str, profile_id: str = "", start: int = 0):
    """这个链接后面有什么(只读元数据)。带了浏览器档案就借它的登录态去探。

    探和下是同一个 cookie 来源 —— 探得到、下不到(或反过来)的话,用户看到的列表就是假的。
    """
    import shutil
    import tempfile

    from app.media import ytdlp

    workdir = Path(tempfile.mkdtemp(prefix="mosael-probe-")) if profile_id else None
    try:
        cookie_file = _cookie_file(workspace_id, profile_id, workdir) if workdir is not None else None
        return ytdlp.probe(url.strip(), cookie_file=cookie_file, start=start)
    finally:
        if workdir is not None:
            shutil.rmtree(workdir, ignore_errors=True)


def _cookie_file(workspace_id: str, profile_id: str, workdir: Path) -> Path | None:
    """把浏览器池档案里的登录态借出来,写成 yt-dlp 认的 cookies.txt。

    **登录态只有 Electron 那一侧有** —— 它存在档案的持久分区里,后端看不到。所以走既有的
    动作队列问它要(见 domain/browser.run_action),和 RPA 节点、发布执行器同一条桥。

    取不到就返回 None 而不是抛:没有 cookie 只是"下不了需要登录的那些",而公开内容照样能下 ——
    为了一个可能用不上的登录态让整批下载失败,是把辅助手段当成了前提。
    """
    from app.domain import browser

    session = None
    try:
        with SessionLocal() as db:
            session = browser.open_session(
                db, workspace_id=workspace_id, profile_id=profile_id, owner_kind="workflow", owner_id=None,
            )
            session_id = session.id
        result = browser.run_action(session_id, "cookies", {})
        lines = [str(line) for line in (result.get("value") or []) if str(line).strip()]
        if not lines:
            logger.info("浏览器档案 %s 里没有 cookie,按公开内容下载", profile_id)
            return None
        target = workdir / "cookies.txt"
        target.write_text("# Netscape HTTP Cookie File\n" + "\n".join(lines) + "\n", encoding="utf-8")
        return target
    except Exception as exc:  # noqa: BLE001 — 借不到登录态就按公开内容下,不该让整批失败
        logger.warning("取浏览器档案 %s 的 cookie 失败:%s", profile_id, str(exc)[:200])
        return None
    finally:
        if session is not None:
            with SessionLocal() as db:
                browser.close_session(db, session.id)
