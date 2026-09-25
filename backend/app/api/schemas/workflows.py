from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.api.schemas.base import ApiModel, OrmModel


class WorkflowCreate(ApiModel):
    workspace_id: str
    name: str = Field(min_length=1, max_length=180)
    description: str = Field(default="", max_length=2000)
    graph: dict | None = None
    template_id: str | None = Field(default=None, max_length=80)


class WorkflowUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    description: str | None = Field(default=None, max_length=2000)
    graph: dict | None = None
    #: 这份图是在哪一份上改出来的(读到时的 `graph_hash`)。存整份图必须带:库里那份在这期间
    #: 被别处改过就撞 409,而不是把别人的写入静默盖掉。只改名/描述时不需要。
    base_graph_hash: str | None = Field(default=None, min_length=64, max_length=64)


class WorkflowImportRequest(ApiModel):
    """导入工作流:data 是导出文件的完整 JSON(format/version/name/graph 信封)。"""

    workspace_id: str
    data: dict


class WorkflowOut(OrmModel):
    id: str
    workspace_id: str
    name: str
    description: str
    graph: dict
    revision: int
    graph_hash: str
    created_at: datetime
    updated_at: datetime


class WorkflowRevisionOut(OrmModel):
    id: str
    workflow_id: str
    revision: int
    graph_hash: str
    source: str
    note: str
    #: 这一版的作者。一次运行用私有账号 / 档案 / 本机文件时,作者或认可过这一版的人得用得了
    #: (见 domain/authority)。
    created_by: str | None
    created_by_name: str = ""
    #: 事后「认可这一版」的人(用户 id),不含作者。
    attested_by: list[str] = Field(default_factory=list)
    created_at: datetime


class WorkflowRevisionDetailOut(WorkflowRevisionOut):
    graph: dict


class WorkflowRunRequest(ApiModel):
    params: dict = Field(default_factory=dict)


class WorkflowFieldOptionOut(ApiModel):
    """节点字段的一个动态选项。"""

    value: str
    label: str


class WorkflowNodeTypeOut(ApiModel):
    type: str
    label: str
    description: str
    category: str = ""  # 面板分组;空=通用组
    config: dict
    outputs: list[str]
    output_types: dict[str, str] = Field(default_factory=dict)
    output_labels: dict[str, str] = Field(default_factory=dict)
    #: 插件节点带来源插件名(内置节点为空)。面板据此在同名工具之间区分是谁提供的。
    plugin_name: str = ""
    #: 插件工具的稳定调用名。只参与搜索/诊断，不拿它顶替给人看的 label。
    tool_name: str = ""
    #: 内嵌子图节点(循环 / 子图)体内看得见什么:作用域名 → 字段,`*字段名` 表示那个配置字段里的
    #: 每个键。如 {"loop": ["item", "index"], "input": ["*inputs"]};普通节点为空。
    body_scope: dict[str, list[str]] = Field(default_factory=dict)


class WorkflowAiEditRequest(ApiModel):
    instruction: str = Field(min_length=1, max_length=4000)
    graph: dict | None = None
    profile_id: str | None = None


class WorkflowAiEditResponse(ApiModel):
    graph: dict
    summary: str = ""


class WorkflowTemplateRequirementOut(ApiModel):
    """模板的一条前置条件(见 domain/workflows/template_requirements)。"""

    text: str
    #: 能自动查的那几样之一(chat_model / reference_image_model / …);空 = 运行时由用户给的素材,查不了。
    check: str = ""
    #: 缺了也能跑(旁白之类)。界面把「缺」说成「可选」,不报警。
    optional: bool = False


class WorkflowTemplateCheckOut(ApiModel):
    """一个检查键此刻的状态。**按人、按工作区**,所以和模板目录分开拉 —— 目录能缓存,状态不能。"""

    check: str
    #: met = 齐了;missing = 没有;unknown = 本地引擎还在后台探测,**不拿未知冒充结论**。
    status: Literal["met", "missing", "unknown"]


class WorkflowTemplateOut(ApiModel):
    """官方模板的说明。文案已按请求方的语言选好(见 domain/workflows/templates.TEMPLATE_CATALOG);
    图标由界面按 id 给,和节点图标、任务种类同一条规矩。"""

    id: str
    name: str
    description: str
    #: 这条流程分几步 —— 卡片上那条竖线。
    stages: list[str] = Field(default_factory=list)
    #: 跑之前要备好什么(模型、引擎、素材)。每条带一个检查键,状态另走 /workflows/templates/checks。
    requirements: list[WorkflowTemplateRequirementOut] = Field(default_factory=list)
