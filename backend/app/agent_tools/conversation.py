"""对话本身:计划、小部件、确认卡、提问、通知、睡一会儿、时间、工作区、后台任务。

从仓库根的 mcp_server.py 按工具族拆出来(架构体检第 8 条)。登记、调用身份、领域用例的调用方式见 ./registry。
"""

from __future__ import annotations

from typing import Any

from app.agent_tools.registry import (
    caller_workspaces,
    default_workspace_id,
    ImageContent,
    SESSION_ID,
    TextContent,
    tool,
    ToolInputError,
    use_case,
    with_images,
)
from app.api.schemas import (
    AgentMessageOut,
    AgentPlanUpdate,
    AgentQuestionCreate,
    AgentQuestionOut,
    ConfirmationOut,
    JobOut,
    NotificationOut,
)
from app.core.db import SessionLocal
from app.core.i18n import tr
from app.db.models import Asset
from app.domain.agent import host, places, receipts, use_cases as agent_use_cases
from app.domain.job_center import use_cases as job_center_use_cases
from app.domain.jobs.catalog import FALLBACK_LABEL_KEY, job_kind
from app.domain.jobs.constants import TERMINAL_STATUSES
from app.domain.notifications import use_cases as notifications
from app.media.paths import resolve_key

@tool(effect="writes")
def update_plan(steps: list[Any], new_plan: bool = False) -> dict[str, Any]:
    """Runs directly: publish/refresh your task plan for the current conversation.

    Use for any task that takes more than a couple of steps: write the plan out
    first, then call this again after EACH step to move it forward. The user sees
    the list live, so it is how they know what you are about to do and where you
    are — an accurate plan matters more than a detailed one.

    Each step is {"step": "...", "status": "pending"|"in_progress"|"done"}; a bare
    string is treated as pending. Exactly one step should be in_progress at a
    time. Max 20 steps. Pass an empty list to clear the plan once everything is
    finished. Pass new_plan=true when starting a DIFFERENT task; otherwise
    rewording/updating the same plan keeps its id and replaces it in history.
    Do NOT use for single-step requests — a one-item plan is noise.
    """
    session_id = SESSION_ID.get()
    if not session_id:
        return {"error": "update_plan 只能在 Mosael 的对话会话里使用"}

    request = AgentPlanUpdate(steps=steps)
    return use_case(agent_use_cases.plan_snapshot, session_id, request.steps, new_plan=new_plan)


#: show_widget 一次最多这么多字符。一张 Leaflet 地图、一个带几十行数据的小面板几 KB 就够;这条线挡的是把整页
#: 抓来的网页、几百 KB 的内联数据塞进对话 —— 它会原样落进消息记录,每次打开这段对话都要整份读回来。
WIDGET_HTML_LIMIT = 60_000
WIDGET_TITLE_LIMIT = 80


@tool(effect="reads")
def show_widget(title: str, html: str) -> dict[str, Any]:
    """Show a sandboxed HTML view (map, chart, a small page) IN YOUR ANSWER, right where you called it.

    Use it whenever the user should SEE something interactive — a rendered page, a chart, a map.
    Write the surrounding words in your reply text; the widget lands in the answer between them.
    html ≤60k chars, no network; JS/CSS inline or jsdelivr/unpkg/cdnjs; images data: or OSM tiles.
    CSS vars --foreground --background --primary. For a plain image use `![alt](mosael-asset:<id>)`
    in your reply instead — generated media is NOT shown automatically."""
    # 为什么是工具而不是回答里约定一个 ```html 代码块(两条路都能让界面画出来):
    # - 参数是结构化的,这里能**先校验**(空、超长)再交给界面;代码块写坏了(少一个反引号、JS 里本身带 ```)
    #   界面只能猜它在哪结束,猜错就是半截 HTML 混进正文。
    # - 流式输出时代码块是一点点长出来的,画到一半的 HTML 会反复重建 iframe;工具调用的参数是整份到的。
    # - 回答的正文保持是人话:复制、朗读、导出时不会带出一大段 HTML。
    # 界面从**调用参数**里取 html 来画(features/agent/turnOutputs.widgetOfTool,画在那一行明细里),
    # 结果里不回传 —— 再回一遍是让模型白读一次自己刚写的几十 KB。
    #
    # 安全边界不在这里:这里只管尺寸。HTML 是模型写的,模型读过的网页、文档都可能往里塞东西,所以界面把它
    # 关进不同源的沙箱 iframe、用 CSP 断网(见前端 features/agent/agentWidget.ts 的说明)。
    title = title.strip()
    if not html.strip():
        raise ToolInputError("agentToolErr_widgetEmpty")
    if len(html) > WIDGET_HTML_LIMIT:
        raise ValueError(
            f"html 有 {len(html)} 个字符,超过上限 {WIDGET_HTML_LIMIT}:把数据精简到要展示的那些,库从 CDN 引用而不是内联"
        )
    if len(title) > WIDGET_TITLE_LIMIT:
        raise ToolInputError("agentToolErr_widgetTitleTooLong", limit=WIDGET_TITLE_LIMIT)
    return {"shown": True, "title": title}


