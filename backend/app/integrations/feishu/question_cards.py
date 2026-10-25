"""飞书里的选择卡:把 AgentQuestion 的单选 / 多选 / 自由文本接到卡片表单。

和确认卡共用同一条授权链:open_id → 这台机器人眼里的绑定成员 → 该工作区仍有权限;
答案仍走 `agent.use_cases.answer`,不另造一份问题状态。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.db.models import AgentQuestion
from app.domain.agent import use_cases
from app.domain.feishu import bindings, routing
from app.integrations.feishu import client

logger = logging.getLogger(__name__)

ACTION_ANSWER = "question.answer"
ACTION_SKIP = "question.skip"
ACTIONS = frozenset({ACTION_ANSWER, ACTION_SKIP})
FIELD_PREFIX = "question_"
OTHER_PREFIX = "question_other_"
FORM_NAME = "mosael_questions"
SUBMIT_NAME = "mosael_questions_submit"
MAX_OTHER_CHARS = 1000


def _text(content: str) -> dict[str, Any]:
    return {"tag": "div", "text": {"tag": "lark_md", "content": content}}


def _field_name(index: int) -> str:
    return f"{FIELD_PREFIX}{index}"


def _other_name(index: int) -> str:
    return f"{OTHER_PREFIX}{index}"


def _options(question: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "text": {"tag": "plain_text", "content": str(option.get("label") or "")},
            "value": str(option.get("label") or ""),
        }
        for option in question.get("options") or []
        if str(option.get("label") or "").strip()
    ]


def _question_block(index: int, question: dict[str, Any]) -> dict[str, Any]:
    multi = bool(question.get("multi_select"))
    selector: dict[str, Any] = {
        "tag": "multi_select_static" if multi else "select_static",
        "name": _field_name(index),
        "type": "default",
        "width": "fill",
        "placeholder": {"tag": "plain_text", "content": "请选择"},
        "options": _options(question),
    }
    if multi:
        selector["selected_values"] = []
    other: dict[str, Any] = {
        "tag": "input",
        "name": _other_name(index),
        "placeholder": {"tag": "plain_text", "content": "其他（可选；填了以这里为准）"},
        "max_length": MAX_OTHER_CHARS,
    }
    title = f"**{index + 1}. {question.get('question', '')}**"
    hint = "\n可选多个" if multi else ""
    return {
        "tag": "column_set",
        "flex_mode": "none",
        "background_style": "default",
        "horizontal_spacing": "default",
        "columns": [
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "vertical_align": "top",
                "elements": [
                    {"tag": "markdown", "content": title + hint},
                    selector,
                    other,
                ],
            },
        ],
    }


def question_card(row: AgentQuestion) -> dict[str, Any]:
    questions = row.questions or []
    elements = [_text("请选择下面的答案。每个问题都要有选择或填写「其他」。")]
    elements.append(
        {
            "tag": "form",
            "name": FORM_NAME,
            "elements": [
                *[_question_block(index, question) for index, question in enumerate(questions)],
                {
                    "tag": "column_set",
                    "flex_mode": "bisect",
                    "horizontal_spacing": "default",
                    "columns": [
                        {
                            "tag": "column",
                            "width": "weighted",
                            "weight": 1,
                            "vertical_align": "top",
                            "elements": [
                                {
                                    "tag": "button",
                                    "action_type": "request",
                                    "name": "mosael_questions_skip",
                                    "text": {"tag": "plain_text", "content": "跳过"},
                                    "type": "default",
                                    "width": "fill",
                                    "value": {"action": ACTION_SKIP, "question_id": row.id},
                                }
                            ],
                        },
                        {
                            "tag": "column",
                            "width": "weighted",
                            "weight": 1,
                            "vertical_align": "top",
                            "elements": [
                                {
                                    "tag": "button",
                                    "action_type": "form_submit",
                                    "name": SUBMIT_NAME,
                                    "type": "primary",
                                    "text": {"tag": "plain_text", "content": "提交"},
                                    "width": "fill",
                                    "value": {"action": ACTION_ANSWER, "question_id": row.id},
                                }
                            ],
                        },
                    ],
                },
            ],
        }
    )
    return {
        "config": {"wide_screen_mode": True},
        "header": {"template": "orange", "title": {"tag": "plain_text", "content": "需要你选择"}},
        "elements": elements,
    }


def settled_question_card(row: AgentQuestion) -> dict[str, Any]:
    if row.status == "dismissed":
        return {
            "config": {"wide_screen_mode": True},
            "header": {"template": "grey", "title": {"tag": "plain_text", "content": "已跳过"}},
            "elements": [_text("这组问题已跳过。")],
        }
    answers = row.answers or {}
    lines = []
    for question in row.questions or []:
        picked = answers.get(question.get("question"))
        if not picked:
            continue
        label = "、".join(str(one) for one in (picked if isinstance(picked, list) else [picked]))
        lines.append(f"**{question.get('question')}**\n{label}")
    return {
        "config": {"wide_screen_mode": True},
        "header": {"template": "green", "title": {"tag": "plain_text", "content": "已提交"}},
        "elements": [_text("\n\n".join(lines) or "答案已提交。")],
    }


def answers_from_form(row: AgentQuestion, form_value: Any) -> dict[str, list[str]]:
    if not isinstance(form_value, dict):
        raise ValueError("缺少表单内容")
    answers: dict[str, list[str]] = {}
    for index, question in enumerate(row.questions or []):
        other = str(form_value.get(_other_name(index)) or "").strip()
        if len(other) > MAX_OTHER_CHARS:
            raise ValueError("「其他」太长")
        if other:
            answers[str(question.get("question"))] = [other]
            continue
        picked = form_value.get(_field_name(index))
        if isinstance(picked, list):
            values = [str(one).strip() for one in picked if str(one).strip()]
        elif picked is None:
            values = []
        else:
            values = [str(picked).strip()] if str(picked).strip() else []
        if not values:
            raise ValueError("每个问题都要选一个或填写「其他」")
        if not bool(question.get("multi_select")) and len(values) > 1:
            raise ValueError("单选题只能选一个")
        answers[str(question.get("question"))] = values
    return answers


def announce(db: Session, row: AgentQuestion) -> str | None:
    origin = routing.session_origin(db, row.session_id)
    if origin is None:
        return None
    bot, chat_id = origin
    try:
        return client.send_card(bot, chat_id, question_card(row))
    except Exception as exc:  # noqa: BLE001 —— 问题已经落库,卡片只是渠道
        logger.warning("feishu question card failed question=%s", row.id, exc_info=True)
        reason = str(getattr(exc, "detail", "") or exc)[:300]
        try:
            client.send_text(bot, chat_id, f"有一组选择需要你在 Mosael 里回答;飞书卡片发送失败:{reason}")
        except Exception:  # noqa: BLE001
            logger.warning("feishu question fallback text failed question=%s", row.id, exc_info=True)
        return None


def handle_card_action(open_id: str, value: dict[str, Any], bot_id: str = "") -> dict[str, Any]:
    action = str(value.get("action") or "")
    question_id = str(value.get("question_id") or "")
    if action not in ACTIONS or not question_id:
        return {"toast": {"type": "error", "content": "无法识别的操作"}}

    with SessionLocal() as db:
        row = db.get(AgentQuestion, question_id)
        if row is None:
            return {"toast": {"type": "error", "content": "这组问题已经不存在了"}}
        if row.status != "pending":
            return {"toast": {"type": "info", "content": "这组问题已经处理过了"}}
        origin = routing.session_origin(db, row.session_id)
        app_id = bot_id or (origin[0].id if origin is not None else "")
        user = bindings.resolve_sender(db, row.workspace_id, app_id, open_id) if open_id else None
        if user is None:
            return {"toast": {"type": "error", "content": "请先在 Mosael 的「飞书机器人」里绑定你的账号"}}

        try:
            if action == ACTION_SKIP:
                answered = use_cases.dismiss(db, user, row.id)
            else:
                answers = answers_from_form(row, value.get("form_value"))
                answered = use_cases.answer(db, user, row.id, answers)
            db.commit()
        except ValueError as exc:
            db.rollback()
            message = str(exc)
            if message.startswith("questionErr_"):
                message = "答案不完整或已经失效,请重新打开这组问题。"
            return {"toast": {"type": "error", "content": message}}
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("feishu question answer failed question=%s", question_id)
            return {"toast": {"type": "error", "content": "处理失败,请到 Mosael 里查看"}}

        settled = settled_question_card(answered)
        if origin is not None and answered.feishu_message_id:
            try:
                client.update_card(origin[0], answered.feishu_message_id, settled)
            except Exception:  # noqa: BLE001 —— 回调响应仍会更新;这里失败只记日志
                logger.warning(
                    "feishu question card update failed question=%s message=%s",
                    question_id, answered.feishu_message_id, exc_info=True,
                )
        return {"card": {"type": "raw", "data": settled}}
