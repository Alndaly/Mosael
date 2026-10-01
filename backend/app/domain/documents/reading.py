"""智能体读文档(ADR 0031 §4):和 Claude / OpenAI 同一个思路 —— **文字按需读,要看版式时看页面图**。

- 对话里挂了一份文档:短的整篇放进上下文;长的只放目录,正文由模型按段去取(`read`);
- `read`:第 first–last 段的正文,有字数上限,超了说还剩到第几段;
- `analyze_pages`:那几页的页面图 + 那几页的文字交给视觉模型,回答关于版式、图表、截图的问题。

还没解析完的文档,`read` 等它一小会儿(导入时自动起的本地解析一般几秒);再没好就如实说还在解析。
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.db.models import Asset, AssetExtraction
from app.domain.documents.extraction import ensure_parsed, extraction_dir, latest_extraction, read_sections

#: 整篇直接放进对话上下文的上限(字)。再长只放目录,正文按段取。
INLINE_CHARS = 12_000
#: 一次 read 最多给多少字。
READ_BUDGET_CHARS = 40_000
#: 一次最多看几页的页面图。
MAX_PAGES_PER_LOOK = 6
#: 导入后自动解析的那一下,read 最多等多久。
WAIT_SECONDS = 30.0


class DocumentReadError(LocalizedError, ValueError):
    status = 409


def _document(db: Session, workspace_id: str, asset_id: str) -> Asset:
    asset = db.get(Asset, asset_id)
    if asset is None or asset.workspace_id != workspace_id:
        raise DocumentReadError("docErr_assetNotFound", asset_id=asset_id)
    if asset.kind != "document":
        raise DocumentReadError("docErr_notDocument", name=asset.name)
    return asset


def _ready(db: Session, asset: Asset, *, wait: bool) -> AssetExtraction:
    """最新成功的那份解析;还在解析就等一会儿(wait),失败 / 没有就说清楚。"""
    from app.core.unit_of_work import unit_of_work

    deadline = time.monotonic() + (WAIT_SECONDS if wait else 0)
    #: 补一次解析是**它自己的一个用例**,自己提交:解析任务在提交之后才开跑(jobs.dispatch_job),而下面要在这里
    #: 等它 —— 跟着读的这一笔一起提交的话,等到时限也等不到,读的人一报错回滚,连这次解析也没了。读的这一侧
    #: 此前没写过东西,另开一个会话不会撞上写锁。
    if latest_extraction(db, asset.id, succeeded=False) is None:
        with unit_of_work() as own:
            ensure_parsed(own, own.get(Asset, asset.id))
    while True:
        done = latest_extraction(db, asset.id)
        if done is not None:
            return done
        latest = latest_extraction(db, asset.id, succeeded=False)
        running = latest is not None and latest.status in ("queued", "running")
        if not running or time.monotonic() >= deadline:
            if running:
                raise DocumentReadError("docErr_stillParsing", name=asset.name)
            if latest is not None and latest.status == "cancelled":
                raise DocumentReadError("docErr_parseStoppedForRead", name=asset.name)
            if latest is not None:
                raise DocumentReadError("docErr_parseFailedForRead", name=asset.name, error=latest.error[:300])
            raise DocumentReadError("docErr_notParsedYet", name=asset.name)
        time.sleep(0.5)
        db.expire_all()


def outline(extraction: AssetExtraction) -> list[dict[str, Any]]:
    return [{"index": one["index"], "title": one.get("title") or "", "chars": one.get("chars", 0),
             "has_page_image": bool(one.get("image"))} for one in extraction.outline or []]


#: 一段剩下的预算不到这么多字,就不在这一段里切一截了:下一次从这一段开头读。
MIN_PIECE_CHARS = 2_000


def _cut(body: str, room: int) -> int:
    """在 room 之内最后一个换行处切(一张表按整行切,不切半行);一行都放不下就硬切。"""
    cut = body.rfind("\n", 0, room)
    return cut + 1 if cut > 0 else room


def _table_header(text: str) -> str:
    """一段开头那张 Markdown 表的表头(表头行 + 分隔行)。续读切在表的中间时补回去,不然后半截只剩一堆没名字的列。"""
    lines = text.splitlines()
    for at in range(len(lines) - 1):
        if lines[at].lstrip().startswith("|") and set(lines[at + 1].replace("|", "").strip()) <= set("-: ") and "-" in lines[at + 1]:
            return f"{lines[at]}\n{lines[at + 1]}\n"
    return ""


def read(db: Session, workspace_id: str, asset_id: str, first: int = 1, last: int | None = None,
         offset: int = 0) -> dict[str, Any]:
    """第 first–last 段,从第 first 段的第 offset 个字起。预算用完时 `next` 说从哪接着读 —— 可能是**一段的中间**:
    一张几百行的表是一整段,此前一段超过预算就只给前 4 万字、再没有办法读到后半(用户截图:智能体说
    「卡在单次读取的上限上」)。切在表中间时,续读的那一截前面补上表头。"""
    asset = _document(db, workspace_id, asset_id)
    extraction = _ready(db, asset, wait=True)
    first = max(1, first)
    last = min(last or extraction.sections, extraction.sections)
    sections: list[dict[str, Any]] = []
    used = 0
    next_ref: dict[str, int] | None = None
    for section in read_sections(extraction, first, last):
        text = section["markdown"]
        start = min(max(0, offset), len(text)) if section["index"] == first else 0
        body = text[start:]
        header = _table_header(text) if start and body.lstrip().startswith("|") else ""
        room = READ_BUDGET_CHARS - used
        if len(body) > room:
            if sections and room < MIN_PIECE_CHARS:
                next_ref = {"first": section["index"], "offset": start}
                break
            cut = _cut(body, room)
            sections.append({"index": section["index"], "title": section.get("title") or "", "offset": start,
                             "markdown": header + body[:cut], "complete": False})
            next_ref = {"first": section["index"], "offset": start + cut}
            break
        sections.append({"index": section["index"], "title": section.get("title") or "", "offset": start,
                         "markdown": header + body, "complete": True})
        used += len(body)
    return {
        "asset_id": asset.id,
        "name": asset.name,
        "parser": extraction.parser_name,
        "unit": extraction.unit,
        "total": extraction.sections,
        "page_images": len(extraction.page_images or []),
        "notes": list(extraction.notes or []),
        "outline": outline(extraction),
        "sections": sections,
        #: 预算用完了:下一次传 first / offset 接着读(offset 是那一段里的第几个字,0 = 从头);None = 读到了要的最后一段。
        "next": next_ref,
    }


def document_text(db: Session, workspace_id: str, asset_id: str) -> str | None:
    """一份文档素材解析出的全文(不带段标记);不是这个工作区的、还没解析好的回 None。给画板上的文档格、工作流用。"""
    asset = db.get(Asset, asset_id)
    if asset is None or asset.workspace_id != workspace_id or asset.kind != "document":
        return None
    done = latest_extraction(db, asset.id)
    if done is None:
        #: 从没解析过(升级改回来的那批):补上本地解析,这一次照样说「还读不到」,下一次就有了。
        ensure_parsed(db, asset)
        return None
    separator = "\n\n---\n\n" if done.unit in ("page", "slide") else "\n\n"
    return separator.join(one["markdown"].strip() for one in read_sections(done, 1, done.sections) if one["markdown"].strip())


def attachment_context(db: Session, workspace_id: str, asset_ids: list[str]) -> str:
    """对话里挂的文档 → 给模型看的那段上下文。短的整篇放进来,长的放目录,正文让它自己取。"""
    blocks: list[str] = []
    for asset_id in asset_ids:
        asset = db.get(Asset, asset_id)
        if asset is None or asset.workspace_id != workspace_id or asset.kind != "document":
            continue
        done = latest_extraction(db, asset.id)
        header = f"【文档 {asset.name}(asset_id={asset.id})】"
        if done is None:
            ensure_parsed(db, asset)
            latest = latest_extraction(db, asset.id, succeeded=False)
            state = ("还在解析" if latest is None or latest.status in ("queued", "running")
                     else "解析被停下了,还没有可读的正文" if latest.status == "cancelled" else f"解析失败:{latest.error[:200]}")
            blocks.append(f"{header}{state}。用 read_document(asset_id) 读它(会等解析完)。")
            continue
        unit = {"page": "页", "slide": "张幻灯片", "sheet": "张表", "section": "章"}.get(done.unit, "段")
        if done.chars <= INLINE_CHARS:
            full = "\n\n".join(f"<!-- {done.unit}: {one['index']} -->\n{one['markdown']}"
                               for one in read_sections(done, 1, done.sections))
            blocks.append(f"{header}全文({done.sections} {unit},{done.parser_name}解析):\n{full}")
        else:
            titles = "\n".join(f"{one['index']}. {one.get('title') or '(无标题)'}" for one in (done.outline or [])[:200])
            blocks.append(f"{header}共 {done.sections} {unit}、{done.chars} 字,太长不整篇放进来。目录:\n{titles}\n"
                          f"用 read_document(asset_id, first, last) 按段读正文;回包的 next 不为空就照它的 first / offset 接着读。")
        if done.page_images:
            blocks.append(f"(这份文档有 {len(done.page_images)} 页页面图:要看版式、图表、截图就用 "
                          f"analyze_document_pages(asset_id, pages, question)。)")
    return "\n\n".join(blocks)


def analyze_pages(db: Session, workspace_id: str, asset_id: str, pages: list[int], question: str, *,
                  user_id: str | None, profile_id: str | None = None) -> dict[str, Any]:
    """那几页的页面图 + 那几页的文字 → 视觉模型。页码按「原版」那一栏数(第几张页面图)。"""
    from app.domain.analysis.service import call_vision_model, image_part, select_analysis_connection
    from app.domain.billing.usage import billable, once

    asset = _document(db, workspace_id, asset_id)
    extraction = _ready(db, asset, wait=True)
    images = list(extraction.page_images or [])
    if not images:
        raise DocumentReadError("docErr_noPageImagesToLook", name=asset.name)
    wanted = [page for page in dict.fromkeys(int(one) for one in pages) if 1 <= page <= len(images)][:MAX_PAGES_PER_LOOK]
    if not wanted:
        raise DocumentReadError("docErr_pageOutOfRange", total=len(images))
    root = extraction_dir(extraction)
    text_by_page = {one["index"]: one["markdown"] for one in read_sections(extraction, min(wanted), max(wanted))} \
        if extraction.unit in ("page", "slide") else {}
    context = f"文档:{asset.name}。下面是第 {'、'.join(map(str, wanted))} 页的页面图"
    if text_by_page:
        context += ",以及这几页抽出来的文字(可能漏掉图里的字):\n" + "\n\n".join(
            f"[第 {page} 页]\n{text_by_page.get(page, '')[:4000]}" for page in wanted)
    content: list[dict[str, Any]] = [{"type": "text", "text": f"{context}\n\n{question.strip() or '说说这几页的内容和版式。'}"}]
    content.extend(image_part((root / images[page - 1]).read_bytes(), "image/png") for page in wanted)
    profile = select_analysis_connection(db, profile_id, user_id)
    with billable(db, capability="chat", operation="analyze_document_pages", workspace_id=asset.workspace_id,
                  idempotency_key=once("analyze_document_pages"), source_type="asset", source_id=asset.id) as call:
        answer = call_vision_model(db, profile, [{"role": "user", "content": content}], call)
    return {"asset_id": asset.id, "pages": wanted, "answer": answer}