@tool(effect="reads")
def get_confirmation(confirmation_id: str) -> dict[str, Any] | list[TextContent | ImageContent]:
    """Read-only: poll one confirmation card by confirmation_id.

    Use only after a confirmation-required tool returns {confirmation_id,
    status:"pending"}. Status becomes executed/rejected/failed after the user
    decides in Mosael; result/error explain the outcome. If the result points at
    a screenshot asset (batch actions), the picture is returned as an image block
    so you see the post-action state without another round trip. Do NOT call this
    to find projects, assets, workflows, jobs, or arbitrary IDs.
    """

    confirmation = use_case(agent_use_cases.confirmation, confirmation_id, out=ConfirmationOut)
    result = confirmation["result"]
    data = {
        "confirmation_id": confirmation["id"],
        "status": confirmation["status"],
        "result": result,
        "error": confirmation["error"],
    }
    asset_id = result.get("screenshot_asset_id") if isinstance(result, dict) else None
    image = _screenshot_asset_image(asset_id)
    if image is None:
        return data
    return with_images({
        **data,
        "images": [{"view": "batch", "mime_type": "image/png", "data": image}],
    })


def _screenshot_asset_image(asset_id: object) -> str | None:
    """一张已入库截图 → base64;卡片结果里只存 id,不把大图塞进数据库。"""
    if not isinstance(asset_id, str) or not asset_id:
        return None
    import base64

    try:
        with SessionLocal() as db:
            asset = db.get(Asset, asset_id)
            if asset is None or not asset.file_key or asset.kind != "image":
                return None
            return base64.b64encode(resolve_key(asset.file_key).read_bytes()).decode("ascii")
    except OSError:
        return None


# --- 工作流有、智能体也该有的能力 ---------------------------------------
#
# 判据写在 tests/test_agent_workflow_parity.py 里:工作流的每个节点类型都要么有一个对应的
# 智能体工具,要么在那份清单里写明为什么不需要。同一个能力只在一个界面上存在,用户就会撞上
# "工作流能做而对话里做不到" —— 而模型撞上时不会说"我没有这个工具",它会去凑一个
# (实际发生过:让它等 5 秒,它拿 browser_wait 去等一段不可能出现的文本)。


#: 单次 sleep 的上限。没有上限的话,模型可以在一轮里睡到用户以为应用挂了 —— 而它
#: 并不知道那一端有个人在等。真要更久,那是下一轮对话该做的决定。
SLEEP_CAP_SECONDS = 60.0


@tool(effect="reads")
def sleep(seconds: float) -> dict[str, Any]:
    """Runs directly: pause for a few seconds before the next step.

    Use when the user asks to wait ("open it, wait 5 seconds, then close"), or when
    something needs time to settle before you check it again. Do NOT use to poll a job —
    that is what get_confirmation and the job tools are for. Max 60 seconds; ask the user
    to re-prompt if a longer wait is genuinely needed.
    """
    import time as _time

    capped = max(0.0, min(float(seconds), SLEEP_CAP_SECONDS))
    _time.sleep(capped)
    return {"slept_seconds": capped}


