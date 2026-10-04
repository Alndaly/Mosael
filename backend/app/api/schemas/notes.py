from datetime import datetime
from pydantic import ConfigDict, Field
from app.api.schemas.base import ApiModel
from app.domain.note_types import NoteContent, NoteRevisionOrigin, NoteSource


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
    #: 手里那份的保存序号(NoteOut.save_seq);别处刚存过就 409。
    base_save_seq: int = Field(ge=1)


class NoteOut(NoteContent):
    model_config = ConfigDict(from_attributes=True)
    id: str
    workspace_id: str
    #: 当前是第几版(版本号)。
    revision: int
    #: 保存序号:每次写入都 +1,下一次保存带着它(base_save_seq)。
    save_seq: int
    created_at: datetime
    updated_at: datetime


class NoteRevisionOut(ApiModel):
    """版本记录里的一版。连续的手动编辑在存储上就合成了一版(见 domain/notes/history)。"""

    revision: int
    title: str
    #: 这一版最后一次保存的时间;从什么时候开始写的。
    created_at: datetime
    started_at: datetime
    #: 相对上一版:新加 / 删掉的字数(不算空白)、标题改没改。
    chars_added: int
    chars_removed: int
    title_changed: bool
    origin: NoteRevisionOrigin
    #: 替谁写的(用户 id);老数据说不出是谁时为空。
    created_by: str | None
    created_by_name: str = ""
    #: origin 是 restore 时:从第几版恢复的。
    restored_from: int | None


class NoteRestore(ApiModel):
    workspace_id: str
    base_save_seq: int = Field(ge=1)
    #: 恢复哪一版(版本号)。
    revision: int = Field(ge=1)


class NoteAppend(ApiModel):
    # **没有 base_save_seq。** 追加到末尾不需要调用方声明它读到的是哪一份 —— 见
    # domain/notes.append_note:拿一个来自列表查询的旧保存序号做 CAS,只会把并存的事判成冲突。
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
