from __future__ import annotations

import logging
import threading
import time
from datetime import timedelta
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.core.security import find_session
from app.db.models import AgentSession, ToolConfirmation, User, Workspace, now
from app.domain.agent import judge as judge_module
from app.domain.agent import rules
from app.domain.permissions import PermissionDenied, ensure_workspace_role

"""自动放行:一张新开的确认卡该不该不问用户就执行。

**判定同步,执行异步。** 判定全是本地 DB 查询(会话模式、工具白名单、计数),微秒级,就地做完;
执行必须离开请求线程 —— `_execute` 是阻塞的(run_code 20s、run_http 60s),而工具体回连本 API
的客户端只等 30s,就地执行会产出「已执行但报超时」:副作用发生了,状态说没发生。

**卡的静止状态永远是 pending。** 任何一条异常路径(判定说不行、授权闸挡下、执行线程炸了、
进程崩了)都停在这里等人 —— 没有第二个"半自动"状态需要谁去回收。
"""

logger = logging.getLogger(__name__)

#: 自**上次人工决定以来**,计费卡最多连开几张。花钱这一档不能无人值守地连开,而金额上限在这里
#: 是做不了的:用量是**事后**记账(生成跑完才落账),智能体可以在任何一条账目落地之前连开二十个;
#: render 更是本地 ffmpeg,根本不产生供应商用量事件。次数是当场就能数清的那个量。
#:
#: 上限约束的是"无人值守连开",不是"一天能花多少"—— 后者需要的是账单,不是闸门。用户批一张卡,
#: 计数自然归零(他回到了现场)。
COST_AUTO_LIMIT = 5

COST_PERMISSIONS = frozenset({"ai-cost", "render-cost"})

#: 「本会话始终允许」能记、能放行的几档,**由轻到重**。
#:
#: 白名单此前只记工具名,而同一个工具的档位是**按这一次的参数**升的(ConfirmableTool.escalate):点过一张 ai-cost 的
#: run_workflow「始终允许」,之后带 HTTP / 发布 / 代码节点(external)的 run_workflow 也直接放行 —— 用户放开的是
#: 「跑一张只花钱的图」,放出去的是「往外发请求」。所以记的是 (工具, 当时那一档),只放行**不高于**那一档的卡。
#:
#: 撤不回的两档(external / destroy)**不在这里**:同一个工具名下,这两档的每一张卡后果各不相同(发到哪、删什么、
#: 跑哪张图),点一次就放开的是以后所有的。自动模式对它们也是「没有可枚举的判据,一律回到人」;要持续放行其中
#: 有判据的那几类,走工作区的放行准则(rules,见 judge / always),要整个放开走 bypass —— 都是比一个按钮更明确的口子。
#: ai-cost 排在 render-cost 之后:花钱比占本机时间重。
SESSION_ALLOWABLE = ("edit", "render-cost", "ai-cost")

#: 自动放行的执行线程。起名字是为了让测试能在重建 schema 前排空它 —— 不然就是那种「看机器速度
#: 和用例顺序随机红」的失败。
AUTOPILOT_THREAD_NAME = "confirmation-autopilot"


@dataclass(frozen=True)
class Decision:
    """判定结果。`mode` 会原样落进卡的留痕字段。

    `needs_judge` 是第三种答案:规则既没允许也没拒绝,要花几秒问一次判断者。它不是"半个批准"——
    卡仍然是 pending,只是先别打扰用户(hold_until)。
    """

    approve: bool
    mode: str = "manual"
    detail: dict[str, Any] = field(default_factory=dict)
    needs_judge: bool = False


