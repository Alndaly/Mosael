from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.api.schemas.base import OrmModel
from app.api.schemas.generation import SourceAssetRef


class BoardOut(OrmModel):
    id: str
    workspace_id: str
    name: str
    canvas: dict
    revision: int
    created_at: datetime
    updated_at: datetime


class BoardCreate(BaseModel):
    workspace_id: str
    name: str = ""
    canvas: dict | None = None


class BoardUpdate(BaseModel):
    workspace_id: str
    #: New clients always send this. Optional only keeps pre-revision desktop clients able to save
    #: during a rolling upgrade; conflict detection is active whenever the token is present.
    base_revision: int | None = Field(default=None, ge=1)
    #: 两者都可以单独传 —— 自动保存只发 canvas,重命名只发 name。None = 这次不改它。
    name: str | None = None
    canvas: dict | None = None


class BoardGenerate(BaseModel):
    workspace_id: str
    base_revision: int | None = Field(default=None, ge=1)
    #: 前端先编好 id —— 占位项和回执要指同一个东西,由前端定名字省掉一次往返。
    item_id: str
    kind: str = "image"
    prompt: str
    x: float = 0
    y: float = 0
    provider: str = ""
    model: str = ""
    parameters: dict = Field(default_factory=dict)
    source_assets: list[SourceAssetRef] = Field(default_factory=list)
    #: 用户可再次编辑的原始表单，不含调用供应商时临时追加的提示词。
    form: dict = Field(default_factory=dict)


class BoardWrite(BaseModel):
    """让 AI 同步写入一张画板便签。"""

    workspace_id: str
    base_revision: int | None = Field(default=None, ge=1)
    item_id: str
    prompt: str
    provider_profile_id: str = ""
    model: str = ""
    source_assets: list[str] = Field(default_factory=list)
    context: list[str] = Field(default_factory=list)


class BoardSpeak(BaseModel):
    """把文字异步合成为音频并落回画板占位。"""

    workspace_id: str
    base_revision: int | None = Field(default=None, ge=1)
    item_id: str
    text: str
    voice_id: str = ""
    x: float = 0
    y: float = 0


class BoardTrim(BaseModel):
    """截取视频或音频并把新素材落回画板；原素材不变。"""

    workspace_id: str
    base_revision: int | None = Field(default=None, ge=1)
    item_id: str
    asset_id: str
    start: float = 0
    end: float
    mute: bool = False
    x: float = 0
    y: float = 0
