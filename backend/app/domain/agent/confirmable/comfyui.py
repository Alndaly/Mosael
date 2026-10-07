"""改 ComfyUI 工作台画布上开着的那一张 —— 这张卡(ADR 0042 拍板 3:先摆出改动清单,点「应用」才改到画布上)。

开卡之前(validate)插件就对着画布上这张算过一遍:每一条都查过、改完不多出错误,卡上的改动清单、子图用了几处、改前改后的
诊断都写进了 payload(见 workbench_agent.propose_edit)。**开卡时画布一点没动。** 批准之后对着现在的画布再算一遍,对得上才
交给桥,整批只占一步撤销(Ctrl+Z 就退回去)。

档位是 `edit`:最坏也撤得回 —— 一次 Ctrl+Z。没有自动放行的口子要它自己开:手动模式下每一张都要人点「应用」,用户自己把对话
设成自动 / 跳过时,和别的 edit 档一样按他的设定走。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.i18n import fragment
from app.domain.agent.confirmable.registry import ConfirmableTool, Summary, confirmable_tool
from app.domain.agent.errors import ConfirmationError


def _user(db: Session, actor: str | None):
    from app.db.models import User

    user = db.get(User, actor) if actor else None
    if user is None:
        raise ConfirmationError("confirmErr_approverNotFound")
    return user


def _validate(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    from app.domain import workbench_agent

    workbench_agent.propose_edit(db, _user(db, actor), workspace_id, payload)


def _summarize(db: Session, payload: dict[str, Any]) -> Summary:
    workflow = payload.get("workflow") if isinstance(payload.get("workflow"), dict) else {}
    #: 改的子图在这张图里用了不止一处:改的是定义,每一处都会变 —— 这半句单独成一条提示(卡上的 warning)
    shared = sorted((one for one in payload.get("subgraphs") or [] if isinstance(one, dict) and int(one.get("uses") or 0) > 1),
                    key=lambda one: -int(one.get("uses") or 0))
    warning = fragment("confirm_comfySubgraphUses", name=str(shared[0].get("name") or ""), uses=int(shared[0].get("uses") or 0)) \
        if shared else ""
    return "confirm_comfyCanvasEdit", {
        "name": str(workflow.get("name") or workflow.get("key") or ""),
        "count": len(payload.get("changes") or []),
        "warning": warning,
    }


def _execute(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    from app.domain import workbench_agent

    # 连接归人:用批准这张卡的那个人的连接、在他的桌面端上改(和读画布同一条路)
    return workbench_agent.apply_edit(db, _user(db, actor), confirmation.workspace_id, dict(confirmation.payload or {}))


def _run_validate(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    """认出 `workflow` 是哪张工作流的工具、入参名都是它认得的,再走**那个工具自己的**开卡校验;卡上记着它的展开名(`tool`)。"""
    from app.domain.agent.confirmable.plugin_tools import validate_call
    from app.domain.agent.workflow_tools import WorkflowToolError, checked_call

    arguments = payload.get("arguments")
    arguments = {} if arguments is None else arguments
    if not isinstance(arguments, dict):
        raise ConfirmationError("confirmErr_pluginToolBadInput", name=str(payload.get("workflow") or ""), detail="arguments")
    try:
        name = checked_call(db, _user(db, actor), str(payload.get("workflow") or ""), arguments,
                            str(payload.get("instance_id") or ""))
    except WorkflowToolError as exc:
        raise ConfirmationError("confirmErr_pluginToolBadInput", name=str(payload.get("workflow") or ""), detail=str(exc)) from exc
    call = {"arguments": arguments}
    validate_call(db, name, workspace_id, call, actor)
    payload.clear()
    payload.update({**call, "tool": name})


def _run_summarize(db: Session, payload: dict[str, Any]) -> Summary:
    from app.domain.agent.confirmable.plugin_tools import summarize_call

    return summarize_call(db, payload)


def _run_escalate(db: Session, tool: str, payload: dict[str, Any]) -> str | None:
    from app.domain.agent.confirmable.plugin_tools import escalate_call

    return escalate_call(db, str(payload.get("tool") or tool), payload)


def _run_needs_card(db: Session, payload: dict[str, Any]) -> bool:
    from app.domain.agent.confirmable.plugin_tools import needs_card_call

    return needs_card_call(db, payload)


def _run_execute(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    from app.domain.agent.confirmable.plugin_tools import run_call

    payload = dict(confirmation.payload or {})
    return run_call(db, str(payload.get("tool") or ""), payload, confirmation.workspace_id, actor)


#: 按工作流跑一张这一轮工具表里没有的工作流(ADR 0044 修订 2026-10-08,见 agent.workflow_tools)。卡上的说明、问人的那一档、
#: 批准之后的执行,和调那个工作流工具自己开的卡同一份;卡以这个名字开 —— 「本会话始终允许」按它记,允许的是经这条路跑的每一张。
confirmable_tool(ConfirmableTool(
    name="comfy_run_workflow",
    permission="edit",
    cost="none",
    summarize=_run_summarize,
    execute=_run_execute,
    validate=_run_validate,
    escalate=_run_escalate,
    needs_card=_run_needs_card,
))


confirmable_tool(ConfirmableTool(
    name="comfy_canvas_edit",
    permission="edit",
    cost="none",
    summarize=_summarize,
    execute=_execute,
    validate=_validate,
))
