"""转写:整篇、句、词三层的出入参,以及把一份转写挂到素材上。"""

from __future__ import annotations

from pydantic import Field
from app.api.schemas.base import ApiModel, OrmModel

class TranscriptTokenIn(ApiModel):
    start_time: float
    end_time: float
    text: str = Field(max_length=120)


class TranscriptSegmentIn(ApiModel):
    start_time: float
    end_time: float
    text: str
    speaker: str | None = None
    tokens: list[TranscriptTokenIn] = Field(default_factory=list)


class TranscriptAttachRequest(ApiModel):
    language: str = Field(default="", max_length=24)
    source: str = Field(default="imported", max_length=40)
    segments: list[TranscriptSegmentIn] = Field(default_factory=list)


class TranscriptTokenOut(OrmModel):
    id: str
    token_index: int
    start_time: float
    end_time: float
    text: str


class TranscriptSegmentOut(OrmModel):
    id: str
    start_time: float
    end_time: float
    text: str
    speaker: str | None
    tokens: list[TranscriptTokenOut] = Field(default_factory=list)


class TranscriptOut(OrmModel):
    id: str
    workspace_id: str
    asset_id: str
    language: str
    status: str
    source: str
    segments: list[TranscriptSegmentOut] = Field(default_factory=list)
