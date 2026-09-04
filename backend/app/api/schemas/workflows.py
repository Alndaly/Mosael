from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.api.schemas.base import OrmModel


class WorkflowCreate(BaseModel):
    workspace_id: str
    name: str = Field(min_length=1, max_length=180)
    description: str = Field(default="", max_length=2000)
    graph: dict | None = None
    template_id: str | None = Field(default=None, max_length=80)


class WorkflowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    description: str | None = Field(default=None, max_length=2000)
    graph: dict | None = None


class WorkflowImportRequest(BaseModel):
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


class WorkflowRunRequest(BaseModel):
    params: dict = Field(default_factory=dict)


class WorkflowNodeTypeOut(BaseModel):
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


class WorkflowAiEditRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=4000)
    graph: dict | None = None
    profile_id: str | None = None


class WorkflowAiEditResponse(BaseModel):
    graph: dict
    summary: str = ""
