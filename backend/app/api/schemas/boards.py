from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.api.schemas.base import ApiModel, OrmModel


class BoardOut(OrmModel):
    id: str
    workspace_id: str
    name: str
    canvas: dict
    revision: int
    created_at: datetime
    updated_at: datetime


class BoardCreate(ApiModel):
    workspace_id: str
    name: str = ""
    canvas: dict | None = None


class BoardDuplicate(ApiModel):
    workspace_id: str
    #: 副本叫什么。「× 副本」是界面语言里的一句话,由前端按当前语言拼好;留空就沿用原名。
    name: str = ""


class BoardUpdate(ApiModel):
    workspace_id: str
    #: 调用方看到的是哪一版。**必填**:一份不带版本的快照存回来,会盖掉服务端在它之后落下的东西
    #: (回执填回的产出、别人的编辑)而不报冲突。
    base_revision: int = Field(ge=1)
    #: 两者都可以单独传 —— 自动保存只发 canvas,重命名只发 name。None = 这次不改它。
    name: str | None = None
    canvas: dict | None = None


class BoardRun(ApiModel):
    """在画板上跑一个产出者(生成、写字、念出来、截一段……),产出落回 `item_id` 那一格。

    `form` 是这个产出者自己的表单,形状由它声明、在领域里校验(见 domain/boards/producers)——
    这里不为每个产出者各开一个请求体。
    """

    workspace_id: str
    #: 调用方看到的是哪一版。在**起任务之前**问:之后才发现冲突的话,钱已经花了。
    base_revision: int = Field(ge=1)
    #: 前端先编好 id —— 占位项和回执要指同一个东西,由前端定名字省掉一次往返。
    item_id: str
    #: 宿主那一格的种类,必须是这个产出者能挂的。
    kind: str
    x: float = 0
    y: float = 0
    producer: str
    form: dict = Field(default_factory=dict)
