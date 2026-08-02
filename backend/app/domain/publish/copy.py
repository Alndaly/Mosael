"""AI 发布文案(Phase 13 第 10 项):标题 / 简介 / 标签生成。

上下文 = 用户 brief + 素材名 + (若有)转写全文摘录;严格 JSON 输出,
解析失败带错误重试一次 —— 与工作流 AI 编辑同一套纪律。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Asset, Transcript
from app.domain.ai_chat import AiChatError, ChatTarget, chat, target_for
from app.domain.usage import BillableCall, billable
from app.domain.providers import require_profile
from app.domain.publish import PublishDomainError

TIMEOUT_SECONDS = 90
TRANSCRIPT_EXCERPT_CHARS = 1500

_SYSTEM = """你是短视频发布运营。根据素材信息写发布文案,只输出一个 JSON 对象,不要解释、不要代码围栏:
{"title": "吸引人的标题,<=30字", "description": "简介,2-4句,自然口语", "tags": ["3-8个话题标签,不带#"]}"""


def generate_copy(
    db: Session, *, workspace_id: str, asset_id: str | None = None, brief: str = "", profile_id: str | None = None
) -> dict[str, Any]:
    profile = require_profile(db, profile_id, error=PublishDomainError)
    parts: list[str] = []
    if brief.strip():
        parts.append(f"创作者要求:{brief.strip()}")
    if asset_id:
        asset = db.get(Asset, asset_id)
        if asset is None or asset.workspace_id != workspace_id:
            raise PublishDomainError("素材不存在")
        parts.append(f"素材名称:{asset.name}")
        transcript = db.scalars(
            select(Transcript).where(Transcript.asset_id == asset_id).order_by(Transcript.id.desc())
        ).first()
        if transcript is not None:
            text = "\n".join(segment.text for segment in transcript.segments)[:TRANSCRIPT_EXCERPT_CHARS]
            if text.strip():
                parts.append(f"视频口播内容(节选):\n{text}")
    if not parts:
        raise PublishDomainError("需要提供 brief 或素材")
    user = "\n\n".join(parts)
    try:
        target = target_for(db, profile)
    except AiChatError as exc:
        raise PublishDomainError(str(exc)) from exc

    with billable(
        db,
        capability="chat",
        operation="publish_copy",
        workspace_id=workspace_id,
        source_type="asset",
        source_id=asset_id or "",
    ) as call:
        last_error = ""
        for _attempt in range(2):
            prompt = user if not last_error else f"{user}\n\n上次输出无法解析:{last_error}\n请重新只输出 JSON。"
            raw = _chat(target, prompt, call)
            try:
                payload = _parse_json(raw)
                return {
                    "title": str(payload.get("title", ""))[:120],
                    "description": str(payload.get("description", ""))[:2000],
                    "tags": [str(tag)[:40] for tag in payload.get("tags", []) if str(tag).strip()][:12],
                }
            except ValueError as exc:
                last_error = str(exc)
        raise PublishDomainError(f"AI 未能产出合法文案: {last_error}")


def _parse_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("输出中没有 JSON 对象")
    return json.loads(text[start : end + 1])


def _chat(target: ChatTarget, user: str, call: BillableCall) -> str:
    try:
        return chat(
            target,
            [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
            temperature=0.7,
            timeout=TIMEOUT_SECONDS,
            call=call,
            label="AI 文案生成",
        )
    except AiChatError as exc:
        raise PublishDomainError(str(exc)) from exc

