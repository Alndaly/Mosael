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

from app.core.i18n import LocalizedError
from app.db.models import AgentQuestion, AgentSession, User, now

MAX_QUESTIONS = 4
MAX_OPTIONS = 6
MAX_HEADER_CHARS = 12
#: 「其它」那一栏的自由文本上限。它会原样变成喂给模型的一条用户消息,
#: 所以它和别的用户输入一样要有界(见仓库里 MAX_TEXT_CHARS 那条约定)。
MAX_FREE_TEXT_CHARS = 2000


class QuestionError(LocalizedError, ValueError):
    """面向模型的错误。消息要说清怎么改 —— 它下一步就是改了重发。

    带文案 key(`questionErr_*`),按请求方的语言翻:模型读哪种都行,而界面上的提示条是给人看的。"""


def normalize(raw: Any) -> list[dict[str, Any]]:
    """把模型给的问题清单校成规整形状。

    校得严是因为**这些字段直接进界面**:没有 label 的选项渲染成一个点不动的空按钮,
    重复的 label 让答案对不回是哪一个,超长的 header 把卡片撑破。模型偶尔会犯这些错,
    而它们的表现都不是报错,是界面坏掉。
    """
    if not isinstance(raw, list) or not raw:
        raise QuestionError("questionErr_listEmpty")
    if len(raw) > MAX_QUESTIONS:
        raise QuestionError("questionErr_tooMany", max=MAX_QUESTIONS)
    out: list[dict[str, Any]] = []
    seen_questions: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise QuestionError("questionErr_notObject")
        question = str(item.get("question") or "").strip()
        if not question:
            raise QuestionError("questionErr_questionEmpty")
        if question in seen_questions:
            raise QuestionError("questionErr_duplicate", question=question)
        seen_questions.add(question)

        options = item.get("options")
        if not isinstance(options, list) or len(options) < 2:
            raise QuestionError("questionErr_tooFewOptions", question=question)
        if len(options) > MAX_OPTIONS:
            raise QuestionError("questionErr_tooManyOptions", question=question, max=MAX_OPTIONS)
        cleaned: list[dict[str, str]] = []
        seen_labels: set[str] = set()
        for option in options:
            if not isinstance(option, dict):
                raise QuestionError("questionErr_optionNotObject")
            label = str(option.get("label") or "").strip()
            if not label:
                raise QuestionError("questionErr_optionLabelEmpty")
            if label in seen_labels:
                raise QuestionError("questionErr_optionDuplicate", question=question, label=label)
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

    只认**这次问过的那些问题** —— 没问过的问题一律拒。

    **选项不限定在给出的那几个里**:「其它」走自由文本,那是这张卡的设计之一。此前这段
    docstring 写的是"只认出现过的选项",而代码从来没那么做过(`allowed` 里那个 label 集合
    算出来只用来判断问题问没问过)—— **一个算出来却没用上的变量,既不会被 lint 报,也不会
    有任何行为差异**,它唯一的证据就是那段与代码不符的说明,而说明在上面。

    自由文本因此有两条真的约束(此前只写在注释里,没写成代码):**一条**(自由文本不是多选)、
    **有长度上限**。它会经 `_as_user_words` 原样变成对话里的一条用户消息喂给模型。
    """
    if row.status != "pending":
        raise QuestionError("questionErr_alreadyAnswered")
    allowed = {q["question"]: {o["label"] for o in q["options"]} for q in row.questions}
    cleaned: dict[str, list[str]] = {}
    for question, picked in (answers or {}).items():
        labels = allowed.get(str(question))
        if labels is None:
            raise QuestionError("questionErr_notAsked", question=question)
        chosen = picked if isinstance(picked, list) else [picked]
        # 「其它」走自由文本:不在选项里的值原样收下。
        values = [str(one).strip() for one in chosen if str(one).strip()]
        if not values:
            raise QuestionError("questionErr_nothingPicked", question=question)
        # **把注释里那两条写成代码。** 它们此前只是注释,而注释拦不住任何东西 ——
        # 这段文本会原样变成对话里的一条用户消息喂给模型。
        free_text = [one for one in values if one not in labels]
        if free_text and len(values) > 1:
            raise QuestionError("questionErr_freeTextOnlyOne", question=question)
        for one in free_text:
            if len(one) > MAX_FREE_TEXT_CHARS:
                raise QuestionError("questionErr_freeTextTooLong", question=question, max=MAX_FREE_TEXT_CHARS)
        cleaned[str(question)] = values
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

    这条路现在是**兜底**,不是唯一通路。应用自己那条运行时(sidecar)调 ask_user 时会停在
    那次工具调用上等着,用户一选,答案就作为工具结果回到它被问的那个位置 —— 不需要这条。

    但兜底不能撤:等待有上限(590s,压在 turn 超时底下),用户去想一想再回来是常事;直连
    MCP 的客户端根本不阻塞;后端重启也会把那一轮掐掉。这些情形下"选"就只是把一行状态改成
    answered,没有任何东西会再开一轮 —— 真机上的样子是点完之后**什么都不发生**。
    `dismiss` 的说明写着「模型会收到『用户跳过了』并继续往下走」,那也得有人把结果送回去。

    走的是任务回执那条现成的路(见 domain/agent/receipts):会话闲就立刻开新一轮,忙就插话。

    **阻塞那条路上它照发,不去判重。** 于是模型可能把同一个选择看两遍:一遍是工具结果,
    一遍是这条插进来的话。两个理由:

    1. 这条消息还有第二份工作 —— 它是**对话里那条记录**。卡片答完就消失了,不留这句的话,
       事后翻对话只看得到一个凭空出现的转折,看不到用户当时选的是什么。
    2. 判重要成立,得在用户作答**之前**就知道"有人正等着",而作答那一刻正是这条消息发出的
       一刻 —— 中间没有可靠的间隙。硬做就得引入定时器和"认领"状态,而它做错的方式是**answer
       掉进空里**:看不见。看两遍看得见,也忽略得掉。这条权衡从一开始就是这么定的。

    **忙的时候也送,而且是插进那一轮**(`steer_if_running`)。反过来判断「在跑就不送」是个
    竞态:检查时它在跑、送出去之前它结束了,答案就再一次掉进空里。而排队同样不对 —— 模型
    此刻正基于"还没拿到答案"往下走,答案却在队列里等这一轮跑完;用户看到的是输入框上方
    冒出一条**他没写过**的消息(「我选好了:…」),带着 Steer 和删除两个按钮,莫名其妙。
    插不进去时才落回排队,由那一轮结束时的 drain 接走。
    """
    from app.domain.agent import host

    session = db.get(AgentSession, row.session_id)
    if session is None:
        return
    # 正文要像用户自己说的话(模型读的是它),而**结构另存一份**:一次选择在对话里不该退化成
    # 一段自述 —— 界面据此画回「问的是什么、选的是哪一项」,而不是一行「我选好了:…」。
    host.post_user_message(db, session, _as_user_words(row), user,
                           answers=_answer_record(row), steer_if_running=True)


def _answer_record(row: AgentQuestion) -> dict | None:
    """这次作答的结构:问了什么、选了哪几项、是不是跳过了。界面画卡片用它。

    带上 `question_id`:同一次作答在对话里会留下**两份**痕迹 —— `ask_user` 那次工具调用的
    结果,和这条送回会话的回执消息。阻塞那条路上两份都在,界面画两遍(用户看到同一个选择
    紧挨着出现两次);超时那条路上工具结果是 `pending`,回执是唯一记录,必须画。
    界面靠这个 id 分辨这两种情形,而不是猜。
    """
    if row.status == "dismissed":
        return {"dismissed": True, "question_id": row.id}
    picked = row.answers or {}
    if not picked:
        return None
    return {"question_id": row.id,
            "picked": [{"question": question,
                        "choices": list(one) if isinstance(one, list) else [one]}
                       for question, one in picked.items()]}


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
