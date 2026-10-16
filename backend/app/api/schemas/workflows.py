from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.api.schemas.base import ApiModel, OrmModel
from app.api.schemas.plugins import EntryGroupOut
from app.domain.workflows.templates import TEMPLATE_CATALOG

#: 官方模板的 id:由模板目录说了算,生成的前端类型因此是一个确切的联合。此前前端手抄了一份(3 个,实际 11 个),
#: 拿 `as` 断言盖住了对不上。
WorkflowTemplateId = Literal[tuple(template["id"] for template in TEMPLATE_CATALOG)]  # type: ignore[valid-type]


class WorkflowCreate(ApiModel):
    workspace_id: str
    name: str = Field(min_length=1, max_length=180)
    description: str = Field(default="", max_length=2000)
    graph: dict | None = None
    template_id: str | None = Field(default=None, max_length=80)


class WorkflowFromPage(ApiModel):
    """内嵌浏览器顶栏「用当前页开工」:哪张分析模板、当前页的链接、当前视图对应的浏览器档案(没有就空着)。"""

    workspace_id: str
    template_id: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=8, max_length=2000, pattern=r"^https?://")
    profile_id: str | None = Field(default=None, max_length=64)


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
    """运行一次工作流。`target_node_id` 给定时是「单跑一个节点」:只执行目标及其上游依赖闭包,
    到目标即停,下游不跑(运行历史据此标注「部分运行」);目标在循环体/子图里会被拒。"""

    params: dict = Field(default_factory=dict)
    target_node_id: str | None = Field(default=None, max_length=120)


class WorkflowRunOutputOut(ApiModel):
    """一次运行里某个节点某个输出的全文(事件快照里截断了的那一段)。"""

    value: str


class RunApprovalOut(OrmModel):
    """一次运行停在「等人确认」上的那一步 —— 应用内批它的那一格(见 routes/workflows)。

    **和 `TaskAwaitingApprovalOut` 不是一件事**:那一条是定时任务「这一版要主人认可」(只提醒、
    不拦、没有单子);这一条是一次真的停下来的运行,批了就接着跑。
    """

    id: str
    job_id: str
    workflow_id: str
    node_id: str
    node_name: str
    title: str
    body: str
    #: 按钮文案:节点上写的;空着时界面按语言给缺省的「确认 / 拒绝」。
    approve_label: str
    reject_label: str
    allow_note: bool
    status: str
    #: 决定那一格:approved / rejected / timeout(空 = 还没决定)。界面拿它写回执那半句。
    decision: str
    #: 这一次等待**发到飞书没有**:sent / failed / not_attempted(空 = 那一版之前建的,没有投递记录)。
    #: 界面照它说「已发到飞书 / 仅站内(原因) / 发飞书失败(原因)」—— 「在飞书里点那张卡也一样」
    #: 这句话只有在**真发出去过**时才成立。
    feishu_delivery: str
    #: 为什么是这个结果:not_attempted 是路由那一档(none / no-bot / no-origin / not-bound / no-target),
    #: failed 是发出去时撞上的那一句。界面拿它把"发不出去"说得具体一点。
    feishu_delivery_reason: str
    #: 什么时候算超时(空 = 一直等)。
    expires_at: datetime | None
    created_at: datetime


class RunApprovalDecisionIn(ApiModel):
    """应用内点的那一下。**和飞书卡片走同一条决定路径**(见 domain/workflows/approvals.decide_and_wake)。"""

    decision: Literal["approved", "rejected"]
    note: str = Field(default="", max_length=2000)


class WorkflowFieldOptionOut(ApiModel):
    """节点字段的一个动态选项。"""

    value: str
    label: str


class WorkflowUnusableNodeOut(ApiModel):
    """图里一个**这个人**用不了的插件节点类型,和为什么(插件没装、没接连接、连接停用 / 缺凭据、工具没勾选……)。"""

    type: str
    reason: str
    #: 修法是到 `instance_id` 那个连接自己的库里升级(ComfyUI:那张工作流的表单还是上一版格式,工作流库里「查看并升级」)
    upgrade: bool = False
    instance_id: str = ""


class WorkflowNodeTypeOut(ApiModel):
    type: str
    label: str
    description: str
    category: str = ""  # 面板分组;空=通用组
    config: dict
    outputs: list[str]
    #: 配置里的动态映射如何展开为属性端口:配置字段 → {input/output: 运行时路径前缀}。
    port_maps: dict[str, dict[str, str]] = Field(default_factory=dict)
    output_types: dict[str, str] = Field(default_factory=dict)
    output_labels: dict[str, str] = Field(default_factory=dict)
    #: 插件节点带来源插件名(内置节点为空)。面板据此在同名工具之间区分是谁提供的。
    plugin_name: str = ""
    #: 插件工具的稳定调用名。只参与搜索/诊断，不拿它顶替给人看的 label。
    tool_name: str = ""
    #: 插件工具是哪样东西的哪个入口(ADR 0045,ComfyUI 一张工作流的完整工作流和它的表单):添加节点、画布上的节点据此写
    #: 第二行「来自 X」/「完整工作流」,同一组的挨着摆。内置节点和不分组的插件工具是 null。
    group: EntryGroupOut | None = None
    #: 内嵌子图节点(循环 / 子图)体内看得见什么:作用域名 → 字段,`*字段名` 表示那个配置字段里的
    #: 每个键。如 {"loop": ["item", "index"], "input": ["*inputs"]};普通节点为空。
    body_scope: dict[str, list[str]] = Field(default_factory=dict)
    #: 输出 → 写着它结构的那一格配置(一份 JSON Schema),如大模型的 {"json": "json_schema"}。
    #: 引用这个输出的地方据此列出 `{{节点.输出.字段}}` 让人挑;普通节点为空。
    output_schema_from: dict[str, str] = Field(default_factory=dict)


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
    #: 几选一的组名(分析类模板的数据来源:TikHub 或内嵌浏览器)。同组有一条齐了这一组就齐;空 = 不在组里。
    group: str = ""


class WorkflowTemplateCheckOut(ApiModel):
    """一个检查键此刻的状态。**按人、按工作区**,所以和模板目录分开拉 —— 目录能缓存,状态不能。"""

    check: str
    #: met = 齐了;missing = 没有;unknown = 本地引擎还在后台探测,**不拿未知冒充结论**。
    status: Literal["met", "missing", "unknown"]


class WorkflowTemplateOut(ApiModel):
    """官方模板的说明。文案已按请求方的语言选好(见 domain/workflows/templates.TEMPLATE_CATALOG);
    图标由界面按 id 给,和节点图标、任务种类同一条规矩。"""

    id: WorkflowTemplateId
    name: str
    description: str
    #: 现行第几版(图上的 meta.template_version)。编辑器拿它和图上的比:从旧版建出来的图在顶上提示按新版重建。
    version: int
    #: 这条流程分几步 —— 卡片上那条竖线。
    stages: list[str] = Field(default_factory=list)
    #: 跑之前要备好什么(模型、引擎、素材)。每条带一个检查键,状态另走 /workflows/templates/checks。
    requirements: list[WorkflowTemplateRequirementOut] = Field(default_factory=list)
