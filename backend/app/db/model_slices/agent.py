"""智能体:会话与分组、消息、记忆,以及等着人处理的那两种卡(提问与确认)。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.db import Base
from app.db.model_base import new_id, now

#: 分组挂在哪一种会话上。两边**各自一套**:对话里建的「客户 A」不会跑到生成栏里去空着站着。
SESSION_GROUP_KINDS = ("agent", "generation")


class SessionGroup(Base):
    """会话分组:给会话列表分个类,便于管理。对话和生成共用这张表,由 `kind` 分开。

    **是一张表而不是会话上的一个名字字符串**:分组要能空着存在(先建「客户 A」,再往里挪会话),
    改名要是一次操作而不是把 N 行的字符串挨个改一遍 —— 名字当键的话,这两件事都做不到。

    删掉分组**不删里面的会话**(先把成员的 group_id 清空):分组是收纳方式,不是所有权。
    """

    __tablename__ = "session_groups"
    __table_args__ = (Index("idx_session_groups_ws_kind", "workspace_id", "kind"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    #: "agent" | "generation" —— 见 SESSION_GROUP_KINDS。
    kind: Mapped[str] = mapped_column(String(24), nullable=False, default="agent")
    #: 谁建的。和会话同一条规矩:不设外键,账号没了归属仍是审计信息。
    owner_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    #: 手动排序位。越小越靠前;相同就按建立时间。
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class AgentSession(Base):
    __tablename__ = "agent_sessions"
    __table_args__ = (Index("idx_agent_sessions_ws_updated", "workspace_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    #: 这是谁的。**不设外键**:账号被删时这份东西的归属仍然是审计信息,不该级联消失
    #: (归属与共享见 domain/sharing)。
    owner_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    #: 收在哪个分组里。空 = 未分组(列表里单独一段)。删分组时由路由显式清空 —— 老库那一列
    #: 是迁移加的、没有外键约束,不能指望数据库替我们 SET NULL。
    group_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="新对话")
    origin: Mapped[str] = mapped_column(String(24), nullable=False, default="ui")  # ui | feishu
    #: 智能体要求界面跳到哪儿(`view` 或 `view:id`),**待消费一次**。
    #:
    #: 方向是反的:智能体跑在后端,而"切页面"是前端的事。放在会话行上是因为前端本来就在轮询
    #: 会话状态(1.5s),不用新增一条通路;放进 SSE 流的话,免提浮标那种没开流的场景就收不到 ——
    #: 而"手不在键盘上、让它带我过去"恰恰是这件事最有用的时候。
    #:
    #: 前端跳完就清空。不清的话,重开应用会再跳一次 —— 一个几天前说过的"打开工作流"。
    pending_view: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    external_key: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True)
    #: 跑这次会话的运行时。目前只有 "pi";留列是为了旧会话仍能被正确解读。
    adapter: Mapped[str] = mapped_column(String(40), nullable=False, default="pi")
    # 对话用的供应商 + 模型(pi 适配器);空则回退第一个启用供应商及其默认模型
    provider_profile_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("provider_profiles.id", ondelete="SET NULL"), nullable=True
    )
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # 视频分析方式偏好:auto(默认,原生优先否则抽帧)/ native(强制原生)/ frames(强制抽帧+转写)。
    # 会话级,聊天里可切,注入系统提示让 analyze_asset 照此传 mode。
    analysis_video_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")
    #: 权限模式:manual(默认)/ auto / bypass。挂在**会话**上 —— 「这次对话里哪一类动作不用问我」
    #: 是每次对话的选择,和思考档位同类。
    permission_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="manual", server_default="manual")
    #: 模式是**谁**开的。行动人不是他就退回手动:飞书群聊共用一个会话,群里任何人发消息都跑在
    #: 同一个会话上 —— 没有这一条,A 开的 bypass 会替 B 做决定。而会话本身不记 owner。
    #: 谁开的这个模式。**不能用 owner_user_id 顶替**(ADR 0008 D6 曾经提过这个简化):会话可以
    #: 被共享,共享之后别的成员也能改模式 —— 那时"谁开的"与"谁的会话"是两个人,而模式是一次
    #: **授权动作**,只对做出授权的那个人生效。合并两列等于把一个人的授权悄悄转给另一个人。
    mode_set_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: 开启时刻。计费卡「连续自动放行几张」从这里起算。
    mode_set_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: 「本会话始终允许」的工具名。此前是浏览器 localStorage 里的一份自动批准 —— 聊天面板一关
    #: 组件就卸载,而 turn 还在跑,同一个"授权"的行为取决于某个 React 组件在不在。
    auto_allow_tools: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    #: 思考档位(off/low/medium/high)。挂在**会话**上而不是模型上:同一个模型有时要深想、
    #: 有时要快答,它是每次对话的选择。off 时 pi 根本不向供应商要思考。
    thinking_level: Mapped[str] = mapped_column(String(10), nullable=False, default="off")
    #: 当前任务计划:`[{"step": "...", "status": "pending|in_progress|done"}]`。
    #: 挂在会话上而不是单独建表 —— 一次会话只有一份"现在在做什么",历史进度由 update_plan
    #: 的工具卡在时间线上留痕,不需要第二套版本记录。
    plan: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    # pi 适配器无 --resume:存 pi 序列化的消息数组做多轮记忆(下轮回灌 initialState.messages)
    adapter_state: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="idle")  # idle | running
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)

    messages: Mapped[list["AgentMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="AgentMessage.created_at"
    )


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    __table_args__ = (Index("idx_agent_messages_session_created", "session_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)  # user | assistant | system
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)

    session: Mapped[AgentSession] = relationship(back_populates="messages")


class AgentMemory(Base):
    """跨会话记忆:一条关于"这个工作区里该知道的事"的短事实。

    记忆是**每轮都注入系统提示**的行为约定,不是需要临时检索的外部资料 ——
    "视频统一 1080p 竖屏"、"片头永远用 brand-intro.mp4"、"客户叫我别用红色"。
    参考 Claude Code 的 CLAUDE.md / Codex 的 AGENTS.md:它们的价值恰恰在于不用检索也生效。

    **两级作用域**:workspace_id 必填(记忆跟着工作区走),project_id 可空 —— 填了就只在
    那个项目的会话里注入。这对应 Claude Code 的"用户级 / 项目级"两层。
    """

    __tablename__ = "agent_memories"
    __table_args__ = (Index("idx_agent_memories_ws", "workspace_id", "project_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    #: agent = 智能体自己记下的;user = 用户在设置里写的。用户写的排在前面注入。
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="agent")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class AgentQuestion(Base):
    """智能体问用户一个有选项的问题,等他挑。

    **不是确认卡。** 确认卡问的是「这件事能不能做」,而这里问的是「你要哪一个」——
    形状像,但有一条决定性的差别:确认卡有 `auto_allow_tools` 和 bypass 模式,可以被
    自动批准;而询问的**全部意义就是智能体不知道答案**,自动回答等于让它自己编一个。
    共用一张表的话,那两个开关迟早会把问题一起自动答掉。

    只在对话里出现(session_id 必填):一个问题脱离了它的上下文没有意义 —— 右上角的
    全局中心里蹦出一句「你要哪一个」,而看的人根本不知道在说什么。
    """

    __tablename__ = "agent_questions"
    __table_args__ = (Index("idx_agent_questions_session", "session_id", "status"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    #: 哪次对话问的。不设外键:会话删了这条记录的归属仍有审计意义。
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: [{header, question, multi_select, options: [{label, description}]}]
    questions: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    #: {question: [选中的 label]}。多选也是列表 —— 单选是"长度为 1 的列表",
    #: 两种形状分开存的话,消费端要写两遍解析。
    answers: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    #: pending | answered | dismissed
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ToolConfirmation(Base):
    __tablename__ = "tool_confirmations"
    __table_args__ = (
        Index("idx_tool_confirmations_ws_status", "workspace_id", "status"),
        Index("idx_tool_confirmations_session", "session_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    #: 发起这张确认卡的智能体会话。**可空**:MCP / 飞书等外部智能体没有会话,它们的卡由右上角
    #: 全局确认中心兜底。有会话的卡只在**它自己那次对话**里内联出现 —— 否则同工作区的其它对话会
    #: 把它显示出来,更糟的是会被那边的「本会话始终允许」自动批准(授权范围逃逸)。
    #: 不设外键:会话删除后这张卡的归属仍然有意义(审计),也不该级联删掉历史。
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=False)
    tool: Mapped[str] = mapped_column(String(80), nullable=False)
    permission: Mapped[str] = mapped_column(String(40), nullable=False)
    #: 卡上那句话。**存的是渲染好的默认语言**,而真正的事实是下面那两列 ——
    #: 出口(ConfirmationOut)按读的人的语言重新渲染,与 JobOut 同构。老卡没有 key,
    #: 那时这一列就是它自己的原话,原样返回。
    summary: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    summary_key: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    summary_params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[str] = mapped_column(String(120), nullable=False, default="external-agent")
    #: 这张卡是**怎么**过的:manual(人点的)/ session-allow(工具白名单)/ auto / bypass。
    #: 自动放行必须留痕,而且要能一眼看出是哪一档放的 —— 事后能查是 bypass 唯一可接受的前提。
    decision_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="manual", server_default="manual")
    #: 记在谁头上。自动放行也有人 —— 那次 turn 是以他的身份跑的,授权闸也是按他校验的。
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: 判定依据:档位、计数快照、规则命中、判断者的输入与裁决。
    #: 判定是 (工具, 参数, 准则) 的纯函数,把输入记下来,事后就能复算"当时为什么放行"。
    decision_detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    #: 在这之前先别打扰用户 —— 隔离判断者正在看这张卡(见 domain/agent/autopilot)。
    #: 用**会自己到期的时间**而不是一个"判定中"状态:状态要有人去回收,期限不用 —— 进程崩在判断
    #: 中间,期限自己过去,卡自己回到待办。与 AuthSession 的过期同一种做法。
    hold_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