@tool(effect="reads")
def get_job(job_id: str) -> dict[str, Any]:
    """Read-only: poll one background job (transcription, render, generation) by id.

    Returns status/progress/result/error. Use after a tool that returns a job.
    """

    job = use_case(job_center_use_cases.readable, job_id, out=JobOut)
    # 看到终态了:这个任务发回这次对话的回执就不必再送(见 receipts.acknowledge_seen)。
    session_id = SESSION_ID.get()
    if session_id and job and job.get("status") in TERMINAL_STATUSES:
        use_case(receipts.acknowledge_seen, job_id, session_id)
    return job


@tool(effect="writes")
def notify_workspace(title: str, body: str = "", workspace_id: str = "") -> dict[str, Any]:
    """Runs directly: push an in-app notification to the workspace members.

    Use to report the end of something long the user asked you to do while they were away.
    Do NOT use to talk to the user in this conversation — just say it in your reply.
    """

    workspace_id = workspace_id or default_workspace_id()
    return use_case(notifications.post, workspace_id, title, body, out=NotificationOut)


@tool(effect="reads")
def list_agent_sessions(workspace_id: str = "") -> list[dict[str, Any]]:
    """Runs directly: list the agent sessions in this workspace (id, title, status, where it was opened).

    Use before notify_agent_session to find who to notify. status "running" means that
    agent is mid-turn right now; your notice would be queued behind its current work.
    `where` says which page the conversation was opened on (a note, an edit project, a
    ComfyUI workflow …). Only the user's own conversations are listed: one a teammate
    shared is view-only, so it cannot be notified.
    """

    me = SESSION_ID.get()

    def listed(db, user, workspace):
        # 共享来的对话只能看(domain/agent/sessions 的写闸):列出来只会让模型往里发一条必然被拒的通知。
        return [
            {
                "session_id": session.id,
                "title": session.title,
                "status": session.status,
                "where": places.where(session),
                "is_self": session.id == me,
            }
            for session in agent_use_cases.list_sessions(db, user, workspace)
            if session.is_mine
        ]

    return use_case(listed, workspace_id or default_workspace_id())


@tool(effect="reads", awaits_answer=True)
def ask_user(questions: list[dict[str, Any]]) -> dict[str, Any]:
    """Ask the user to choose between options you cannot decide for them.

    How the waiting works is NOT described here on purpose: it differs per runtime and a
    sentence baked into this description would be a lie to the other one. Inside Mosael the
    call blocks and hands you the answer (the manifest says so on that path); a direct MCP
    client gets {question_id, status: pending} and the reply's `message` field spells out the
    polling protocol on the spot. Either way, a return value that still says "pending" is not
    an answer — building on it means building on a choice that was never made.

    Use at a genuine fork — two or three routes all make sense and which one is right depends on
    what the user wants. Picking one yourself and building on it means a whole stretch of work
    gets thrown away when the guess was wrong; one click is far cheaper.

    Do NOT use for something you can find out yourself (list the assets, read the file, check the
    settings), for a choice with an obvious default, or to ask permission — writes already go
    through their own confirmation card.

    Each question: {"header": short chip label, "question": the full question,
    "multi_select": true if several answers can apply, "options": [{"label", "description"}]}.
    At least 2 options, at most 6; at most 4 questions in one go. Give every option a
    `description` saying what happens if it is chosen — a bare label makes people guess.

    The user can also skip. Then you get {"skipped": true} and should continue with your best
    judgement rather than asking again.
    """
    session_id = SESSION_ID.get()
    if not session_id:
        # 飞书 / 外部 MCP 客户端没有会话 —— 问题没地方显示,骗它说"等着"只会白等到超时。
        return {"error": "这次调用没有对话上下文,问不了 —— 请直接在回复里把选项写出来。"}
    # 工作区跟着这次对话走(后端按会话定),不另报 —— 缺省的「第一个工作区」未必是对话所在的那个。

    request = AgentQuestionCreate(session_id=session_id, questions=questions)
    created = use_case(agent_use_cases.ask, request.session_id, request.questions, out=AgentQuestionOut)
    return {
        "question_id": created["id"],
        "status": created["status"],
        "message": "等待用户在 Mosael 中选择。用 get_answer 轮询结果。",
    }


