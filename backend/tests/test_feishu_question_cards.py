"""飞书问题卡:单选 / 多选 / 自由文本都进入同一个 AgentQuestion。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.integrations.feishu import question_cards


def _row(*, multi: bool = False, answers: dict | None = None):
    return SimpleNamespace(
        id="q1",
        session_id="s1",
        status="pending" if answers is None else "answered",
        questions=[{
            "header": "风格",
            "question": "选一个风格",
            "multi_select": multi,
            "options": [
                {"label": "简洁", "description": ""},
                {"label": "丰富", "description": ""},
            ],
        }],
        answers=answers or {},
    )


def test_single_and_multi_use_the_matching_feishu_component() -> None:
    import json

    single = json.dumps(question_cards.question_card(_row()), ensure_ascii=False)
    multi = json.dumps(question_cards.question_card(_row(multi=True)), ensure_ascii=False)
    assert '"tag": "select_static"' in single
    assert '"tag": "multi_select_static"' not in single
    assert '"tag": "multi_select_static"' in multi
    assert '"tag": "select_static"' not in multi
    assert question_cards.FORM_NAME in single
    assert '"max_length": 1000' in single
    assert "form_submit" in single
    assert question_cards.ACTION_ANSWER in single
    assert question_cards.ACTION_SKIP in single


def test_form_values_keep_single_multi_and_free_text() -> None:
    single = _row()
    assert question_cards.answers_from_form(single, {"question_0": "简洁"}) == {"选一个风格": ["简洁"]}
    multi = _row(multi=True)
    assert question_cards.answers_from_form(multi, {"question_0": ["简洁", "丰富"]}) == {
        "选一个风格": ["简洁", "丰富"]
    }
    assert question_cards.answers_from_form(single, {"question_0": "简洁", "question_other_0": "自定义"}) == {
        "选一个风格": ["自定义"]
    }


def test_incomplete_form_is_rejected_before_the_domain() -> None:
    with pytest.raises(ValueError):
        question_cards.answers_from_form(_row(), {})
    with pytest.raises(ValueError):
        question_cards.answers_from_form(_row(), {"question_0": ["简洁", "丰富"]})
    assert question_cards.settled_question_card(_row(answers={"选一个风格": ["简洁"]}))["header"]["title"]["content"] == "已提交"
    dismissed = _row()
    dismissed.status = "dismissed"
    assert question_cards.settled_question_card(dismissed)["header"]["title"]["content"] == "已跳过"


def test_announce_sends_the_card_to_the_session_chat(monkeypatch) -> None:
    sent: list[tuple[str, dict]] = []
    monkeypatch.setattr(question_cards.routing, "session_origin", lambda db, sid: (object(), "oc_chat"))
    monkeypatch.setattr(question_cards.client, "send_card", lambda bot, chat, card: sent.append((chat, card)) or "om_1")
    question_cards.announce(object(), _row())
    assert sent[0][0] == "oc_chat"
    assert question_cards.FORM_NAME in str(sent[0][1])


def test_callback_answers_the_same_pending_question(monkeypatch) -> None:
    from app.core.db import SessionLocal
    from app.db.models import FeishuBot
    from app.domain.agent import questions as agent_questions
    from app.domain.agent.host import get_or_create_external_session
    from tests.util import fresh_client

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        bot = FeishuBot(workspace_id=workspace, name="助手", app_id="cli_q", app_secret="s")
        db.add(bot)
        db.flush()
        session = get_or_create_external_session(
            db, workspace_id=workspace, origin="feishu", external_key=f"feishu:{bot.id}:oc_q", title="飞书 · 助手",
        )
        row = agent_questions.ask(db, workspace_id=workspace, session_id=session.id, questions=[{
            "question": "选一个风格",
            "multi_select": False,
            "options": [{"label": "简洁"}, {"label": "丰富"}],
        }])
        db.commit()
        question_id, bot_id = row.id, bot.id

    calls: list[dict] = []

    def fake_answer(db, user, qid, answers):
        current = db.get(type(row), qid)
        current.answers = answers
        current.status = "answered"
        calls.append(answers)
        return current

    monkeypatch.setattr(question_cards.bindings, "resolve_sender", lambda *args, **kwargs: type("U", (), {"id": "u1", "username": "tester"})())
    monkeypatch.setattr(question_cards.use_cases, "answer", fake_answer)
    out = question_cards.handle_card_action(
        "ou_q",
        {"action": question_cards.ACTION_ANSWER, "question_id": question_id, "form_value": {"question_0": "丰富"}},
        bot_id,
    )
    assert "card" in out and "已提交" in str(out["card"]["data"])
    assert calls == [{"选一个风格": ["丰富"]}]


def test_waiting_for_user_pauses_and_resumes_typing(monkeypatch) -> None:
    from app.integrations.feishu import inbound

    session_id = "feishu-typing-test"
    inbound._paused_typing.pop(session_id, None)
    inbound._awaiting_replies.pop(session_id, None)
    inbound._awaiting(session_id, "om_1", "re_1")
    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(inbound, "_route_for_session", lambda sid: (object(), "oc_1"))
    monkeypatch.setattr(
        inbound.client,
        "remove_reaction",
        lambda bot, message, reaction: calls.append(("remove", message, reaction)),
    )
    monkeypatch.setattr(
        inbound.client,
        "add_reaction",
        lambda bot, message, emoji: calls.append(("add", message, emoji)) or "re_2",
    )

    inbound._waiting_for_user(session_id, True)
    assert calls == [("remove", "om_1", "re_1")]
    assert session_id not in inbound._awaiting_replies
    assert inbound._paused_typing[session_id] == "om_1"

    inbound._waiting_for_user(session_id, False)
    assert calls[-1] == ("add", "om_1", inbound.client.REACTION_TYPING)
    assert inbound._awaiting_replies[session_id] == [("om_1", "re_2")]
    assert inbound._settle(session_id) == ("om_1", "re_2")


def test_waiting_finished_without_paused_typing_is_a_no_op(monkeypatch) -> None:
    from app.integrations.feishu import inbound

    called: list[str] = []
    monkeypatch.setattr(inbound, "_route_for_session", lambda sid: called.append(sid) or None)
    inbound._waiting_for_user("feishu-no-paused", False)
    assert called == []
