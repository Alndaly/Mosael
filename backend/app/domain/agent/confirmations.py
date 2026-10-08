from __future__ import annotations

from typing import Any

from sqlalchemy import false, update
from sqlalchemy.orm import Session

from app.core.i18n import DEFAULT_LOCALE, render_message
from app.db.models import ToolConfirmation, User, now
from app.domain.agent.confirmable import tool_spec
from app.domain.agent.errors import ConfirmationError
from app.domain.agent.sessions import decides_for_filter, ensure_decides_for
from app.domain.jobs import reset_receipt, set_receipt
from app.domain.permissions import ensure_workspace_perm, holds_workspace_perm

"""
Confirmation kernel (plan §16.2/§17.2): mutating external-agent tools never
execute directly. They create a pending confirmation; the user approves it in
the UI, and only then does the mapped action run. Timeline edits go through
SequenceOperations, so every approved edit stays undoable.

**内核不认识任何具体工具。** 每个工具在 domain/agent/confirmable 里声明自己要什么权限、卡上
怎么说、批准之后做什么(此前是这里的四条 if 链,加一个工具要在四处各补一段)。
"""

__all__ = [
    "ConfirmationError",
    "approve_confirmation",
    "authorize_and_approve",
    "authorize_and_reject",
    "decidable_filter",
    "effective_permission",
    "reject_confirmation",
    "request_confirmation",
    "tool_permission",
]


#: 摘要参数里的两个**约定名**,应用里的确认卡会把它们从那句话里拆出来单独摆:
#:
#:   · `warning` —— 点明后果的那半句(domain/effects.warning_key、graphs.external_warning),
#:     卡上成一条提示,不再拖在标题末尾和徽标、按钮抢一行;
#:   · `args`    —— 参数的一行摘要(plugin_tools.brief_arguments),卡上已经逐项列出了参数。
#:
#: 飞书、MCP 这些**只有一行字**的出口照旧读完整的 `summary`:那里没有别的地方放这两段。
CARD_WARNING_PARAM = "warning"
CARD_DETAIL_PARAMS = ("args",)


def card_parts(summary_key: str, summary_params: dict[str, Any], locale: str) -> tuple[str, str]:
    """应用里那张卡的**标题**与**后果提示**,按读的人的语言。

    标题是同一句摘要去掉上面两段;提示是 `warning` 那半句单独渲染出来,去掉它在句中时的
    装饰(前导空格、⚠️、括号) —— 卡上它自带图标、自成一行。老卡没有 key,标题就是原话。
    """
    if not summary_key:
        return "", ""
    params = dict(summary_params or {})
    warning_param = params.get(CARD_WARNING_PARAM)
    for name in (CARD_WARNING_PARAM, *CARD_DETAIL_PARAMS):
        if name in params:
            params[name] = ""
    headline = render_message(summary_key, locale, params)
    warning = ""
    if isinstance(warning_param, dict) and "__key" in warning_param:
        warning = render_message(str(warning_param["__key"]), locale, warning_param.get("params") or {})
    return headline, _standalone(warning)


def _standalone(clause: str) -> str:
    """句中的半句 → 独立的一句:「  ⚠️ 会在你的电脑上运行代码」→「会在你的电脑上运行代码」,
    「 (this costs money or paid compute)」→「This costs money or paid compute」。"""
    text = clause.strip().removeprefix("⚠️").strip()
    for opening, closing in (("(", ")"), ("\uff08", "\uff09")):
        if text.startswith(opening) and text.endswith(closing):
            text = text[len(opening):-len(closing)].strip()
    return text[:1].upper() + text[1:]


def tool_permission(tool: str) -> str:
    """这个工具的**下限**档位。实际那一档见 effective_permission。"""
    spec = tool_spec(tool)
    if spec is None:
        raise ConfirmationError(f"Unknown mutating tool: {tool}")
    return spec.permission


def tool_cost(tool: str) -> str:
    spec = tool_spec(tool)
    return spec.cost if spec is not None else "none"


