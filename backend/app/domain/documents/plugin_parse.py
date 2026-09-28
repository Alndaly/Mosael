"""交给声明了 `document_parse` 的插件解析(ADR 0031 第五步:协议随 MinerU 插件一起定)。"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import Asset, AssetExtraction
from app.domain.documents.local import DocumentParseError, Parsed


def parse_with_plugin(db: Session, extraction: AssetExtraction, asset: Asset, source: Path, target: Path, progress) -> Parsed:
    raise DocumentParseError("docErr_parserOutdated", plugin=extraction.parser_name)
