"""智能体:会话与分组、消息、记忆、计划、上下文水位,以及提问卡与确认卡。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from pydantic import Field, ValidationInfo, field_validator
from app.api.schemas.base import ApiModel, OrmModel

class AgentContextPart(ApiModel):
    """堆叠条里的一段。kind ∈ messages|tools|system|free。"""

    kind: str
    tokens: int


class AgentContextOut(ApiModel):
    """窗口被**什么**占满了,不只是占了多少。

    一个百分比回答不了任何该做的决定:满了要清什么?清对话有用吗?而这个应用里最大的一块
    往往**不是对话** —— 工具定义每轮重发一遍,一条消息没有时它也在。分项由后端算:它需要
    系统提示的实际内容和工具清单,那两样都在服务端,前端猜出来的分项比没有分项更糟。
    """

    #: 供应商上次实际看到的量(锚点用量 + 之后新增的估算)。水位条读 `used`,这个留给明细。
    tokens: int
    window: int
    #: 各分项之和 = window。堆叠条按它画。
    used: int
    parts: list[AgentContextPart] = []


class AgentCompactOut(ApiModel):
    """一次手动压缩的结果。

    `compaction` 为 None 表示没有可压缩的内容(对话还太短)—— 界面据此说"暂时不需要整理",
    而不是显示一个"压缩了 0 条"的空结果。
    """

    context: AgentContextOut | None = None
    compaction: dict | None = None


class AgentPendingView(ApiModel):
    """智能体要求界面跳到哪一页。`view` 的合法值由 mcp_server._VIEWS 把关。"""

    view: str = Field(min_length=1, max_length=40)
    id: str = Field(default="", max_length=64)


class AgentQuestionOption(ApiModel):
    label: str
    description: str = ""


class AgentQuestionItem(ApiModel):
    header: str = ""
    question: str
    multi_select: bool = False
    options: list[AgentQuestionOption] = Field(default_factory=list)


class AgentQuestionCreate(ApiModel):
    workspace_id: str
    session_id: str
    #: 形状由 domain/agent/questions.normalize 校 —— 校验和展示用同一份规则,
    #: 在这里再写一遍 pydantic 约束会变成第二个答案。
    questions: list[dict] = Field(default_factory=list)


class AgentQuestionAnswer(ApiModel):
    #: {问题正文: [选中的 label]}。单选也是列表(长度 1)—— 两种形状分开的话消费端要解析两遍。
    answers: dict[str, list[str]] = Field(default_factory=dict)


class AgentQuestionOut(OrmModel):
    id: str
    workspace_id: str
    session_id: str
    questions: list[AgentQuestionItem] = Field(default_factory=list)
    answers: dict[str, list[str]] = Field(default_factory=dict)
    status: str
    created_at: datetime
    answered_at: datetime | None = None


class AgentSessionCreate(ApiModel):
    workspace_id: str
    project_id: str | None = None
    title: str = Field(default="新对话", max_length=200)
    adapter: str | None = Field(default=None, pattern="^pi$")
    provider_profile_id: str | None = None
    model: str | None = Field(default=None, max_length=120)


class SessionGroupCreate(ApiModel):
    workspace_id: str
    #: 挂在哪一种会话上。两边各自一套,见 db/model_slices/agent.SESSION_GROUP_KINDS。
    kind: str = Field(default="agent", pattern="^(agent|generation)$")
    name: str = Field(min_length=1, max_length=80)


class SessionGroupUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    sort_order: int | None = None


class SessionGroupOut(OrmModel):
    id: str
    workspace_id: str
    kind: str
    owner_user_id: str | None = None
    name: str
    sort_order: int = 0
    created_at: datetime
    updated_at: datetime


class AgentSessionUpdate(ApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    provider_profile_id: str | None = None
    model: str | None = Field(default=None, max_length=120)
    #: 视频分析方式偏好:auto / native / frames。
    analysis_video_mode: str | None = None
    thinking_level: str | None = None
    #: 权限模式:manual / auto / bypass。切到 bypass 另需 admin(见路由)。
    permission_mode: str | None = None
    #: 「本会话始终允许」的工具名单。整份替换 —— 它就是用户在卡上点出来的那份清单。
    auto_allow_tools: list[str] | None = None
    #: 收进哪个分组。**空串 = 移出分组**(与 provider_profile_id 同一套约定):这套 schema 用
    #: None 表示"这次没改",所以"改成没有"必须另有说法。
    group_id: str | None = Field(default=None, max_length=64)


class AgentSessionOut(OrmModel):
    id: str
    workspace_id: str
    # 归属(见 domain/sharing):对话默认只有自己看得见,主人可以把某一次拿出来给同事看。
    owner_user_id: str | None = None
    is_mine: bool = True
    shared: bool = False
    project_id: str | None
    group_id: str | None = None
    title: str
    origin: str
    adapter: str
    permission_mode: str = "manual"
    mode_set_by: str | None = None
    auto_allow_tools: list[str] = []
    provider_profile_id: str | None = None
    model: str | None = None
    analysis_video_mode: str = "auto"
    thinking_level: str = "off"
    status: str
    #: 智能体要求界面跳到哪儿(`view` 或 `view:id`)。跳完由前端 DELETE 掉。
    pending_view: str = ""
    #: 当前上下文水位。**每次请求现算**,而不是等某一轮回报 —— 打开旧会话、刚换过模型、
    #: 上一轮失败了,这些时候都没有新的一轮可以带回这个数,而"还能聊多久"这个问题恰恰在
    #: 开口之前就要有答案。窗口取当前模型的,换模型即变。
    context: AgentContextOut | None = None
    #: 当前任务计划 `[{"step","status"}]`;还没有计划时为 None(界面据此整块不显示)。
    plan: list[dict] | None = None
    created_at: datetime
    updated_at: datetime


class AgentPlanUpdate(ApiModel):
    steps: list = Field(default_factory=list)


class AgentMemoryOut(OrmModel):
    id: str
    workspace_id: str
    project_id: str | None = None
    content: str
    #: agent = 智能体自己记的;user = 用户在设置里写的。
    source: str = "agent"
    created_at: datetime
    updated_at: datetime


class AgentMemoryCreate(ApiModel):
    workspace_id: str
    project_id: str | None = None
    content: str = Field(min_length=1, max_length=500)
    source: str = "user"


class AgentMemoryUpdate(ApiModel):
    content: str = Field(min_length=1, max_length=500)


class AgentReferenceIn(ApiModel):
    """正文里 `@` 出来的一个对象。

    **正文只写名字,id 走这里。** 名字会重、会改、会带空格,拿它当标识迟早出事;而把 32 位
    十六进制塞进句子会把真正的话挤没。两件事分开:模型读到的是「把 @运镜练习 改长一点」,
    要动手时从这份清单里拿 id。
    """

    kind: Literal["asset", "note", "board", "workflow"]
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(default="", max_length=200)


class AgentMessageCreate(ApiModel):
    content: str = Field(min_length=1, max_length=8000)
    context: str | None = Field(default=None, max_length=4000)
    #: 正文里引用到的对象。落库进 payload(气泡照它把胶囊画回来),同时拼成一段给模型的清单。
    references: list[AgentReferenceIn] = Field(default_factory=list, max_length=32)
    #: 编辑器原样的文档。**气泡靠它把引用渲染成胶囊**,而不是把 `@名字` 当成一串普通的字。
    #: 没有它的话,发送这个动作本身会把用户刚放进去的结构抹平。
    body_document: dict | None = None
    #: 发起方是另一个智能体会话时带上它的 id(notify_agent_session)。结构化而不是靠文案前缀:
    #: 标题自动命名要跳过它,前端要给它画来源徽章 —— 两件事都不该建立在字符串匹配上。
    origin_session_id: str | None = Field(default=None, max_length=64)


class AgentMessageOut(OrmModel):
    id: str
    session_id: str
    role: str
    content: str
    payload: dict
    error: str | None
    created_at: datetime


class ConfirmationCreate(ApiModel):
    workspace_id: str
    tool: str = Field(min_length=1, max_length=80)
    payload: dict = Field(default_factory=dict)
    requested_by: str = Field(default="external-agent", max_length=120)


class ConfirmationOut(OrmModel):
    id: str
    workspace_id: str
    session_id: str | None
    tool: str
    permission: str
    summary: str
    summary_key: str = ""
    summary_params: dict = {}
    payload: dict
    status: str
    result: dict
    error: str | None
    requested_by: str
    decision_mode: str = "manual"
    decided_by: str | None = None
    created_at: datetime
    resolved_at: datetime | None

    @field_validator("summary", mode="before")
    @classmethod
    def _translate_summary(cls, value: object, info: ValidationInfo) -> object:
        """卡上那句话按**读的人**的语言翻,与 JobOut 同构。

        确认卡是授权界面:一个英文用户读不懂的授权提示,等于没有提示。
        老卡没有 key,那时 `summary` 就是它自己的原话,原样返回。
        """
        from app.core.i18n import get_current_locale, render_nested

        data = info.data if isinstance(info.data, dict) else {}
        key = str(data.get("summary_key") or "")
        if not key:
            return value
        return render_nested(key, data.get("summary_params") or {}, get_current_locale())


class AgentSkillOut(ApiModel):
    id: str
    name: str
    description: str
    source: str
    tools: list = Field(default_factory=list)
    permissions: list = Field(default_factory=list)


class AgentManifestOut(ApiModel):
    app: str
    version: str
    openapi_url: str
    skills: list[AgentSkillOut]


class AgentStreamEvent(ApiModel):
    """SSE 上一帧:这一轮**到此刻为止**的全量快照(不是增量)。

    它此前没有 schema —— 形状由路由现场拼一个 dict,前端两个消费者各写一份 `as {...}` 断言,
    而 `as` 绕过类型检查:少写一个字段不报错,多写一个也不报错。实测两份断言**已经不一样**
    (画布那份没有 `done`)。给它一个 schema,前端就从生成类型取,不再手抄。

    挂在流式路由的 `response_model` 上纯粹是为了让它进 openapi:路由返回的是
    `StreamingResponse`,FastAPI 对直接返回的 Response 不做序列化,所以这条声明不影响流本身。
    """

    #: 这一轮到此刻的正文。全量,不是增量 —— 客户端直接赋值即可。
    text: str = ""
    #: 这一轮结束了。**后端发完它就 break。** 客户端读它来收尾,而不是靠"流关了"去推断:
    #: 那个推断在中间设备拖着连接不关的时候会一直等下去。
    done: bool = False
    #: 执行轨迹(工具调用、子智能体、确认卡),同样是全量快照。
    timeline: list[dict[str, Any]] = Field(default_factory=list)