def request_confirmation(
    db: Session,
    *,
    workspace_id: str,
    tool: str,
    payload: dict[str, Any],
    actor_id: str | None,
    requested_by: str = "external-agent",
    session_id: str | None = None,
    tool_call_id: str | None = None,
) -> ToolConfirmation:
    """开一张卡。`actor_id` 是开卡的人(发起这次调用的凭据是谁的),校验里因人而异的事实按他算。"""
    spec = tool_spec(tool)
    if spec is None:
        raise ConfirmationError(f"Unknown mutating tool: {tool}")
    if spec.validate is not None:
        spec.validate(db, workspace_id, payload, actor_id)
    #: **key 和参数才是事实,渲染出来的那一行只是默认语言的快照。**
    #: 确认卡是授权界面 —— 用户点「批准」之前唯一会读的就是这一行,而卡落库、活得比一次请求久。
    #: 写入时就翻会把语言冻死在那一刻(`Job.message` 为这件事付过账,见 domain/jobs.say)。
    summary_key, summary_params = spec.summarize(db, payload)
    confirmation = ToolConfirmation(
        workspace_id=workspace_id,
        tool=tool,
        permission=effective_permission(db, tool, payload),
        summary=render_message(summary_key, DEFAULT_LOCALE, summary_params),
        summary_key=summary_key,
        summary_params=summary_params,
        payload=payload,
        requested_by=requested_by,
        session_id=session_id,
        tool_call_id=tool_call_id,
    )
    db.add(confirmation)
    db.flush()
    db.refresh(confirmation)
    return confirmation


def authorize_and_approve(
    db: Session, user: User, confirmation: ToolConfirmation, choices: dict[str, bool] | None = None
) -> ToolConfirmation:
    """批准一张确认卡 —— **所有入口的唯一实现**。

    `choices`:批的人在卡上拨过的开关(只认工具声明过的那几个,见 ConfirmableTool.choices)。没给的照开卡时的缺省 ——
    飞书那条入口和自动放行都不给。

    入口不止一个:桌面端走 HTTP 路由(bearer token 认身份),飞书走卡片回调(open_id 经账号
    绑定认身份)。身份怎么认由入口负责,认出来之后「这个人能不能批、批了会发生什么」必须只有
    一份 —— 之前是两边各抄一遍,谁往路由里加第四道校验,飞书那条就会静默漏掉,而这恰恰是授权
    路径,漏掉等于越权。

    两道闸门缺一不可:
      - ensure_workspace_perm(edit):他得是这个工作区的人,**而且**持有 edit。这里点名 edit,
        而不是靠 ensure_workspace_access 去看「当前请求是不是 POST」—— 那个判断读的是只在 ASGI
        中间件里绑定的 ContextVar,默认 GET。今天两个入口都是 POST,所以校验碰巧成立;哪天批准
        从后台线程发起(自动放行、重试、队列),viewer 的批准就会连同执行一起通过且不报错。
        批准永远是写操作,权限就该显式写出来。
      - 记在谁头上:decided_by。

    此前这里还有第三道 —— `ensure_graph_node_privileges`,专门挡 code 节点。它随隔离执行器一起
    撤掉了(ADR 0008 D2):那道闸本来就是缺沙箱的补丁,而「谁有资格写代码」是个错问题。代码现在
    跑在内核强制的隔离里(见 domain/sandbox),写它就是普通的内容编辑。

    卡挂在某次有主人的对话上时,还得**是那次对话的主人**(`ensure_decides_for`):对话共享给同事是
    给他看,替主人拍板是在别人的对话里写 —— 批准之后的动作还会记在批的人头上、用他的钥匙跑。
    """
    _ensure_decides(db, user, confirmation)
    # 记在谁头上。自动放行也有人 —— 这次 turn 是以他的身份跑的,上面三道闸也是按他校验的。
    # `decision_mode` 不在这里定:默认就是 manual(人点的),自动放行会在派活之前先改掉它。
    confirmation.decided_by = user.id
    return approve_confirmation(db, confirmation, choices)