@tool(effect="reads")
def get_answer(question_id: str) -> dict[str, Any]:
    """Read what the user picked for an ask_user question (or whether they skipped)."""

    row = use_case(agent_use_cases.question, question_id, out=AgentQuestionOut)
    if row.get("status") == "pending":
        return {"status": "pending"}
    if row.get("status") == "dismissed":
        return {"status": "dismissed", "skipped": True}
    return {"status": "answered", "answers": row.get("answers") or {}}


@tool(effect="writes")
def notify_agent_session(session_id: str, message: str) -> dict[str, Any]:
    """Runs directly: send a message to ANOTHER agent session (@-mention style).

    The target agent receives it as a message: if it is idle this starts a new turn for it
    immediately; if it is mid-turn the message is queued and handled right after. Use for
    handing work to, or reporting results back to, a different conversation's agent.
    Do NOT use to talk to the current conversation — just write your reply.
    """
    me = SESSION_ID.get()
    if session_id == me:
        return {"error": "这是当前会话自己 —— 想说什么直接写在回复里,不用发通知。"}
    text = (message or "").strip()
    if not text:
        return {"error": "message 不能为空"}
    # 来源只走结构化字段。信封(给模型看的那句「这条来自另一个会话」)由收信那侧在**拼提示词
    # 时**加上,见 host.agent_notice_envelope —— 拼进 content 的话,用户在对话里看到的就是一行
    # 方括号标签加一串 32 位 id,而那两样都是写给模型的。

    result = use_case(host.post_from_session, session_id, content=text, origin_session_id=me or None, out=AgentMessageOut)
    queued = bool((result.get("payload") or {}).get("queued")) if isinstance(result, dict) else False
    return {
        "delivered": True,
        "target_session_id": session_id,
        # queued=True:对方正忙,这条会排在它当前回合之后;False:对方是空闲的,已直接开跑。
        "queued": queued,
    }


