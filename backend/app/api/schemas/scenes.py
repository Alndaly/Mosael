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


class SceneReferenceRequest(ApiModel):
    """从一个镜头渲白模参考(见 domain/scenes.render_shot_references)。"""

    workspace_id: str
    #: 取值见 domain/scenes.REFERENCE_RENDERS —— 由领域函数校验,这里不再抄一份清单。
    render: str = "stills"
    project_id: str | None = None


class SceneReferenceOut(ApiModel):
    first_frame_asset_id: str
    last_frame_asset_id: str
    video_asset_id: str
    #: 从机位轨迹算出来的镜头语言(英文),可以直接拼进生成提示词。
    camera_move: str
    skipped_models: int