def effective_permission(db: Session, tool: str, payload: dict[str, Any]) -> str:
    """这次调用**实际属于**哪一档。声明里的那一档只是下限。

    静态表说不清后果,因为同一个工具的后果取决于参数:`run_workflow` 挂在 `ai-cost` 上,而它要跑的
    那张图里可能有 publish / http_request / code / browser_* —— 一张"可能产生 AI 消耗"的卡能执行
    以上全部。反过来,一张只有 llm 节点的图就真的只是花钱。派生规则归工具自己声明
    (`ConfirmableTool.escalate`),内核只问一声。

    档位不是徽标而已:它决定卡片的措辞,三档权限模式下还直接决定要不要放行。定错了,放开的就是
    错的东西。
    """
    spec = tool_spec(tool)
    if spec is None:
        raise ConfirmationError(f"Unknown mutating tool: {tool}")
    if spec.escalate is not None:
        return spec.escalate(db, tool, payload) or spec.permission
    return spec.permission


def authorize_and_reject(db: Session, user: User, confirmation: ToolConfirmation) -> ToolConfirmation:
    """拒绝一张确认卡。同样要 edit —— 拒绝是对**别人发起的待办**下结论,和批准是同一类决定。

    这不是收紧:两个入口都是 POST,而 ensure_workspace_access 在 POST 上判的就是 edit,所以
    走 HTTP 一直如此。写成显式的,是为了不让同一个人在两条调用路径上得到两种答案。
    有主人的对话里的卡,和批准同一条:只有主人。
    """
    _ensure_decides(db, user, confirmation)
    return reject_confirmation(db, confirmation)


# ---------- 谁能拍板:批的那一刻问一次,出清单时问一次 ----------
#
# 全局确认中心只列他能拍板的卡(`decidable_filter`):列出来却点不动(共享来的对话里的卡批了回 403)的那张,
# 在中心里只是一张永远消不掉的卡。两处答的是同一个问题,所以两份判据紧挨着写,各由同一对子判据拼成 ——
# 工作区的 edit 权限 + 卡所在的那次对话(domain/agent/sessions 的 ensure_decides_for / decides_for_filter)。


def _ensure_decides(db: Session, user: User, confirmation: ToolConfirmation) -> None:
    """批 / 拒一张卡之前:工作区的 edit(否则 403),再加那次对话的主人规矩(见 `ensure_decides_for`)。"""
    ensure_workspace_perm(db, user, confirmation.workspace_id, "edit")
    ensure_decides_for(db, confirmation.session_id, user.id)


def decidable_filter(db: Session, user: User, workspace_id: str) -> Any:
    """`_ensure_decides` 的 SQL 版:这个工作区里他批得了的卡。角色不够就一张都没有。

    只管「有没有资格」,不管状态:已经有结论的卡批了回 409,那是另一回事,列表按 `status` 另筛。
    """
    if not holds_workspace_perm(db, user, workspace_id, "edit"):
        return false()
    return (ToolConfirmation.workspace_id == workspace_id) & decides_for_filter(ToolConfirmation.session_id, user.id)




def reject_confirmation(db: Session, confirmation: ToolConfirmation) -> ToolConfirmation:
    _claim(db, confirmation, "rejected")
    confirmation.resolved_at = now()
    db.flush()
    return confirmation


def approve_confirmation(
    db: Session, confirmation: ToolConfirmation, choices: dict[str, bool] | None = None
) -> ToolConfirmation:
    # 开关先查(认不出的键不认领这张卡,人改了再点),认领之后再写进 payload:认领那一笔会提交,
    # 写在它前面的话,一张已经被别人批掉的卡的 payload 也会跟着被改掉。
    picked = _checked_choices(confirmation, choices)
    _claim(db, confirmation, "approved")
    if picked:
        confirmation.payload = {**(confirmation.payload or {}), **picked}
    try:
        result = _execute(db, confirmation)
        confirmation.status = "executed"
        confirmation.result = result
    except Exception as exc:
        # **执行体炸了,它做了一半的改动整个撤掉**,卡只记「失败」。此前这里只改状态,入口照常提交 ——
        # 删两个素材、第二个炸了,第一个照样删掉(连文件),卡上却写着失败:卡说的和库里的不是一回事。
        #
        # 撤得干净是因为 `_claim` 刚提交过:从那一刻起会话里只有执行体的改动,回滚正好就是它那一段
        # (提交之后才跑的钩子 —— 删文件、起任务线程 —— 跟着丢掉,见 core/unit_of_work)。
        db.rollback()
        confirmation.status = "failed"
        #: **整句存下,不按位置截**(与 jobs.blame 同一条):`error` 是 Text 列,长短是界面排版的事 —— 卡上过长的
        #: 原因折起来显示(ConfirmationCard)。此前的 `[:500]` 把长一点的原因切成半句,切掉的恰好是后半截,
        #: 而原因往往就写在后半截;智能体经 get_confirmation 读到的也是那半句。
        confirmation.error = str(exc)
    confirmation.resolved_at = now()
    # 不提交:批准的入口(路由、飞书回调、自动放行的线程)提交。认领那一笔已经在 _claim 里落了。
    db.flush()
    db.refresh(confirmation)
    return confirmation


