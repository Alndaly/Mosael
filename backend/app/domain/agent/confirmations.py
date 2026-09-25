from __future__ import annotations

from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.i18n import DEFAULT_LOCALE, render_message
from app.db.models import ToolConfirmation, User, now
from app.domain.agent.confirmable import tool_spec
from app.domain.agent.errors import ConfirmationError
from app.domain.jobs import reset_receipt, set_receipt
from app.domain.permissions import ensure_workspace_perm

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
    "effective_permission",
    "reject_confirmation",
    "request_confirmation",
    "tool_permission",
]


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
    )
    db.add(confirmation)
    db.commit()
    db.refresh(confirmation)
    return confirmation


def authorize_and_approve(db: Session, user: User, confirmation: ToolConfirmation) -> ToolConfirmation:
    """批准一张确认卡 —— **所有入口的唯一实现**。

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
    """
    ensure_workspace_perm(db, user, confirmation.workspace_id, "edit")
    # 记在谁头上。自动放行也有人 —— 这次 turn 是以他的身份跑的,上面三道闸也是按他校验的。
    # `decision_mode` 不在这里定:默认就是 manual(人点的),自动放行会在派活之前先改掉它。
    confirmation.decided_by = user.id
    return approve_confirmation(db, confirmation)


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
    """
    ensure_workspace_perm(db, user, confirmation.workspace_id, "edit")
    return reject_confirmation(db, confirmation)




def reject_confirmation(db: Session, confirmation: ToolConfirmation) -> ToolConfirmation:
    _claim(db, confirmation, "rejected")
    confirmation.resolved_at = now()
    db.commit()
    return confirmation


def approve_confirmation(db: Session, confirmation: ToolConfirmation) -> ToolConfirmation:
    _claim(db, confirmation, "approved")
    try:
        result = _execute(db, confirmation)
        confirmation.status = "executed"
        confirmation.result = result
    except Exception as exc:
        confirmation.status = "failed"
        confirmation.error = str(exc)[:500]
    confirmation.resolved_at = now()
    db.commit()
    db.refresh(confirmation)
    return confirmation


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
    # 批准者的钥匙(见 domain/provider_credentials 与 Job.created_by)。
    return spec.execute(db, confirmation, confirmation.decided_by)