def wait_for_idle_autopilot(timeout: float = 5.0) -> bool:
    """等所有自动放行的执行线程跑完。给测试用 —— 生产里没人需要它。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        alive = [t for t in threading.enumerate() if t.name == AUTOPILOT_THREAD_NAME and t.is_alive()]
        if not alive:
            return True
        alive[0].join(timeout=max(0.0, deadline - time.monotonic()))
    return not any(t.name == AUTOPILOT_THREAD_NAME and t.is_alive() for t in threading.enumerate())


def decide(db: Session, user: User, confirmation: ToolConfirmation) -> Decision:
    """这张卡该不该自动放行。**纯读**,不改任何东西。

    顺序即优先级:每次都问 → 这一次不用问人 → 没有会话 → 不是开模式的那个人 → 工具白名单 → bypass → auto 分档。

    「每次都问」排在最前、在 bypass 之前(工具自己声明,见 ConfirmableTool.always_asks):这类操作会长期改变
    智能体以后的做法(改技能,ADR 0043),任何一种口子 —— 会话白名单、模式、放行准则、判断者 —— 都不该替人点头。

    「这一次不用问人」排在「没有会话」之前:它不是谁开的口子,而是这次调用本身不需要口子(工具自己声明,
    见 ConfirmableTool.needs_card)—— MCP 直连、飞书上跑一格的一项只读能力也一样直接跑。
    """
    from app.domain.agent.confirmable import allowance_name, tool_spec

    spec = tool_spec(confirmation.tool)
    if spec is not None and spec.always_asks:
        return Decision(approve=False, detail={"reason": "always-asks"})
    if spec is not None and spec.needs_card is not None and not spec.needs_card(db, confirmation.payload or {}):
        return Decision(approve=True, mode="no-card", detail={"permission": confirmation.permission})
    if not confirmation.session_id:
        # MCP 直连、飞书外部智能体的卡没有会话可挂模式。让它们继承任何"默认模式"就是授权范围
        # 逃逸:用户为某次对话开的口子,被一条他根本没在看的通道用掉。
        return Decision(approve=False, detail={"reason": "no-session"})
    session = db.get(AgentSession, confirmation.session_id)
    if session is None:
        return Decision(approve=False, detail={"reason": "session-gone"})
    if session.mode_set_by != user.id:
        # 飞书群聊共用一个会话(external_key 一个 chat 一个),群里任何人发消息都跑在它上面。
        # 模式是**授权动作**,只对做出授权的那个人生效。
        return Decision(approve=False, detail={"reason": "mode-set-by-someone-else"})

    permission = confirmation.permission
    # 记在哪个工具名下由卡说了算(替别的工具开卡的 run_plugin_tool 记在它替调的那个名下,见 ConfirmableTool.allowance_tool)。
    allowed_as = allowance_name(confirmation.tool, confirmation.payload)
    allowed_up_to = session_allowance(session, allowed_as)
    if allowed_up_to and _within(permission, allowed_up_to):
        # 用户在一张读过的卡上点了「本会话始终允许」—— 逐个工具、他自己点的,和模式放行是两回事,
        # 所以留痕也分开记。只放行**不高于他当时那一档**的卡(见 SESSION_ALLOWABLE)。
        return Decision(
            approve=True,
            mode="session-allow",
            detail={"tool": allowed_as, "permission": permission, "allowed_up_to": allowed_up_to},
        )

    mode = session.permission_mode
    if mode == "bypass":
        return Decision(approve=True, mode="bypass", detail={"permission": permission})
    if mode != "auto":
        return Decision(approve=False, detail={"reason": "manual"})

    if permission == "edit":
        return Decision(approve=True, mode="auto", detail={"permission": permission})
    if permission in COST_PERMISSIONS:
        used = _billable_run_length(db, session)
        if used >= COST_AUTO_LIMIT:
            return Decision(approve=False, detail={"reason": "cost-run-limit", "used": used, "limit": COST_AUTO_LIMIT})
        return Decision(
            approve=True, mode="auto", detail={"permission": permission, "used": used, "limit": COST_AUTO_LIMIT}
        )
    # external / destroy:撤不回来的那两档。规则先判 —— 明确拒绝就到此为止(判断者翻不了案),明确允许就
    # 直接放行(确定性的答案不该花一次模型调用)。只有规则没覆盖的才往下问判断者,而那要花几秒,
    # 所以交给后台并压一个 hold_until(见 consider)。
    ruling = rules.evaluate(confirmation.tool, confirmation.payload or {}, _rules_for(db, confirmation))
    detail = {"permission": permission, "rule": {"outcome": ruling.outcome, "reason": ruling.reason}}
    if ruling.allowed:
        return Decision(approve=True, mode="auto", detail=detail)
    if ruling.denied:
        return Decision(approve=False, detail=detail)
    return Decision(approve=False, needs_judge=True, mode="auto", detail=detail)


def _within(permission: str, ceiling: str) -> bool:
    """这一档在不在 `ceiling` 及以下。撤不回的两档(和不认识的档)永远不在 —— 它们不进 SESSION_ALLOWABLE。"""
    if permission not in SESSION_ALLOWABLE or ceiling not in SESSION_ALLOWABLE:
        return False
    return SESSION_ALLOWABLE.index(permission) <= SESSION_ALLOWABLE.index(ceiling)


def session_allowance(session: AgentSession, tool: str) -> str:
    """这次对话里,这个工具「始终允许」到哪一档;没允许过回空串。"""
    for entry in session.auto_allow_tools or []:
        if isinstance(entry, dict) and entry.get("tool") == tool:
            return str(entry.get("permission") or "")
    return ""


def set_session_allowances(db: Session, user: User, session: AgentSession, entries: list[tuple[str, str]]) -> None:
    """整份替换「本会话始终允许」的清单 —— 它就是用户在卡上点出来的那份。

    - 每一条是 (工具, 档位)。档位只能是 SESSION_ALLOWABLE 里的:撤不回的两档不给这个口子(理由见那里)。
    - 同一个工具出现多次取**最高**那一档:用户先在一张 edit 卡、后在一张 ai-cost 卡上点过,后者已经覆盖前者。
    - 工具得是认得的确认卡工具(插件工具按族认),否则这一条放不行任何东西,只是一条脏数据。
    - 声明了「每次都问」的工具(ConfirmableTool.always_asks)不收:界面上本来就没有这个按钮,收下的话清单里
      多一条永远不生效的承诺(decide 头一条就不放它)。
    - 记下**是谁定的**:与模式同一条规则 —— 授权只对做出授权的那个人生效(见 decide)。
    """
    from app.domain.agent.confirmable import tool_spec

    merged: dict[str, str] = {}
    for tool, permission in entries:
        if permission not in SESSION_ALLOWABLE:
            raise PermissionModeError(
                "agentErr_sessionAllowTier", tool=tool, permission=permission, allowed="/".join(SESSION_ALLOWABLE)
            )
        spec = tool_spec(tool)
        if spec is None:
            raise PermissionModeError("agentErr_sessionAllowUnknownTool", tool=tool)
        if spec.always_asks:
            raise PermissionModeError("agentErr_sessionAllowAlwaysAsks", tool=tool)
        if tool not in merged or _within(merged[tool], permission):
            merged[tool] = permission
    session.auto_allow_tools = [{"tool": tool, "permission": permission} for tool, permission in merged.items()][:40]
    session.mode_set_by = user.id
    if session.mode_set_at is None:
        session.mode_set_at = now()


#: 「本会话始终允许」是读出整份、加一条、写回去:两张卡几乎同时点(几个工具调用同时在等批),两次读到的是同一份,后写的盖掉先写的
#: (智能体那一路 AGENT-16)。后端只有一个进程,这一把锁把「读 → 合并 → 提交」排成一队就够了。
ALLOWANCE_LOCK = threading.Lock()


def add_session_allowance(db: Session, user: User, session: AgentSession, tool: str, permission: str) -> None:
    """往「本会话始终允许」里**加一条**(界面在卡上点了它):在库里那一份上合并,不信调用方手里的那份。调用方持 `ALLOWANCE_LOCK`、
    在锁里提交。校验和整份替换同一套(`set_session_allowances`)。"""
    db.refresh(session)
    current = [
        (str(entry.get("tool") or ""), str(entry.get("permission") or ""))
        for entry in (session.auto_allow_tools or []) if isinstance(entry, dict)
    ]
    set_session_allowances(db, user, session, [*current, (tool, permission)])


def _rules_for(db: Session, confirmation: ToolConfirmation) -> dict:
    workspace = db.get(Workspace, confirmation.workspace_id)
    return rules.normalize(workspace.autopilot_rules if workspace is not None else None)


def _billable_run_length(db: Session, session: AgentSession) -> int:
    """自上次人工决定(或模式开启)以来,这个会话自动放行过几张计费卡。

    起点取两者中较晚的那个:用户批了一张卡就说明他回到了现场,计数该归零。
    """
    since = session.mode_set_at
    last_human = db.scalar(
        select(func.max(ToolConfirmation.resolved_at)).where(
            ToolConfirmation.session_id == session.id,
            ToolConfirmation.decision_mode == "manual",
            ToolConfirmation.resolved_at.is_not(None),
        )
    )
    if last_human is not None and (since is None or last_human > since):
        since = last_human
    stmt = select(func.count()).select_from(ToolConfirmation).where(
        ToolConfirmation.session_id == session.id,
        ToolConfirmation.decision_mode == "auto",
        ToolConfirmation.permission.in_(COST_PERMISSIONS),
    )
    if since is not None:
        stmt = stmt.where(ToolConfirmation.created_at > since)
    return int(db.scalar(stmt) or 0)


def consider(db: Session, user: User, confirmation: ToolConfirmation) -> bool:
    """判定这张新卡,决定放行就派一个线程去执行。返回是否已交给自动放行。

    留痕在**派线程之前**就落库:执行可能失败,但"这张卡是被自动放行的"这件事已经发生了,
    它不该只在执行成功时才留下记录。
    """
    decision = decide(db, user, confirmation)
    confirmation.decision_detail = decision.detail
    if decision.needs_judge:
        # 判断者要跑几秒,不能卡在开卡请求里。压一个期限:待办列表在此之前不显示这张卡,用户不会
        # 看见一张自己出现又自己消失的卡。**这不是一个新状态** —— 期限会自己过去,所以进程崩在
        # 判断中间也不需要谁去回收,卡自己回到待办(与 AuthSession 的过期同一种做法)。
        confirmation.hold_until = now() + timedelta(seconds=judge_module.JUDGE_TIMEOUT_SECONDS)
        db.commit()
        threading.Thread(
            target=_judge_thread,
            args=(confirmation.id, user.id),
            daemon=True,
            name=AUTOPILOT_THREAD_NAME,
        ).start()
        return True
    if not decision.approve:
        db.commit()
        return False
    _hand_off(db, confirmation, decision.mode, user.id)
    return True


def _hand_off(db: Session, confirmation: ToolConfirmation, mode: str, user_id: str) -> None:
    """记下"这张卡是被自动放行的",再派线程去执行。

    留痕落在派活**之前**:执行可能失败,但放行这件事已经发生了,它不该只在执行成功时才留下记录。
    """
    confirmation.decision_mode = mode
    confirmation.decided_by = user_id
    confirmation.hold_until = None
    db.commit()
    threading.Thread(
        target=_execute_thread,
        args=(confirmation.id, user_id),
        daemon=True,
        name=AUTOPILOT_THREAD_NAME,
    ).start()


def _judge_thread(confirmation_id: str, user_id: str) -> None:
    """问一次隔离判断者,按裁决决定放行还是交回用户。

    **任何不是"明确放行"的结果都退回用户**:拒绝、超时、报错、回了个读不懂的东西 —— 判断者不可用
    不等于放行。
    """
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        confirmation = db.get(ToolConfirmation, confirmation_id)
        if confirmation is None or confirmation.status != "pending":
            return
        tool, payload = confirmation.tool, dict(confirmation.payload or {})
        request = judge_module.build_request(tool, payload, _rules_for(db, confirmation))
        detail = dict(confirmation.decision_detail or {})
        # 归属:这一次判断花的钱算在这张卡所在的工作区头上。不传的话 `billable` 只能记一条
        # 归属不明的账,而那一栏存在的意义是告诉用户"你少配了哪条价格规则"。
        workspace_id = confirmation.workspace_id
        try:
            verdict = judge_module.ask(
                request,
                user_id=user_id,
                workspace_id=workspace_id,
                source_type="tool_confirmation",
                source_id=confirmation_id,
            )
        except Exception as exc:  # noqa: BLE001 —— 超时/网络/解析不出来,都算判不了
            logger.warning("judge could not settle confirmation %s: %s", confirmation_id, exc)
            _release(db, confirmation_id, {**detail, "judge_failed": str(exc)[:300]})
            return
        detail["judge"] = {**request.recorded(), "allow": verdict.allow, "reason": verdict.reason, "model": verdict.model}
        confirmation = db.get(ToolConfirmation, confirmation_id)
        if confirmation is None or confirmation.status != "pending":
            return
        confirmation.decision_detail = detail
        if not verdict.allow:
            _release(db, confirmation_id, detail)
            return
        _hand_off(db, confirmation, "auto", user_id)


def _release(db: Session, confirmation_id: str, detail: dict) -> None:
    """把卡交回用户:清掉期限,它立刻出现在待办里。"""
    confirmation = db.get(ToolConfirmation, confirmation_id)
    if confirmation is None or confirmation.status != "pending":
        return
    confirmation.hold_until = None
    confirmation.decision_detail = detail
    db.commit()


def _execute_thread(confirmation_id: str, user_id: str) -> None:
    """在请求线程之外批准并执行。失败一律退回 pending —— 让人来看。

    这里调的是 `authorize_and_approve`,和 HTTP 路由、飞书回调**同一个函数**:自动放行绕过的是
    「用户同意」,不是「他有没有这个权限」。三道授权闸一道不少;挡下来了就当作没有自动放行过。
    """
    from app.core.unit_of_work import unit_of_work
    from app.domain.agent.confirmations import authorize_and_approve

    # 线程就是入口:批准(或退回用户)在这里一起提交。
    with unit_of_work() as db:
        confirmation = db.get(ToolConfirmation, confirmation_id)
        user = db.get(User, user_id)
        if confirmation is None or user is None:
            return
        try:
            authorize_and_approve(db, user, confirmation)
        except Exception as exc:  # noqa: BLE001 —— 含权限不足(403)、并发抢占、执行器炸了
            logger.warning("autopilot could not settle confirmation %s: %s", confirmation_id, exc)
            _fall_back_to_a_human(db, confirmation_id, str(exc))


def _fall_back_to_a_human(db: Session, confirmation_id: str, reason: str) -> None:
    """把卡放回待办。**只在它还没被认领时**动手 —— 抢占失败时它已经是别人的了。"""
    confirmation = db.get(ToolConfirmation, confirmation_id)
    if confirmation is None or confirmation.status != "pending":
        return
    confirmation.decision_mode = "manual"
    confirmation.decided_by = None
    confirmation.decision_detail = {**(confirmation.decision_detail or {}), "autopilot_failed": reason[:300]}


def session_for_token(db: Session, token: str) -> str | None:
    """这份凭据属于哪次对话。归属由凭据决定,不由调用方声明(见 routes/confirmations)。"""
    auth = find_session(db, token)
    return auth.agent_session_id if auth is not None else None


__all__ = [
    "AUTOPILOT_THREAD_NAME",
    "COST_AUTO_LIMIT",
    "Decision",
    "ALLOWANCE_LOCK",
    "SESSION_ALLOWABLE",
    "add_session_allowance",
    "consider",
    "decide",
    "session_allowance",
    "session_for_token",
    "set_session_allowances",
    "wait_for_idle_autopilot",
]


#: 权限模式:manual 每张卡都问人;auto 按规则与判断者放行;bypass 不问就做。
PERMISSION_MODES = ("manual", "auto", "bypass")


class PermissionModeError(LocalizedError, ValueError):
    """不是认得的权限模式 /「始终允许」里不能放的那一条。api 回 422。"""


def set_permission_mode(db: Session, user: User, session: AgentSession, mode: str) -> None:
    """切换这次对话的权限模式。

    - 要 `ai` 权限、要是主人:调用方已经过了写闸(`writable_session`)。它决定的是"智能体能不问就做
      什么",和能不能用智能体是同一件事的两半。
    - **bypass 另要 admin**:它是「不问我就做」——发布、花钱、对外的动作都不再经过一次人眼。
      隔离执行器到位之后,"跑代码"本身已经不是提权(见 domain/sandbox),但**不问就做**仍然是
      一个工作区级别的决定,不是每个 editor 自己能给自己开的。
    - **飞书会话不给 bypass**:那是一个群里所有人共用的对话,而 bypass 不该由一个人替一群人开。
    - 记下**是谁开的**:授权只对做出授权的那个人生效(见 decide)。
    """
    if mode not in PERMISSION_MODES:
        raise PermissionModeError("agentErr_badPermissionMode", modes="/".join(PERMISSION_MODES))
    if mode == "bypass":
        if session.origin != "ui":
            raise PermissionDenied("agentErr_sharedSessionNoBypass")
        ensure_workspace_role(db, user, session.workspace_id, "admin")
    session.permission_mode = mode
    session.mode_set_by = user.id
    session.mode_set_at = now()
