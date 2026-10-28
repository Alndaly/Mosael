"""Computer Use 回放证据(ADR 0081 P3)。

动作前后两张截图只落本机数据目录,消息里存元数据和受保护 URL;删会话即删目录,
「清空回放」删文件并把消息/确认卡里的 replay 元数据去掉。
"""

from __future__ import annotations

import base64
import re
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.db.models import AgentMessage, ToolConfirmation

REPLAY_ROOT = "agent-replay"
MAX_IMAGE_BYTES = 8 * 1024 * 1024
_SAFE = re.compile(r"^[A-Za-z0-9_-]{1,96}$")


def _safe(part: str, what: str) -> str:
    value = str(part or "")
    if not _SAFE.fullmatch(value):
        raise ValueError(f"invalid replay {what}")
    return value


def session_dir(session_id: str) -> Path:
    return Path(settings.data_dir) / REPLAY_ROOT / _safe(session_id, "session")


def image_path(session_id: str, replay_id: str, which: str) -> Path:
    if which not in ("before", "after"):
        raise ValueError("invalid replay image")
    path = session_dir(session_id) / _safe(replay_id, "id") / f"{which}.png"
    return path


def _write_png(path: Path, data: str) -> str | None:
    """写一张 PNG;成功回 None,失败回一句原因。"""
    try:
        raw = base64.b64decode(data, validate=True)
    except (ValueError, TypeError):
        return "invalid image data"
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        return "image is empty or too large"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".png.tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)
    return None


def store_action_replay(
    *, session_id: str, replay_id: str, replay: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    """把驱动交回的两张图落盘,返回可进消息 payload 的 replay 元数据。"""
    saved: dict[str, Any] = {
        "version": 1,
        "session_id": _safe(session_id, "session"),
        "replay_id": _safe(replay_id, "id"),
        "at": str(replay.get("at") or ""),
        "action": replay.get("action") if isinstance(replay.get("action"), dict) else {},
        "target": {
            "window_id": result.get("windowNumber"),
            "pid": result.get("pid"),
            "point": result.get("point"),
        },
    }
    for which in ("before", "after"):
        image = replay.get(which)
        if not isinstance(image, dict) or not image.get("image"):
            saved[which] = {"error": str((image or {}).get("error") or "not captured")}
            continue
        path = image_path(session_id, replay_id, which)
        error = _write_png(path, str(image["image"]))
        if error:
            saved[which] = {"error": error}
        else:
            saved[which] = {
                "url": f"/api/agent/sessions/{_safe(session_id, 'session')}/replay/{_safe(replay_id, 'id')}/{which}.png",
                "width": image.get("width"),
                "height": image.get("height"),
            }
    clean = {key: value for key, value in result.items() if key != "replay"}
    clean["replay"] = saved
    return clean


def clear_session_files(session_id: str) -> None:
    shutil.rmtree(session_dir(session_id), ignore_errors=True)


def clear_replay(db: Session, session_id: str) -> None:
    """清空这个会话的回放:文件删掉,消息与确认卡里的元数据也去掉。调用方提交事务。"""

    clear_session_files(session_id)
    for message in db.query(AgentMessage).filter(AgentMessage.session_id == session_id).all():
        payload = message.payload if isinstance(message.payload, dict) else None
        timeline = payload.get("timeline") if isinstance(payload, dict) else None
        if not isinstance(timeline, list):
            continue
        changed = False
        for item in timeline:
            tool = item.get("tool") if isinstance(item, dict) else None
            result = tool.get("result") if isinstance(tool, dict) else None
            if isinstance(result, dict) and "replay" in result:
                tool["result"] = {key: value for key, value in result.items() if key != "replay"}
                changed = True
        if changed:
            message.payload = {**payload, "timeline": timeline}
            flag_modified(message, "payload")
    for card in db.query(ToolConfirmation).filter(ToolConfirmation.session_id == session_id).all():
        if isinstance(card.result, dict) and "replay" in card.result:
            card.result = {key: value for key, value in card.result.items() if key != "replay"}
            flag_modified(card, "result")
