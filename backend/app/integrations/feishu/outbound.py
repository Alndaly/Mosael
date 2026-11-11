"""飞书出站正文里的 Mosael 素材图片。

客户端只懂上传与发图;这里负责把 `![说明](mosael-asset:<id>)` 解析成本工作区的真实图片,
并保持「前文 → 图片 → 后文」的顺序。无效或跨工作区引用仍按原文发送,不替它读别的数据目录。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import Asset, FeishuBot
from app.media.paths import resolve_key
from app.integrations.feishu import client

logger = logging.getLogger(__name__)

ASSET_IMAGE = re.compile(r"!\[([^\]\n]*)\]\(mosael-asset:([A-Za-z0-9_-]+)\s*\)")


def _image_path(db: Session, workspace_id: str, asset_id: str) -> Path | None:
    asset = db.get(Asset, asset_id)
    if asset is None or asset.workspace_id != workspace_id or asset.kind != "image" or not asset.file_key:
        return None
    path = resolve_key(asset.file_key)
    return path if path.is_file() else None


def send_with_assets(
    db: Session,
    bot: FeishuBot,
    chat_id: str,
    text: str,
    *,
    workspace_id: str,
) -> None:
    """发送 Markdown 正文;其中可读取的素材引用变成真正的飞书图片消息。"""
    cursor = 0
    for match in ASSET_IMAGE.finditer(text):
        path = _image_path(db, workspace_id, match.group(2))
        if path is None:
            continue
        before = text[cursor:match.start()]
        if before.strip():
            client.send_markdown(bot, chat_id, before)
        try:
            client.send_image(bot, chat_id, path)
        except (client.FeishuError, OSError) as exc:
            logger.warning("feishu asset image failed asset=%s: %s", match.group(2), exc)
            client.send_text(bot, chat_id, f"图片:{match.group(1) or path.name}")
        cursor = match.end()
    if cursor == 0:
        client.send_markdown(bot, chat_id, text)
    elif text[cursor:].strip():
        client.send_markdown(bot, chat_id, text[cursor:])
