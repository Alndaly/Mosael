"""生成:输入素材的引用、模型与参数选项、发起生成、会话与提示词优化。"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.api.schemas.base import ApiModel, OrmModel
from app.api.schemas.jobs import JobOut
from app.ai.providers.contracts.generation import FIRST_FRAME, SOURCE_ROLES


"""生成:输入素材的引用、模型与参数选项、发起生成、会话与提示词优化。"""






class SourceAssetRef(ApiModel):
    """一份输入素材及其在生成请求中的用途。"""

    asset_id: str = Field(min_length=1, max_length=64)
    # 角色值由 provider contract 生成，避免 schema 与 adapter 能力表各维护一份。
    role: str = Field(default=FIRST_FRAME, pattern=f"^({'|'.join(SOURCE_ROLES)})$")


class GenerationOptionOut(ApiModel):
    """一个「用哪条连接的哪个模型来生成」的选项。

    **后端做联接**:以前这份列表由前端拿三张表(生成目录 / 启用的档案 / 能力默认)现拼,
    任何一份口径变一点就和设置页对不上。现在只有一条线 —— 有哪些模型看 provider_models。
    """

    id: str
    provider_profile_id: str
    profile_name: str
    provider: str
    kind: str
    model: str
    label: str
    capabilities: dict = Field(default_factory=dict)
    #: 这个 vendor+kind 有没有接入的生成 Adapter。不可用的照样列出但标出来 ——
    #: 藏起来的话用户配好了却找不到,只会以为是自己配错了。
    adapter_available: bool = False
    #: 上面那份 capabilities 是**认出来的**,还是落到了兜底(什么参数都不声明)。
    #: 界面据此分开两种零:「这个模型确实没有可调参数」和「我们不认识这个模型」——
    #: 合成一个的后果是后者静默地什么都不显示,看起来就像前者。
    capabilities_known: bool = True


class GenerationModelOut(OrmModel):
    id: str
    provider: str
    kind: str
    model: str
    enabled: bool
    capabilities: dict
    adapter_available: bool


class GenerationCreate(ApiModel):
    workspace_id: str
    session_id: str | None = None
    project_id: str | None = None
    provider_profile_id: str | None = None
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=120)
    kind: str = Field(pattern="^(image|video)$")
    prompt: str = Field(min_length=1)
    negative_prompt: str = Field(default="", max_length=4000)
    parameters: dict = Field(default_factory=dict)
    source_assets: list[SourceAssetRef] = Field(default_factory=list)


class GenerationJobOut(OrmModel):
    id: str
    workspace_id: str
    session_id: str | None = None
    # 任务中心清理已完成 job 后置空(记录本身长存,状态由 result_asset_id 兜底)。
    job_id: str | None = None
    provider_profile_id: str | None = None
    provider: str
    model: str
    kind: str
    request: dict
    result_asset_id: str | None
    #: **全部产出。** 一次生成可能出多份(图像接口的 n),而 result_asset_id 只放得下封面 ——
    #: 界面照这一串出图,不然用户选了 4 张、只看得见 1 张(另外 3 张确实在素材库里,他不知道)。
    #: 封面排在第一。由路由从 generated_assets 贴上来。
    result_asset_ids: list[str] = []
    created_at: datetime
    updated_at: datetime
    # 计费:取自本次生成记录的用量事件(source_type=generation_job)。cost_micros 为已知估算费用;
    # 有事件但无定价规则时 cost_confidence=unknown、cost_micros 为空(前端显示「未定价」)。
    cost_micros: int | None = None
    currency: str | None = None
    cost_confidence: str | None = None


class GenerationCreateResponse(ApiModel):
    generation: GenerationJobOut
    job: JobOut


class PromptOptimizeRequest(ApiModel):
    workspace_id: str
    #: 目标图像平台(provider/model)——只用来选平台提示词习惯,不是重写用的 LLM。
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1)
    #: 重写用的聊天 LLM 供应商配置;缺省用默认启用的那个(与助手/工作流同一个)。
    provider_profile_id: str | None = None
    language: str = Field(default="zh", max_length=10)


class PromptOptimizeResponse(ApiModel):
    prompt: str
    negative_prompt: str = ""
    notes: str = ""
    platform: str = ""


class GenerationSessionCreate(ApiModel):
    workspace_id: str
    title: str = Field(default="新生成", max_length=200)
    provider_profile_id: str | None = None
    model: str | None = Field(default=None, max_length=120)
    kind: str | None = Field(default=None, pattern="^(image|video)$")


class GenerationSessionUpdate(ApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    #: 收进哪个分组;空串或 null 表示退回未分组。
    group_id: str | None = None
    provider_profile_id: str | None = None
    model: str | None = Field(default=None, max_length=120)
    kind: str | None = Field(default=None, pattern="^(image|video)$")


class GenerationSessionOut(OrmModel):
    id: str
    workspace_id: str
    # 归属(见 domain/sharing):生成记录和对话一样,默认只有自己看得见。
    owner_user_id: str | None = None
    is_mine: bool = True
    shared: bool = False
    title: str
    group_id: str | None = None
    provider_profile_id: str | None = None
    model: str | None = None
    kind: str | None = None
    created_at: datetime
    updated_at: datetime
