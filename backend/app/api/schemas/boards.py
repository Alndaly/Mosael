from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.api.schemas.base import ApiModel, OrmModel
from app.api.schemas.workflows import WorkflowNodeTypeOut


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


class BoardProducerOut(WorkflowNodeTypeOut):
    """画板上的一个产出者:节点描述(和工作流节点面板同一份)+ 画板自己的几样(见 boards.producers.describe)。

    `type` 是节点类型(内置的四个就是它们自己的名字),字段选项接口认它;`id` 是产出者的名字,
    存在一格的 `form.producer` 上、跑的时候发的是它。配置字段里多一样 `board_sources`:
    这个字段能接哪几种上游格子。
    """

    id: str
    #: 能挂在哪几种格子上(画板项的 kind)。
    hosts: list[str]
    permission: str
    #: "none" | "paid" | "external" —— 智能体替人跑时要不要确认卡。
    effects: str
    #: 能不能挑来填一个空槽(一种格子有几个这样的产出者时,面板上给一个切换)。
    fills_empty_slot: bool = False
