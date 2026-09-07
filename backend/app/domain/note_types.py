"""Validated note content shared by persistence and API adapters."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError


class NoteSource(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    kind: Literal["asset", "message", "board", "note", "url"]
    id: str = Field(default="", max_length=64)
    label: str = Field(default="", max_length=240)
    quote: str = Field(default="", max_length=50000)
    start: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    end: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    url: str = Field(default="", max_length=2000)
    revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def valid_range(self):
        if self.end is not None and (self.start is None or self.end <= self.start):
            raise PydanticCustomError("note_range", "结束时间必须晚于开始时间")
        if self.kind == "url":
            from urllib.parse import urlsplit
            try:
                parsed = urlsplit(self.url)
            except ValueError as exc:
                raise PydanticCustomError("note_url", "来源链接必须是有效网址") from exc
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                raise PydanticCustomError("note_url", "来源链接必须是 http 或 https 地址")
        elif not self.id:
            raise PydanticCustomError("note_source", "来源 ID 不能为空")
        return self


class NoteContent(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    title: str = Field(default="", max_length=240)
    markdown: str = Field(default="", max_length=500000)
    project_id: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=32)
    topics: list[str] = Field(default_factory=list, max_length=32)
    sources: list[NoteSource] = Field(default_factory=list, max_length=200)
    favorite: bool = False
    trashed: bool = False
