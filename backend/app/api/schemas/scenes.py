from datetime import datetime
from pydantic import Field
from app.api.schemas.base import ApiModel, OrmModel
from app.domain.scene_types import SceneContent


class SceneCreate(ApiModel):
    workspace_id: str
    name: str = Field("Untitled scene", max_length=160)
    content: SceneContent = Field(default_factory=SceneContent)


class SceneUpdate(SceneCreate):
    base_revision: int = Field(ge=1)


class SceneOut(OrmModel):
    id: str
    workspace_id: str
    name: str
    content: SceneContent
    revision: int
    created_at: datetime
    updated_at: datetime


class SceneOperations(ApiModel):
    workspace_id: str
    base_revision: int = Field(ge=1)
    name: str | None = Field(None, max_length=160)
    objects: list[dict] = Field(default_factory=list, max_length=100)
    remove_ids: list[str] = Field(default_factory=list, max_length=100)
    shots: list[dict] | None = Field(None, min_length=1, max_length=32)
