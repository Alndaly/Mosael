from __future__ import annotations

from datetime import datetime

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
    created_by: str | None
    created_at: datetime


class WorkflowRevisionDetailOut(WorkflowRevisionOut):
    graph: dict


class WorkflowRunRequest(ApiModel):
    params: dict = Field(default_factory=dict)


class WorkflowNodeTypeOut(ApiModel):
    type: str
    label: str
    description: str
    category: str = ""  # 面板分组;空=通用组
    config: dict
    #: 「这几个字段里至少要填一个」。per-field 的 required 表达不了二选一(语音合成的
    #: 克隆音色 / 引擎音色就是),而不表达的话就绪度检查漏掉的正是"一个都没选"。
    required_one_of: list[list[str]] = Field(default_factory=list)
    outputs: list[str]
    output_types: dict[str, str] = Field(default_factory=dict)
    output_labels: dict[str, str] = Field(default_factory=dict)
    #: 插件节点带来源插件名(内置节点为空)。面板据此在同名工具之间区分是谁提供的。
    plugin_name: str = ""
    #: 插件工具的稳定调用名。只参与搜索/诊断，不拿它顶替给人看的 label。
    tool_name: str = ""


class WorkflowAiEditRequest(ApiModel):
    instruction: str = Field(min_length=1, max_length=4000)
    graph: dict | None = None
    profile_id: str | None = None


class WorkflowAiEditResponse(ApiModel):
    graph: dict
    summary: str = ""
