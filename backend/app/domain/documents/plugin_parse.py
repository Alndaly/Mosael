"""认领了 `document_parse` 的插件工具(ADR 0031 §3,MinerU 是第一家)。

**契约**(ADR 0033 §3:它是一个普通工具,能力是加在它上面的一份契约):

- 入:`file` 是一份文档(`format: asset`,`x-media` 含 `document`),宿主交的是原件副本的本地路径;可选 `filename`
  (原文件名;没给就是副本的文件名,它和原件同名);
- 进度:NDJSON 的 `{"event": "progress", ...}` 行,取消看 `MOSAEL_PLUGIN_CANCEL_FILE`(和别的流式工具同一套);
- 出:`{"markdown": <暂存目录里一份 Markdown 的相对路径>}`。正文里用 `<!-- page: N -->`(或 slide / sheet /
  section)标出每一段从哪开始 —— 没标就按标题切;插图写在暂存目录的 `images/` 下,正文里用相对路径引用。
  正文里内嵌的 HTML 表格(MinerU 就是这样交表格的)由宿主转成 Markdown 表格。

两条路调它,产出落到同一个地方 —— 那份文档的一次解析:

- 宿主的解析任务(文档详情「重新解析」、导入后的解析、工作流「文档转 Markdown」):`parse_with_plugin`,
  解析那一行在任务开始时就建好了,进度写在任务上;
- 智能体、工作流里的这个插件节点、插件页「试一下」直接调工具:能力的收尾(extraction.finish_plugin_call)新建一行解析存进去。

页面图**不归插件管**:宿主照原件自己渲(local.attach_page_images),哪一家解析的都一样。
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.db.models import Asset, AssetExtraction, Job
from app.domain.documents import DOCUMENT_PARSE
from app.domain.documents.local import DocumentParseError, Parsed, Section, html_to_markdown, _split_by_headings

_MARKER = re.compile(r"<!--\s*(page|slide|sheet|section)\s*:\s*(\d+)\s*-->")
_TABLE = re.compile(r"<table\b.*?</table>", re.S | re.I)


def _inside(root: Path, relative: str) -> Path:
    """插件交回的路径必须落在暂存目录里 —— 不能借它读走别处的文件。"""
    from app.domain.plugins.tools import staged_output

    target = staged_output(root, relative)
    if target is None:
        raise DocumentParseError("docErr_pluginBadOutput", detail=relative[:200])
    return target


def sections_from_markdown(markdown: str) -> tuple[str, list[Section]]:
    """带段标记的 Markdown → (单位, 各段)。没有标记就按标题切,单位是 section。"""
    markdown = _TABLE.sub(lambda match: "\n\n" + html_to_markdown(match.group(0)) + "\n\n", markdown)
    marks = list(_MARKER.finditer(markdown))
    if not marks:
        return "section", _split_by_headings(markdown.strip())
    unit = marks[0].group(1)
    sections: list[Section] = []
    for position, mark in enumerate(marks):
        end = marks[position + 1].start() if position + 1 < len(marks) else len(markdown)
        body = markdown[mark.end():end].strip()
        first = next((line for line in body.splitlines() if line.strip()), "")
        sections.append(Section(index=int(mark.group(2)), title=first.lstrip("#").strip()[:80], markdown=body))
    return unit, sections


def _cancelled(job_id: str | None) -> bool:
    if not job_id:
        return False
    from app.domain.jobs import was_cancelled

    #: 取消的任务在库里是 failed + jobErr_cancelled,不是 cancelled(见 jobs.was_cancelled)—— 此前这里
    #: 比的是 cancelled,于是插件那边从来没收到过「停下」。
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        return job is not None and was_cancelled(job)


def parsed_from_output(output: dict[str, Any], scratch: Path, target: Path) -> Parsed:
    """插件交回的产出(暂存目录被删之前)→ 切好段的解析;插图搬进解析目录。两条路共用。"""
    relative = str(output.get("markdown") or "")
    if not relative:
        raise DocumentParseError("docErr_pluginBadOutput", detail="no markdown")
    markdown = _inside(scratch, relative).read_text(encoding="utf-8", errors="replace")
    images = scratch / "images"
    if images.is_dir():
        shutil.copytree(images, target / "images", dirs_exist_ok=True)
    unit, sections = sections_from_markdown(markdown)
    kept = sorted(f"images/{one.relative_to(images).as_posix()}" for one in images.rglob("*") if one.is_file()) \
        if images.is_dir() else []
    return Parsed(unit=unit, sections=sections, images=kept)


def parse_with_plugin(db: Session, extraction: AssetExtraction, asset: Asset, source: Path, target: Path, progress) -> Parsed:
    """解析任务里交给插件:原件经工具的 `file` 入参交(和素材 id 同一道暂存),产出在暂存目录删之前切好段。"""
    from app.domain.plugins.errors import PluginDomainError
    from app.domain.plugins.runtime import PluginRuntimeError, StreamHooks
    from app.domain.plugins.tools import invoke_host

    parsed: dict[str, Parsed] = {}

    def collect(output: dict[str, Any], scratch: Path) -> dict[str, Any]:
        parsed["result"] = parsed_from_output(output, scratch, target)
        return {"markdown": str(output.get("markdown")), "sections": len(parsed["result"].sections),
                "images": len(parsed["result"].images)}

    hooks = StreamHooks(
        on_progress=lambda fraction, message: progress(0.05 + 0.85 * fraction, message or "docProgress_readPages"),
        #: 解析不跨重启续等(重启时这一次判失败,见 extraction.reconcile_orphaned_extractions),回执不用记。
        on_task=lambda _receipt: None,
        is_cancelled=lambda: _cancelled(extraction.job_id),
    )
    try:
        invoke_host(db, extraction.parser, DOCUMENT_PARSE, {"filename": asset.original_filename or source.name},
                    files={"file": source}, collect=collect, hooks=hooks)
    except (PluginDomainError, PluginRuntimeError) as exc:
        raise DocumentParseError("docErr_pluginFailed", plugin=extraction.parser_name, detail=str(exc)[:500]) from exc
    if "result" not in parsed:
        raise DocumentParseError("docErr_pluginBadOutput", detail="nothing collected")
    return parsed["result"]