def _checked_choices(confirmation: ToolConfirmation, choices: dict[str, bool] | None) -> dict[str, bool]:
    """卡上的开关:只认这个工具声明过的、只认布尔。别的键一律拒 —— 批准这一下不是改 payload 的通道。"""
    if not choices:
        return {}
    spec = tool_spec(confirmation.tool)
    allowed = spec.choices if spec is not None else ()
    unknown = sorted(key for key in choices if key not in allowed)
    if unknown or not all(isinstance(value, bool) for value in choices.values()):
        raise ConfirmationError("confirmErr_unknownChoice", keys=", ".join(unknown) or ", ".join(choices))
    return dict(choices)


def _claim(db: Session, confirmation: ToolConfirmation, to_status: str) -> None:
    """Take exclusive ownership of a pending confirmation, or refuse.

    Reading `confirmation.status` off the in-memory object and then assigning it is a
    check-then-act: two requests that both load the pending row both pass the check and both
    run the executor. That is a second track added, a second render queued, a second image
    billed. One conditional UPDATE lets the database pick a winner instead — the loser changes
    no rows and is told the confirmation is already settled.
    """
    result = db.execute(
        update(ToolConfirmation)
        .where(ToolConfirmation.id == confirmation.id, ToolConfirmation.status == "pending")
        .values(status=to_status)
    )
    # 这里仍提交:认领是「这张卡归我执行了」,要在执行器开跑之前落定 —— 执行器可能很慢、可能付费,
    # 中途进程没了,卡也不能回到 pending 被再批一次;提交同时放掉 SQLite 的写锁,不让慢执行器攥着它。
    db.commit()
    db.refresh(confirmation)
    if result.rowcount != 1:
        raise ConfirmationError(f"Confirmation is already {confirmation.status}")


def _execute(db: Session, confirmation: ToolConfirmation) -> dict[str, Any]:
    """跑这张卡批准的那件事。

    整段包在 set_receipt 里:**这里面建的任何后台任务,干完了都把回执送回发起它的那次对话**。
    智能体此前提交完就断了线索,只知道「提交成功」,不知道跑完没有 —— 要么反复轮询,要么
    干脆当作没这回事。发布/导出/生成各有各的入口函数,逐个加参数就得每加一种任务改一处,
    而漏掉的那一处不会报错,只是那种任务的回执永远送不到。
    """
    if confirmation.session_id:
        from app.domain.agent.receipts import receipt_to_session

        token = set_receipt(receipt_to_session(confirmation.session_id))
        try:
            return _execute_approved(db, confirmation)
        finally:
            reset_receipt(token)
    return _execute_approved(db, confirmation)


def _execute_approved(db: Session, confirmation: ToolConfirmation) -> dict[str, Any]:
    spec = tool_spec(confirmation.tool)
    if spec is None:
        raise ConfirmationError(f"No executor for tool {confirmation.tool}")
    # 这一步替谁干:批准它的那个人。智能体自己不是主体 —— 它花的是批准者的额度、用的是
    # 批准者的钥匙(见 domain/providers/credentials 与 Job.created_by)。
    return spec.execute(db, confirmation, confirmation.decided_by)
