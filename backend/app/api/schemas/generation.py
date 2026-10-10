"""生成:输入素材的引用、模型与参数选项、发起生成、会话与提示词优化。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, ValidationInfo, computed_field, field_validator

from app.api.schemas.base import ApiModel, CostAmountOut, OrmModel
from app.api.schemas.failures import FailureReadout
from app.api.schemas.jobs import JobOut, _rendered
from app.api.schemas.plugins import EntryGroupOut
from app.ai.providers.contracts.generation import FIRST_FRAME, SOURCE_ROLES
from app.domain.jobs import CANCELLED_ERROR_KEY


"""生成:输入素材的引用、模型与参数选项、发起生成、会话与提示词优化。"""






class SourceAssetRef(ApiModel):
    """一份输入素材及其在生成请求中的用途。"""

    asset_id: str = Field(min_length=1, max_length=64)
    # 角色值由 provider contract 生成，避免 schema 与 adapter 能力表各维护一份。
    role: str = Field(default=FIRST_FRAME, pattern=f"^({'|'.join(SOURCE_ROLES)})$")


class GenerationMissingOut(ApiModel):
    """一个记着的生成模型(会话、画板格子、工作流节点存着的)现在不在生成选项里:叫什么、为什么、怎么修(ADR 0045 修订之一)。
    名字和生成选项同几格(`model_label`、`profile_name`、`group`),界面照样摆成两层;给人看的字按看的人的语言挑好。"""

    provider_profile_id: str
    model: str
    #: 主名:插件说的(ComfyUI「krea2-text-2-image 的表单」)、模型行的显示名,或者说不上来时的「之前选的模型」
    model_label: str
    #: 连接名;连接已经删了是空串
    profile_name: str
    #: 来自哪样东西(ComfyUI:哪张工作流);不属于哪一组是 null
    group: EntryGroupOut | None = None
    #: 为什么、该去哪
    reason: str
    #: 修法是到插件自己的库里升级(ComfyUI:工作流库的「查看并升级」)
    upgrade: bool = False
    #: 是插件连接时,它是哪个插件实例(「去工作流库升级」开的是这个连接的工作流库);不是是空串
    plugin_instance_id: str = ""


class GenerationOptionOut(ApiModel):
    """一个「用哪条连接的哪个模型来生成」的选项。

    **后端做联接**:以前这份列表由前端拿三张表(生成目录 / 启用的档案 / 能力默认)现拼,
    任何一份口径变一点就和设置页对不上。现在只有一条线 —— 有哪些模型看 provider_models。
    """

    id: str
    provider_profile_id: str
    #: 这条连接是插件连接时,它是哪个插件实例(空串 = 不是插件连接)。表单拿它去那个连接的模型库取
    #: 选模型文件那一格的缩略图、底模和触发词(参数上的 `x-model-folder`)。
    plugin_instance_id: str = ""
    profile_name: str
    provider: str
    kind: str
    model: str
    #: 给人看的模型名(主名:显示名,没有就是 id)。下拉里写这个,`model` 只是 id。**没有拼好的「连接名 · 模型名」**
    #: (ADR 0045):两层名字由界面拿 `model_label`、`group`、`profile_name` 摆,拼进一个字符串之后只能拆。
    model_label: str
    #: 哪样东西的哪个入口;不属于哪一组是 null。副名(「来自 X · 连接名」)由界面拿它和 `profile_name` 摆。
    group: EntryGroupOut | None = None
    capabilities: dict = Field(default_factory=dict)
    #: 这个 vendor+kind 有没有接入的生成 Adapter。不可用的照样列出但标出来 ——
    #: 藏起来的话用户配好了却找不到,只会以为是自己配错了。
    adapter_available: bool = False
    #: 上面那份 capabilities 是**认出来的**,还是落到了兜底(什么参数都不声明)。
    #: 界面据此分开两种零:「这个模型确实没有可调参数」和「我们不认识这个模型」——
    #: 合成一个的后果是后者静默地什么都不显示,看起来就像前者。
    capabilities_known: bool = True
    #: 这是不是**这个人**在这种生成上设的默认模型。选择器据此预选;一项都没标 = 他没设,
    #: 选择器显示「选择模型」让他选,而不是拿第一项顶上。
    is_default: bool = False


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
    model: str = Field(min_length=1, max_length=160)
    kind: str = Field(pattern="^(image|video|audio)$")
    #: 可以为空:音频只给歌词、给视频配声什么字都不给都是合法的。「图像 / 视频要提示词」这类按种类、
    #: 按模型的规矩在提交校验里判(operations.validate_text_inputs),同样回 422。
    prompt: str = ""
    negative_prompt: str = Field(default="", max_length=4000)
    parameters: dict = Field(default_factory=dict)
    source_assets: list[SourceAssetRef] = Field(default_factory=list)
    #: 这次 `@` 到的资产(ADR 0027):提示词描述拼进提示词,参考图按模型收得下的张数挂上。
    #: 挂了哪几张、哪几张没挂上,回在 `request.entities` 里。
    entity_ids: list[str] = Field(default_factory=list, max_length=8)
    #: 数字人(带驱动音频的说话照片、对口型)必须勾上「已取得画面中人物的授权」,否则 422(ADR 0028 §5)。
    digital_human_consent: bool = False


class SpeechCreate(ApiModel):
    """创作页「语音」(ADR 0055):念一段字。音色一格和工作流、画板、智能体同一个口径 —— 克隆引擎是配音库里的嗓子 id,别的引擎是
    它自己的音色(能复刻的引擎点配音库里的嗓子时也是嗓子 id)。"""

    workspace_id: str
    session_id: str | None = None
    project_id: str | None = None
    text: str = Field(min_length=1, max_length=2000)
    engine: str = Field(min_length=1, max_length=80)
    voice: str = Field(min_length=1, max_length=120)
    #: 界面那份目录里的名字(火山按账号现拉的音色只有界面知道名字):记录、产出的素材名用它。没给就由后端查。
    voice_label: str = Field(default="", max_length=120)
    engine_label: str = Field(default="", max_length=120)
    #: 火山:音色的资源族(只有目录知道)。
    engine_voice_resource: str = Field(default="", max_length=60)
    provider_profile_id: str | None = None
    engine_model: str = Field(default="", max_length=120)
    #: 本机克隆这一次用哪个引擎、哪份权重(空 = 部署配置里的默认)。
    clone_engine: str = Field(default="", max_length=40)
    clone_model: str = Field(default="", max_length=40)
    speed: float = Field(default=1.0, ge=0.25, le=3.0)


class PodcastTurnIn(ApiModel):
    """照稿念的一段:`speaker` 是 `speakers` 里的第几位。"""

    speaker: int = Field(ge=0, le=1)
    text: str = Field(min_length=1, max_length=280)


class PodcastSpeakerIn(ApiModel):
    value: str = Field(min_length=1, max_length=120)
    label: str = Field(default="", max_length=120)


class PodcastCreate(ApiModel):
    """创作页「播客」(ADR 0055 §6):改写材料(`text` 是材料)、聊一个主题(`text` 是主题)、照稿念(`turns`)。"""

    workspace_id: str
    session_id: str | None = None
    project_id: str | None = None
    provider_profile_id: str | None = None
    mode: str = Field(pattern="^(summarize|read|research)$")
    text: str = Field(default="", max_length=20000)
    turns: list[PodcastTurnIn] = Field(default_factory=list, max_length=60)
    speakers: list[PodcastSpeakerIn] = Field(default_factory=list, max_length=2)
    speed: float = Field(default=1.0, ge=0.25, le=3.0)


class GenerationJobOut(FailureReadout, OrmModel):
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
    #: 产出那份素材被删了的时间;None = 还在(或这条本来就没交回产出)。界面据此说「这份产出已被删除」,
    #: 而不是把「没结果 + 没失败 + 任务行没了」当成还在排队。
    result_deleted_at: datetime | None = None
    #: 失败原因(生成记录自己存的一份,任务被清掉之后还在)。和 JobOut.error 同一套:key 与参数只为翻译服务,
    #: **必须声明在 error 之前**;error 按请求方的语言翻好,没有 key 的(第三方原话)原样返回。
    error_key: str = Field(default="", exclude=True)
    error_params: dict = Field(default_factory=dict, exclude=True)
    error: str | None = None
    created_at: datetime
    updated_at: datetime
    # 计费:取自本次生成记录的用量事件(source_type=generation_job)。costs 为已知估算费用,
    # 每个币种一笔(人民币和美元不相加);有事件但无定价规则时 cost_confidence=unknown、costs 为空
    # (前端显示「未定价」);没有事件时两者都空。
    costs: list[CostAmountOut] = []
    cost_confidence: str | None = None
    #: 失败了,但服务商那边的结果还能**不重新提交**再取一次(下载成片时断了、等远端时出了确定性的错):AI 工作台的失败卡上
    #: 据此摆「重新取回」(POST /generation/jobs/{id}/retrieve)。由列表从任务行算出来贴上(见 sessions._attach_retrievable)。
    retrievable: bool = False

    @field_validator("error_key", mode="before")
    @classmethod
    def _key_or_empty(cls, value: object) -> object:
        return value or ""

    @field_validator("error_params", mode="before")
    @classmethod
    def _params_or_empty(cls, value: object) -> object:
        return value or {}

    @field_validator("error", mode="before")
    @classmethod
    def _translate_error(cls, value: object, info: ValidationInfo) -> object:
        return _rendered(value, info, "error_key", "error_params")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def repeatable(self) -> bool:
        """能不能「再来一次」(照这一条记着的模型和参数重新提交一次,POST /generation/jobs/{id}/again):工作台跑画布上那张图的不行
        (那张图不在记录里),带驱动音频的数字人生成不行(授权每次都要本人勾,不替他带过去)。"""
        return not self.request.get("workbench") and not self.request.get("digital_human_consent")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def stopped(self) -> bool:
        """有人把它停下了(AI 工作台的「停止」、任务中心的取消、画板的停止都走 jobs.cancel_job),不是跑挂了 ——
        界面说「已停止」,不摆一张红色的失败卡。任务落 `cancelled` 那一刻,生成记录抄下「已停止」的 key
        (generation.runner.record_failure),任务被清掉之后也还在。"""
        return self.error_key == CANCELLED_ERROR_KEY

    @computed_field  # type: ignore[prop-decorator]
    @property
    def charged_after_stop(self) -> bool:
        """停下了、服务商那边**可能已经扣过费**(D58):「已停止」那张卡上写明「可能已扣费,成片未保留」—— 维持 ADR 0019,停下就是
        不要这一份,成片不留;但钱的事要说清。

        判据看这一条记下的账(用量事件,由列表贴上 `cost_confidence`,见 sessions._attach_costs):停下之后远端照样做完、或者撤不掉
        没了结的,runner._settle_after_cancel / _record_settled 会记一笔 —— 记了价(估的、服务商报的)或者有账没定价,都算「可能扣过」;
        没交出去就停了、或者服务商那边撤掉了的,没有这一笔(或者只有「没扣费」「免费」),不写。"""
        return self.stopped and self.cost_confidence not in (None, "not_billed", "free")


class GenerationCreateResponse(ApiModel):
    generation: GenerationJobOut
    job: JobOut


class PromptOptimizeRequest(ApiModel):
    workspace_id: str
    #: 目标图像平台(provider/model)——只用来选平台提示词习惯,不是重写用的 LLM。
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=160)
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
    model: str | None = Field(default=None, max_length=160)
    #: 会话一定有种类:创作页按它筛(ADR 0055)。没说就是图像。
    kind: str = Field(default="image", pattern="^(image|video|audio|speech|podcast)$")


class GenerationSessionUpdate(ApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    #: 收进哪个分组;空串或 null 表示退回未分组。
    group_id: str | None = None
    provider_profile_id: str | None = None
    model: str | None = Field(default=None, max_length=160)
    #: 有记录的会话只在同一族里换(ADR 0055 §2),不同族 422。
    kind: str | None = Field(default=None, pattern="^(image|video|audio|speech|podcast)$")


GenerationOriginKind = Literal["studio", "audio_page", "board", "workflow", "entity", "schedule", "agent", "comfyui"]


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
    #: 在哪一处开的(ADR 0052,见 domain/generation/origins)。`origin_name` 现查、**按看的人**查:那一处删了是 `deleted`、
    #: 他看不见是 `hidden`,这两种 `origin_name` 和 `origin_id` 都是空串。标题空着的会话,界面写的就是这一处的名字。
    origin_kind: GenerationOriginKind
    origin_id: str = Field(validation_alias="origin_id_shown")
    origin_name: str
    origin_state: Literal["ok", "deleted", "hidden"]
    created_at: datetime
    updated_at: datetime


class GenerationCapabilityProfileOut(ApiModel):
    """一份用户自己写下的参数组。"""

    id: str
    name: str
    kind: str
    capabilities: dict = Field(default_factory=dict)
    #: 模型行上要存的那个值。前端不自己拼 —— 拼错了是一个解析不到的 ref。
    ref: str


class GenerationCapabilityProfileCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = "image"
    capabilities: dict = Field(default_factory=dict)


class GenerationCapabilityProfileUpdate(ApiModel):
    """只改传了的那几项。kind 不给改 —— 要换就新建一份(见路由里的说明)。"""

    name: str | None = Field(default=None, max_length=120)
    capabilities: dict | None = None


class CapabilityProfileFieldOut(ApiModel):
    """可视表单的一个字段:键、形状、分组。分组是后端语义,前端只翻译标签。"""

    key: str
    shape: str
    group: str
    #: 这一格是**哪个参数**的默认值(`default_quality` → `quality`)。只有 defaults 组有。
    #: 界面据此决定"这个旋钮要不要有一格默认值",而不是自己攒一张名单。
    defaults_for: str | None = None
    #: `choice` 形状的可选值(提示词要不要写:required / optional / none)。别的形状没有这一项。
    choices: list[str] | None = None


class CapabilityProfileSchemaOut(ApiModel):
    """参数组可视表单的结构描述 —— 表单唯一的事实源(见 domain/generation/custom_profiles.py)。"""

    parameters: list[str]
    enum_parameters: list[str]
    source_roles: list[str]
    #: 参数 → 装它可选值的那个键。不在这里的枚举参数,取值装在 parameter_choices 里。
    choices_key: dict[str, str]
    fields: list[CapabilityProfileFieldOut]
