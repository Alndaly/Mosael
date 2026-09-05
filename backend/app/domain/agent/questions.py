"""智能体问用户一个有选项的问题,等他挑。

用在**岔路口**:两三条路都说得通,而选哪条取决于用户想要什么 —— 模型自己挑一条然后一路
做下去,做错了要推翻的是一整段工作。摊开来让人点一下,比事后返工便宜得多。

不该用在能自己查出答案的地方(那是懒),也不该用在只有一条路的地方(那是啰嗦)。

**和确认卡是两件事**:确认卡问「这件事能不能做」,可以被 auto_allow / bypass 自动批准;
询问问「你要哪一个」,自动回答等于让模型自己编一个答案。所以各有各的表,见 db/models。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AgentQuestion, AgentSession, User, now

MAX_QUESTIONS = 4
MAX_OPTIONS = 6
MAX_HEADER_CHARS = 12


class QuestionError(ValueError):
    """面向模型的错误。消息要说清怎么改 —— 它下一步就是改了重发。"""


def normalize(raw: Any) -> list[dict[str, Any]]:
    """把模型给的问题清单校成规整形状。

    校得严是因为**这些字段直接进界面**:没有 label 的选项渲染成一个点不动的空按钮,
    重复的 label 让答案对不回是哪一个,超长的 header 把卡片撑破。模型偶尔会犯这些错,
    而它们的表现都不是报错,是界面坏掉。
    """
    if not isinstance(raw, list) or not raw:
        raise QuestionError("questions 必须是非空数组")
    if len(raw) > MAX_QUESTIONS:
        raise QuestionError(f"一次最多问 {MAX_QUESTIONS} 个问题 —— 再多就该分两轮问")
    out: list[dict[str, Any]] = []
    seen_questions: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise QuestionError("每个问题都得是对象")
        question = str(item.get("question") or "").strip()
        if not question:
            raise QuestionError("question 不能为空")
        if question in seen_questions:
            raise QuestionError(f"问题重复了:{question} —— 答案按问题正文归位,重复就对不回去")
        seen_questions.add(question)

        options = item.get("options")
        if not isinstance(options, list) or len(options) < 2:
            raise QuestionError(f"「{question}」至少要给 2 个选项 —— 只有一个的话不必问")
        if len(options) > MAX_OPTIONS:
            raise QuestionError(f"「{question}」最多 {MAX_OPTIONS} 个选项")
        cleaned: list[dict[str, str]] = []
        seen_labels: set[str] = set()
        for option in options:
            if not isinstance(option, dict):
                raise QuestionError("每个选项都得是对象")
            label = str(option.get("label") or "").strip()
            if not label:
                raise QuestionError("选项的 label 不能为空 —— 空的会渲染成一个点不动的按钮")
            if label in seen_labels:
                raise QuestionError(f"「{question}」里选项重名:{label}")
            seen_labels.add(label)
            cleaned.append({"label": label, "description": str(option.get("description") or "").strip()})

        out.append(
            {
                # header 是卡片上那个小标签,长了会把卡片撑破;截断而不是报错 ——
                # 它只是个标签,不值得为它让整次询问失败。
                "header": str(item.get("header") or "")[:MAX_HEADER_CHARS].strip(),
                "question": question,
                "multi_select": bool(item.get("multi_select")),
                "options": cleaned,
            }
        )
    return out


def ask(db: Session, *, workspace_id: str, session_id: str, questions: Any) -> AgentQuestion:
    row = AgentQuestion(workspace_id=workspace_id, session_id=session_id, questions=normalize(questions))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def answer(db: Session, row: AgentQuestion, answers: dict[str, Any]) -> AgentQuestion:
    """记下用户挑了什么。

    只认**这次问的那些问题**里出现过的选项 —— 界面之外的调用方(或者一个改坏了的前端)
    塞进来的东西,不该变成模型看到的"用户说的话"。
    """
    if row.status != "pending":
        raise QuestionError("这个问题已经回答过了")
    allowed = {q["question"]: {o["label"] for o in q["options"]} for q in row.questions}
    cleaned: dict[str, list[str]] = {}
    for question, picked in (answers or {}).items():
        labels = allowed.get(str(question))
        if labels is None:
            raise QuestionError(f"没有问过这个问题:{question}")
        chosen = picked if isinstance(picked, list) else [picked]
        # 「其它」走自由文本:不在选项里的值原样收下,但只有一条(自由文本不是多选)。
        cleaned[str(question)] = [str(one) for one in chosen if str(one).strip()]
        if not cleaned[str(question)]:
            raise QuestionError(f"「{question}」没有选任何一项")
    row.answers = cleaned
    row.status = "answered"
    row.answered_at = now()
    db.commit()
    db.refresh(row)
    return row


def dismiss(db: Session, row: AgentQuestion) -> AgentQuestion:
    """用户不想答。模型该继续往下走,而不是卡住 —— 见 mcp_server.ask_user 的回包。"""
    if row.status == "pending":
        row.status = "dismissed"
        row.answered_at = now()
        db.commit()
        db.refresh(row)
    return row


def deliver_to_session(db: Session, row: AgentQuestion, user: User) -> None:
    """把用户的选择送回那次对话 —— 不送的话,答完就没有下文了。

    `ask_user` **不阻塞**:模型建完问题拿回一个 id,轮询一次多半还是 pending,然后这一轮就
    结束了(它没有别的办法等下去)。用户随后在界面上选了 —— 而"选"只是把一行状态改成
    answered,没有任何东西会再开一轮。真机上的样子就是:点完之后**什么都不发生**。

    `dismiss` 的说明写着「模型会收到『用户跳过了』并继续往下走」—— 回合都结束了,它拿什么收到。
    这句话要成立,就得有人把结果送回去。

    走的是任务回执那条现成的路(见 domain/agent/receipts):会话闲就立刻开新一轮,忙就排队。

    **忙的时候也送。** 那一轮可能正好自己 get_answer 拿到了,于是多出一轮"我选了 X"的确认,
    有点冗余。但反过来判断「在跑就不送」是个竞态:检查时它在跑、送出去之前它结束了,答案
    就再一次掉进空里。多一轮看得出来,也忽略得掉;死路看不出来。
    """
    from app.domain.agent import host

    session = db.get(AgentSession, row.session_id)
    if session is None:
        return
    host.post_user_message(db, session, _as_user_words(row), user)


def _as_user_words(row: AgentQuestion) -> str:
    """回执的正文 —— 用户在对话里看到的也是这一句,所以要像他自己说的话。"""
    if row.status == "dismissed":
        return "我跳过了那几个问题,你按自己的判断继续。"
    picked = row.answers or {}
    if not picked:
        return "我已经在选择卡上做了选择。"
    lines = [
        f"· {question}:{'、'.join(one) if isinstance(one, list) else one}"
        for question, one in picked.items()
    ]
    return "我选好了:\n" + "\n".join(lines)


def pending_for(db: Session, session_id: str) -> list[AgentQuestion]:
    return list(
        db.scalars(
            select(AgentQuestion)
            .where(AgentQuestion.session_id == session_id, AgentQuestion.status == "pending")
            .order_by(AgentQuestion.created_at)
        )
    )


__all__ = ["MAX_OPTIONS", "MAX_QUESTIONS", "QuestionError", "answer", "ask", "dismiss", "normalize", "pending_for"]
