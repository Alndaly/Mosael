"""把一份文档的解析结果存成笔记(ADR 0031 §2:「存成笔记」是一个明确的动作,不自动建)。

- 正文是解析出的 Markdown:页 / 幻灯片之间隔一道分割线,段首的 `<!-- page: N -->` 标记去掉(笔记里用不上);
- 文档里的插图**这时才进素材库**(解析时留在解析结果里,免得一份 PPT 几十个图标把库塞满),正文里换成笔记认的
  `mosael-asset:<id>`;
- 笔记的来源记着原文档,从笔记能点回去。
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.db.models import Asset, Note
from app.domain.documents.extraction import DocumentParseError, extraction_dir, latest_extraction
from app.domain.note_types import NoteContent, NoteSource

#: 笔记正文的上限(NoteContent.markdown)。超了截断并说一句 —— 几百页的 PDF 存成一篇笔记本来就读不完。
NOTE_LIMIT = 480_000
_IMAGE = re.compile(r"!\[([^\]]*)\]\(((?:images|pages)/[^)\s]+)\)")


def save_as_note(db: Session, asset: Asset, *, actor_id: str) -> Note:
    from app.domain.assets.importer import register_file_asset
    from app.domain.notes import create_note

    from app.domain.documents.reading import document_text

    extraction = latest_extraction(db, asset.id)
    body = document_text(db, asset.workspace_id, asset.id)
    if extraction is None or body is None:
        raise DocumentParseError("docErr_notParsedYet", name=asset.name)

    root = extraction_dir(extraction)
    kept: dict[str, str] = {}

    def to_asset(match: re.Match) -> str:
        alt, path = match.group(1), match.group(2)
        if path not in kept:
            source = (root / path).resolve()
            if not source.is_relative_to(root.resolve()) or not source.is_file():
                return ""
            made = register_file_asset(db, workspace_id=asset.workspace_id, project_id=asset.project_id, source_path=source,
                                       name=f"{asset.name} · {alt or source.stem}", source="derived")
            kept[path] = made.id
        return f"![{alt}](mosael-asset:{kept[path]})"

    body = _IMAGE.sub(to_asset, body)
    if len(body) > NOTE_LIMIT:
        body = body[:NOTE_LIMIT] + "\n\n…"
    title = asset.name.rsplit(".", 1)[0][:240]
    return create_note(db, asset.workspace_id, NoteContent(
        title=title,
        markdown=body,
        project_id=asset.project_id,
        sources=[NoteSource(kind="asset", id=asset.id, label=asset.name)],
    ), actor=actor_id)
