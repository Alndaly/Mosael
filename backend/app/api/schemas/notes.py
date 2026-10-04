from datetime import datetime
from pydantic import ConfigDict, Field
from app.api.schemas.base import ApiModel
from app.domain.note_types import NoteContent, NoteSource


class NoteCreate(NoteContent):
    workspace_id: str


class NotePageCreate(ApiModel):
    """内嵌浏览器顶栏「存成笔记」:整页(渲染后的 HTML)或选中的文字,二选一,带着页面地址与标题。"""

    workspace_id: str
    project_id: str | None = None
    url: str = Field(min_length=8, max_length=2000, pattern=r"^https?://")
    title: str = Field(default="", max_length=1000)
    #: 渲染后的整页 HTML(Electron 那一侧已剥掉脚本与样式,并截到 4 MB 以内)。
    html: str = Field(default="", max_length=4_000_000)
    selection: str = Field(default="", max_length=200_000)


class NoteUpdate(NoteContent):
    workspace_id: str
    base_revision: int = Field(ge=1)


class NoteOut(NoteContent):
    model_config = ConfigDict(from_attributes=True)
    id: str
    workspace_id: str
    revision: int
    created_at: datetime
    updated_at: datetime


class NoteRestore(ApiModel):
    workspace_id: str
    base_revision: int = Field(ge=1)
    revision: int = Field(ge=1)


class NoteAppend(ApiModel):
    # **没有 base_revision。** 追加到末尾不需要调用方声明它读到的是哪一版 —— 见
    # domain/notes.append_note:拿一个来自列表查询的旧修订号做 CAS,只会把并存的事判成冲突。
    workspace_id: str
    markdown: str = Field(min_length=1, max_length=500000)
    sources: list[NoteSource] = Field(default_factory=list, max_length=200)


class NoteReferenceOut(ApiModel):
    note_id: str
    revision: int
    title: str
    markdown: str
    tags: list[str]
    citation_url: str