@tool(effect="reads")
def get_current_time(timezone: str = "") -> dict[str, Any]:
    """Read-only: what time is it right now, on the machine running this studio.

    **Use this before anything that depends on "now"** — naming a file by date, deciding
    what "最近/today/this week" means when filtering assets or jobs, scheduling a publish,
    or writing a date into a caption. You were trained with a knowledge cutoff and have no
    other way to know today's date; guessing it produces wrong filenames and wrong filters.

    timezone is an IANA name ("Asia/Shanghai", "UTC"); leave empty for the machine's own zone.
    Returns local ISO time, UTC ISO time, the zone's name and UTC offset, weekday, and the
    Unix timestamp.
    """
    from datetime import datetime, timezone as _tz
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    now_utc = datetime.now(_tz.utc)
    zone_error = ""
    if timezone.strip():
        try:
            local = now_utc.astimezone(ZoneInfo(timezone.strip()))
        except (ZoneInfoNotFoundError, ValueError):
            # 认不出的时区**不能悄悄回落到本机** —— 那会让"按东京时间"这类要求静静地按错的
            # 时区算完,而结果看起来完全正常。说出来,并如实标明用的是哪一个。
            zone_error = f"不认识时区 {timezone!r},用的是本机时区"
            local = now_utc.astimezone()
    else:
        local = now_utc.astimezone()
    offset = local.utcoffset()
    minutes = int(offset.total_seconds() // 60) if offset else 0
    return {
        "local": local.isoformat(timespec="seconds"),
        "utc": now_utc.isoformat(timespec="seconds"),
        "timezone": str(local.tzinfo),
        "utc_offset": f"{'+' if minutes >= 0 else '-'}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}",
        "weekday": local.strftime("%A"),
        "date": local.strftime("%Y-%m-%d"),
        "unix": int(now_utc.timestamp()),
        **({"warning": zone_error} if zone_error else {}),
    }


@tool(effect="reads")
def list_jobs(workspace_id: str = "", kind: str = "", limit: int = 20) -> list[dict[str, Any]]:
    """Read-only: list recent background jobs (renders, transcriptions, generations, imports).

    Use when the user asks how something is going ("渲染好了吗", "下载完了吗") and you do
    **not** have a job id — get_job needs one, and without this tool there was no way to
    find it. Also use to check whether work you started earlier in the conversation finished.
    Filter with kind ("render", "transcribe", "url_import", "generation"…). Newest first.
    Each entry is a brief (status, message/error, ids it produced); call get_job for the full payload and result.
    """

    wanted = max(1, min(int(limit), 100))
    jobs = use_case(job_center_use_cases.list_jobs, workspace_id or default_workspace_id(), kind=kind or None, top_level=True,
                     limit=wanted, out=JobOut)
    return [_job_brief(job) for job in jobs[:wanted]]


#: 列任务时每一条说明 / 错误最多留多少字。
_JOB_TEXT_CHARS = 300
#: 列任务时给模型看的 subject 摘要最多留多少字。**这是模型上下文的长度上限,不是数据层的截断**:
#: 完整原文在 `get_job` 的 payload 里;真要截时带省略号,不然「就这些」和「还有很长」在模型眼里一样。
_JOB_SUBJECT_CHARS = 120
#: 载荷里认得出「这是哪个任务」的那几格(给人看的标题、提示词开头)。
_JOB_SUBJECT_KEYS = ("subject", "title", "name", "prompt", "text")


def _job_kind_label(kind: str) -> str:
    """任务种类的名字,按**当前语言**(和 `/api/jobs/kinds` 出口那一份同一张表)。"""

    meta = job_kind(kind)
    return tr(meta.label_key if meta.kind else FALLBACK_LABEL_KEY)


def _job_fallback_subject(kind: str, payload: dict[str, Any]) -> str:
    """没有用户提示词时(生成任务的 `subject` 是空串)给模型的那一句:种类 + 素材份数;
    没有份数就只说种类。**模型要认出这是哪个任务,空字符串和整段喂给模型的正文都不行。**"""

    label = _job_kind_label(kind)
    request = payload.get("request")
    assets = request.get("source_assets") if isinstance(request, dict) else None
    count = len(assets) if isinstance(assets, list) else 0
    return tr("jobSubject_fromAssets", count=count, kind=label) if count else label


def _job_brief(job: dict[str, Any]) -> dict[str, Any]:
    """列任务时给智能体的那一条:是什么、到哪一步、产出了哪些东西的 id。整份载荷 / 结果用 get_job 看。

    此前回的是整份 JobOut —— 工作流任务的载荷和结果平均 36 KB、最大 420 KB,一次 list_jobs 回了 893 KB(维护者库里实际出现过,
    约 25 万 token),这一轮之后每次请求都整段重发(智能体那一路 AGENT-12)。
    """
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    brief: dict[str, Any] = {
        key: job.get(key) for key in ("id", "kind", "status", "progress", "created_at", "updated_at") if key in job
    }
    if job.get("parent_job_id"):
        brief["parent_job_id"] = job["parent_job_id"]
    for key in ("message", "error"):
        text = job.get(key)
        if isinstance(text, str) and text.strip():
            brief[key] = text.strip()[:_JOB_TEXT_CHARS]
    subject = next((payload[key] for key in _JOB_SUBJECT_KEYS if isinstance(payload.get(key), str) and payload[key].strip()), "")
    if subject:
        subject = subject.strip()
        #: 只截**给模型看的摘要**,带省略号;完整原文用 get_job 拿。
        brief["subject"] = (
            subject if len(subject) <= _JOB_SUBJECT_CHARS
            else f"{subject[: _JOB_SUBJECT_CHARS - 1].rstrip()}…"
        )
    else:
        #: 「用户没写提示词」不等于「没有任务」:说清是哪一类、从几份素材来的(按当前语言)。
        brief["subject"] = _job_fallback_subject(str(job.get("kind") or ""), payload)
    #: 产出:结果里叫 *_id / *_ids 的那几格(素材、字幕轨、转写……)—— 智能体接着要用的就是它们。
    produced = {
        key: value for key, value in result.items()
        if (key.endswith("_id") and isinstance(value, str))
        or (key.endswith("_ids") and isinstance(value, list) and all(isinstance(one, str) for one in value))
    }
    if produced:
        brief["produced"] = produced
    if set(result) - set(produced):
        brief["details"] = "get_job"
    return brief


@tool(effect="reads")
def list_workspaces() -> list[dict[str, Any]]:
    """Read-only: list the workspaces this user has, newest first.

    Every other tool takes an optional workspace_id and falls back to the workspace this
    conversation belongs to. Use this when the user mentions ANOTHER workspace by name, then
    pass that workspace_id explicitly.
    """
    return caller_workspaces()
