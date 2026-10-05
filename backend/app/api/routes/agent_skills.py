"""智能体技能:对话里的「/」菜单(ADR 0040)。

技能是工作区的;`ref` 是模型看到的名字(插件的技能写成 `插件 id:名字`)。看:工作区成员。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, Tx
from app.api.schemas.skills import AgentSkillOut
from app.domain.agent.skills import catalog, use_cases
from app.domain.agent.skills.catalog import Skill

router = APIRouter(tags=["agent-skills"])


def _out(skill: Skill) -> dict:
    return {
        "ref": skill.ref,
        "title": skill.title,
        "description": skill.description,
        "source_label": catalog.source_label(skill),
        "enabled": skill.enabled,
        "problem": skill.problem,
    }


@router.get("/workspaces/{workspace_id}/skills", response_model=list[AgentSkillOut])
def list_skills(workspace_id: str, db: Tx, user: CurrentUser) -> list[dict]:
    """这个工作区看得到的全部技能:内置、我的、来自插件。「/」菜单只摆其中开着、能用的。"""
    return [_out(one) for one in use_cases.list_skills(db, user, workspace_id)]


__all__ = ["router"]
