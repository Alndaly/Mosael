"""在用户的 Blender 里跑建模代码 —— 这张卡。

和「本机执行代码」分开是有理由的:一轮建模几十步,放开它是建模时的常态;而放开它不该连带
放开「在电脑上随便跑代码」。所以它自成一档(`gate="blender"`),档位由这张卡自己声明,
权限领域不认识 Blender 是什么(见 confirmable/registry 与 agent/rules)。

它仍然是 `external`:Blender 的 Python 能读写本机文件、能起进程,不是沙箱。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.i18n import fragment
from app.domain.agent.confirmable.registry import ConfirmableTool, Summary, confirmable_tool
from app.domain.agent.errors import ConfirmationError


def _validate_blender_execute(db: Session, workspace_id: str, payload: dict[str, Any]) -> None:
    from app.core.config import settings

    if not settings.local_desktop:
        raise ConfirmationError("Blender 建模只在本机桌面版可用 —— Blender 要和 Mosael 跑在同一台电脑上。")
    if not str(payload.get("code") or "").strip():
        raise ConfirmationError("没有要在 Blender 里执行的代码")

def _summarize_blender_execute(db: Session, payload: dict[str, Any]) -> Summary:
    code = str(payload.get("code") or "")
    purpose = str(payload.get("purpose") or "").strip()[:80]
    return "confirm_blenderExecute", {
        "lines": len(code.strip().splitlines()),
        "purpose": fragment("confirm_blenderPurpose", purpose=purpose) if purpose else "",
    }

def _execute_blender_execute(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    from app.db.models import User
    from app.domain.blender import agent as blender_agent

    # 连接归人:用批准这张卡的那个人的 Blender。自动放行时 actor 是开模式的人(见 autopilot)。
    user = db.get(User, actor) if actor else None
    if user is None:
        raise ValueError("找不到批准这次操作的用户")
    payload = confirmation.payload
    result = blender_agent.execute(db, user, confirmation.workspace_id, str(payload.get("code") or ""),
                                   str(payload.get("instance_id") or ""))
    if result.get("error"):
        # 代码自己的错:把 traceback 交回去,模型据此改了再试。traceback 在 worker 那边已按层数
        # 收过(limit=6),这里不再按位置裁 —— 裁掉的往往正是写着错因的最后一行。
        raise ValueError(f"Blender 里的代码出错了:\n{result['error']}")
    return result


confirmable_tool(ConfirmableTool(
    name="blender_execute",
    permission="external",
    cost="none",
    gate="blender",
    gate_label="Blender 建模",
    summarize=_summarize_blender_execute,
    execute=_execute_blender_execute,
    validate=_validate_blender_execute,
))
