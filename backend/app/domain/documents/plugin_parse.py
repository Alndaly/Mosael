"""交给声明了 `document_parse` 的插件解析(ADR 0031 §3,MinerU 是第一家)。

**协议**(只给宿主调的能力,走 plugins.tools.invoke_host 的流式那条):

- 入:`{"file": <原件副本的本地路径>, "filename": <原文件名>}`。宿主在进程起来之前把副本放进这次的暂存目录
  (`MOSAEL_PLUGIN_OUTPUT_DIR`,插件也往这里写产出);
- 进度:NDJSON 的 `{"event": "progress", ...}` 行,取消看 `MOSAEL_PLUGIN_CANCEL_FILE`(和别的流式工具同一套);
- 出:`{"markdown": <暂存目录里一份 Markdown 的相对路径>}`。正文里用 `<!-- page: N -->`(或 slide / sheet /
  section)标出每一段从哪开始 —— 没标就按标题切;插图写在暂存目录的 `images/` 下,正文里用相对路径引用。
  正文里内嵌的 HTML 表格(MinerU 就是这样交表格的)由宿主转成 Markdown 表格。

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
from app.domain.documents.local import DocumentParseError, Parsed, Section, _html_to_markdown, _split_by_headings

_MARKER = re.compile(r"<!--\s*(page|slide|sheet|section)\s*:\s*(\d+)\s*-->")
_TABLE = re.compile(r"<table\b.*?</table>", re.S | re.I)


def _inside(root: Path, relative: str) -> Path:
    """插件交回的路径必须落在暂存目录里 —— 不能借它读走别处的文件。"""
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()) or not target.is_file():
        raise DocumentParseError("docErr_pluginBadOutput", detail=relative[:200])
    return target


def sections_from_markdown(markdown: str) -> tuple[str, list[Section]]:
    """带段标记的 Markdown → (单位, 各段)。没有标记就按标题切,单位是 section。"""
    markdown = _TABLE.sub(lambda match: "\n\n" + _html_to_markdown(match.group(0)) + "\n\n", markdown)
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


def parse_with_plugin(db: Session, extraction: AssetExtraction, asset: Asset, source: Path, target: Path, progress) -> Parsed:
    from app.domain.plugins.errors import PluginDomainError
    from app.domain.plugins.runtime import PluginRuntimeError, StreamHooks
    from app.domain.plugins.tools import invoke_host

    filename = asset.original_filename or source.name
    parsed: dict[str, Parsed] = {}

    def prepare(scratch: Path) -> dict[str, Any]:
        #: 给副本不给原件(和 `format: "asset"` 同一个规矩):插件改坏了、删掉了都伤不到素材库里那一份。
        inbox = scratch / "_input"
        inbox.mkdir(parents=True, exist_ok=True)
        copy = inbox / f"source{source.suffix.lower()}"
        shutil.copyfile(source, copy)
        return {"file": str(copy), "filename": filename}

    def collect(output: dict[str, Any], scratch: Path) -> dict[str, Any]:
        """暂存目录被删之前:正文读出来切段,插图搬进解析目录。"""
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
        parsed["result"] = Parsed(unit=unit, sections=sections, images=kept)
        return {"markdown": relative, "sections": len(sections), "images": len(kept)}

    hooks = StreamHooks(
        on_progress=lambda fraction, message: progress(0.05 + 0.85 * fraction, message or "docProgress_readPages"),
        #: 解析不跨重启续等(重启时这一次判失败,见 extraction.reconcile_orphaned_extractions),回执不用记。
        on_task=lambda _receipt: None,
        is_cancelled=lambda: _cancelled(extraction.job_id),
    )
    try:
        invoke_host(db, extraction.parser, DOCUMENT_PARSE, {}, prepare=prepare, collect=collect, hooks=hooks)
    except (PluginDomainError, PluginRuntimeError) as exc:
        raise DocumentParseError("docErr_pluginFailed", plugin=extraction.parser_name, detail=str(exc)[:500]) from exc
    if "result" not in parsed:
        raise DocumentParseError("docErr_pluginBadOutput", detail="nothing collected")
    return parsed["result"]
