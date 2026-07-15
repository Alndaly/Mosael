from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DbSession
from app.api.schemas import AgentManifestOut, AgentSkillOut
from app.domain.agent import list_agent_skills

router = APIRouter(tags=["agent"])


@router.get("/agent/skills", response_model=list[AgentSkillOut])
def get_agent_skills(db: DbSession) -> list[dict]:
    return list_agent_skills(db)


@router.get("/agent/manifest", response_model=AgentManifestOut)
def get_agent_manifest(db: DbSession) -> AgentManifestOut:
    return AgentManifestOut(
        app="mibu-new",
        version="0.1.0",
        openapi_url="/openapi.json",
        skills=[AgentSkillOut.model_validate(skill) for skill in list_agent_skills(db)],
    )
