"""文档的解析结果:起一次解析(任务)、落盘、按段读(ADR 0031 §2)。

一次解析 = 一行 `AssetExtraction` + 素材目录下 `extracted/<id>/`:

- `full.md` —— 全文,每段前一个 `<!-- 单位: N -->` 标记;
- `pages/NNN.png` —— 页面图(PDF 总有;Office 文档本机装了 LibreOffice 才有);
- `images/…` —— 文档里的插图。**不进素材库**:一份 PPT 几十个图标进库只会把库塞满;存成笔记时才进。

行上的 `outline` 记每一段的标题、页面图和它在全文里的起止 —— 读的人按段取,不必每次解析一遍全文。
同一份文档可以解析几次(本地一份、MinerU 一份),读的时候用**最新成功的那份**。
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.unit_of_work import unit_of_work
from app.db.models import Asset, AssetExtraction, Job, now
from app.domain import capabilities
from app.domain.documents import CAPABILITY, DocumentParserUnavailable
from app.domain.documents.local import DocumentParseError, Parsed, attach_page_images, parse_local
from app.domain.jobs import create_job, dispatch_job, emit_job_event, finish_job, run_job_guarded, say, was_cancelled
from app.media.paths import asset_dir, resolve_key
from app.media.thumbnails import thumbnail_path, write_thumbnail

logger = logging.getLogger(__name__)

__all__ = [
    "DocumentParseError",
    "DocumentParserUnavailable",
    "extraction_dir",
    "latest_extraction",
    "read_markdown",
    "read_sections",
    "reconcile_orphaned_extractions",
    "start_parse",
]


def extraction_dir(extraction: AssetExtraction) -> Path:
    return asset_dir(extraction.workspace_id, extraction.asset_id) / "extracted" / extraction.id


def latest_extraction(db: Session, asset_id: str, *, succeeded: bool = True, parser: str | None = None) -> AssetExtraction | None:
    """这份文档最新的一次解析(默认只看成功的;`parser` 只看这一家解析的)。"""
    query = select(AssetExtraction).where(AssetExtraction.asset_id == asset_id)
    if succeeded:
        query = query.where(AssetExtraction.status == "succeeded")
    if parser:
        query = query.where(AssetExtraction.parser == parser)
    return db.scalars(query.order_by(AssetExtraction.created_at.desc())).first()


def start_parse(
    db: Session, asset: Asset, *, owner_user_id: str | None, provider_id: str | None = None, created_by: str | None = None,
) -> AssetExtraction:
    """起一次解析。`provider_id` 点名用哪一家(界面上「用 ×× 重新解析」),不点名按这个人的默认挑
    (没定就是本地解析)。挑不出来(点名的插件没配好、太旧)在起任务之前就说。"""
    if asset.kind != "document":
        raise DocumentParseError("docErr_notDocument", name=asset.name)
    provider = capabilities.pick(db, owner_user_id, CAPABILITY, provider_id, asset=asset.name)
    extraction = AssetExtraction(asset_id=asset.id, workspace_id=asset.workspace_id, parser=provider.id,
                                 parser_name=provider.name, status="queued")
    db.add(extraction)
    db.flush()
    job = create_job(
        db,
        workspace_id=asset.workspace_id,
        kind="document_parse",
        created_by=created_by,
        payload={"asset_id": asset.id, "extraction_id": extraction.id, "subject": asset.name, "parser": provider.name},
        message="jobMsg_documentParseQueued",
    )
    extraction.job_id = job.id
    extraction_id, job_id, builtin = extraction.id, job.id, provider.builtin
    dispatch_job(db, job, lambda: run_job_guarded(job_id, lambda: _body(job_id, extraction_id, builtin), what="文档解析"))
    return extraction


def ensure_parsed(db: Session, asset: Asset) -> AssetExtraction | None:
    """一次解析都没有过的文档,补上导入时本该做的那次**本地解析**,交回它;解析过(不管成没成)就什么都不做。

    正常导入的文档一进来就解析(assets.importer);没有的是升级迁移改回来的那一批 —— 此前被当成视频入库、
    从没解析过(migrations 的 documents-are-not-videos)。它们在有人读的那一刻(阅读器、智能体、画板)补上。
    和导入时同一条:只用本地解析,不看他的默认 —— 交给云端必须是人点名的。
    """
    from app.domain.documents import LOCAL_PARSER

    if asset.kind != "document" or latest_extraction(db, asset.id, succeeded=False) is not None:
        return None
    return start_parse(db, asset, owner_user_id=None, provider_id=LOCAL_PARSER)


class ParseStopped(Exception):
    """解析任务被人停下了。不是失败,也不带原因。"""


def _job_cancelled(db: Session, job_id: str) -> bool:
    """插件那条路停下时抛的是插件自己的错(它看到了取消文件),按任务状态认。"""
    db.expire_all()
    job = db.get(Job, job_id)
    return job is not None and was_cancelled(job)


def _body(job_id: str, extraction_id: str, builtin: bool) -> None:
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        extraction = db.get(AssetExtraction, extraction_id)
        asset = db.get(Asset, extraction.asset_id) if extraction else None
        if job is None or extraction is None or asset is None:
            return
        if not finish_job(db, job, status="running", progress=0.02):
            return
        extraction.status = "running"
        say(job, "jobMsg_documentParseRunning", params={"parser": extraction.parser_name})
        emit_job_event(db, job.id, "job.running", {})
        # 「在解析」先落库:几百页要解一阵,阅读器要马上看得到;也把 finish_job 拿的写锁放掉。
        db.commit()

        target = extraction_dir(extraction)
        shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True, exist_ok=True)

        def progress(fraction: float, message: str) -> None:
            """报进度;任务已经被停下(任务中心、阅读器上的「停止」)就在这一页之后收手 —— 此前照样读完几百页。"""
            with unit_of_work() as progress_db:
                current = progress_db.get(Job, job_id)
                if current is not None and finish_job(progress_db, current, status="running", progress=round(max(0.02, min(fraction, 0.98)), 3)):
                    say(current, message)
                elif current is not None and was_cancelled(current):
                    raise ParseStopped()

        try:
            source = resolve_key(asset.file_key)
            if not source.is_file():
                raise DocumentParseError("docErr_fileMissing", name=asset.name)
            if builtin:
                parsed = parse_local(source, target, on_progress=progress)
            else:
                parsed = _parse_with_plugin(db, extraction, asset, source, target, progress)
                #: 页面图由宿主照原件渲,哪一家解析的都一样。
                attach_page_images(source, target, parsed, progress)
            _write(db, extraction, asset, parsed, target)
        except Exception as exc:
            db.rollback()
            stopped = isinstance(exc, ParseStopped) or _job_cancelled(db, job_id)
            failed = db.get(AssetExtraction, extraction_id)
            if failed is not None:
                failed.status, failed.finished_at = ("cancelled" if stopped else "failed"), now()
                failed.error = "" if stopped else str(exc)[:2000]
                # 下面还要原样抛出去(交给 run_job_guarded 记到任务上),抛出去这个事务就回滚了 ——
                # 这一行的「失败 / 已停下」得先落库。
                db.commit()
            #: 停下的不是失败:任务那一侧已经是「已取消」(cancel_job 写的),这里不再抛出一条失败盖上去。
            if stopped:
                shutil.rmtree(target, ignore_errors=True)
                return
            raise
        result = {"asset_id": asset.id, "extraction_id": extraction.id, "sections": extraction.sections}
        if finish_job(db, job, status="succeeded", progress=1.0, result=result):
            say(job, "jobMsg_documentParseDone")
            emit_job_event(db, job.id, "job.succeeded", dict(result))


def _parse_with_plugin(db: Session, extraction: AssetExtraction, asset: Asset, source: Path, target: Path, progress) -> Parsed:
    """交给声明了 `document_parse` 的插件(MinerU……),协议见 documents/plugin_parse。"""
    from app.domain.documents.plugin_parse import parse_with_plugin

    return parse_with_plugin(db, extraction, asset, source, target, progress)


def _write(db: Session, extraction: AssetExtraction, asset: Asset, parsed: Parsed, target: Path) -> None:
    """全文写成 full.md,每段的标题、页面图、在全文里的起止记进行上;第一页的页面图当素材封面。"""
    outline: list[dict[str, Any]] = []
    chunks: list[str] = []
    cursor = 0
    for section in parsed.sections:
        header = f"<!-- {parsed.unit}: {section.index} -->\n"
        body = section.markdown.strip()
        start = cursor + len(header)
        chunks.append(header + body)
        outline.append({"index": section.index, "title": section.title, "image": section.image,
                        "start": start, "end": start + len(body), "chars": len(body)})
        cursor = start + len(body) + 2
    full = "\n\n".join(chunks) + "\n"
    (target / "full.md").write_text(full, encoding="utf-8")
    extraction.page_images = [one.image for one in parsed.sections if one.image] or list(parsed.page_images)

    extraction.status = "succeeded"
    extraction.unit = parsed.unit
    extraction.sections = len(parsed.sections)
    extraction.chars = sum(one["chars"] for one in outline)
    extraction.outline = outline
    extraction.notes = list(parsed.notes)
    extraction.finished_at = now()

    info = {**(asset.media_info or {}), "pages": len(parsed.sections), "unit": parsed.unit, "chars": extraction.chars}
    cover = extraction.page_images[0] if extraction.page_images else None
    if cover:
        try:
            from PIL import Image

            with Image.open(target / cover) as image:
                write_thumbnail(image, thumbnail_path(asset_dir(asset.workspace_id, asset.id)))
            info["has_thumbnail"] = True
        except Exception:  # noqa: BLE001 —— 封面是锦上添花,解析本身成了
            logger.warning("文档 %s 的封面没写成", asset.id, exc_info=True)
    asset.media_info = info


def reconcile_orphaned_extractions(db: Session) -> int:
    """重启之前还在排队、在解析的:进程没了,不会再有人把它做完 —— 判失败并说清是重启打断的,用户点「重新解析」就行。"""
    from app.core.i18n import tr

    rows = list(db.scalars(select(AssetExtraction).where(AssetExtraction.status.in_(("queued", "running")))))
    for row in rows:
        row.status, row.error, row.finished_at = "failed", tr("docErr_interruptedByRestart"), now()
    return len(rows)


def read_markdown(extraction: AssetExtraction) -> str:
    path = extraction_dir(extraction) / "full.md"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def read_sections(extraction: AssetExtraction, first: int, last: int) -> list[dict[str, Any]]:
    """第 first–last 段(1 起,含两头)的正文、标题和页面图。"""
    full = read_markdown(extraction)
    picked = []
    for entry in extraction.outline or []:
        if first <= int(entry["index"]) <= last:
            picked.append({**entry, "markdown": full[int(entry["start"]):int(entry["end"])]})
    return picked
