"""工作流触发器:**谁在哪个群、丢来什么样的消息,就让哪条工作流跑一次**(ADR 0065)。

两张表,一配置一留痕:

- `WorkflowTrigger` 是一份配置 —— 哪条工作流、哪个机器人/群、认哪些消息、入参怎么映射、开关;
- `WorkflowTriggerEvent` 是"这条消息被这条触发器认领了,然后怎么了"。它同时是**去重的判据**
  (`(trigger_id, message_id)` 唯一约束,见 ADR 0065 §4)与**限流的账本**(最近一分钟里
  `status=started` 的行数),所以它不能是一份"随手清掉"的日志。

飞书那一侧怎么把消息送进来、怎么发回执,在 `integrations/feishu/inbound.py`;规则在
`app/domain/triggers/`。这里只放形状。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.db.model_base import new_id, now


class WorkflowTrigger(Base):
    """一条触发器:某条工作流在某个飞书会话里,被某些消息叫起来。

    和 `ScheduledTask` 的两处对应关系是**故意的**(同一条规矩,两个来源):`owner_user_id` 是
    "跑的时候替谁跑"(用它的钥匙、算它的额度、判 ADR 0047 的担保),`enabled` 是"关掉就是关掉"
    —— 删掉它盯的那条工作流时当场停用,不删行(留痕)。
    """

    __tablename__ = "workflow_triggers"
    __table_args__ = (
        Index("idx_workflow_triggers_workspace", "workspace_id"),
        Index("idx_workflow_triggers_workflow", "workflow_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    #: 哪条工作流。**不设外键**:图没了,这条触发器要**留着**(停用,连同它的名字和最近触发记录),
    #: 删不删由人决定 —— 和定时任务把 `workflow_id` 放在 payload 里是同一个取舍(见
    #: scheduler.stop_tasks_bound_to_workflow)。设了外键就会跟着级联删掉,"这里原本挂着一条
    #: 自动化、它跑过几次"这段痕迹也跟着没了。
    workflow_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: 这份自动化是谁挂上去的 —— 触发的时候替他跑。**不设外键**:账号删了,归属仍是留痕。
    owner_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, default="", server_default="")
    #: 哪个机器人。空串 = 这个工作区里任意一个(见 domain/feishu/bots)。
    bot_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    #: 哪个群。空串 = 这个机器人所在的任意会话。
    chat_id: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    #: 认哪些消息类型:`text`(含富文本 post)/ `image` / `file` / `media`。空表 = 一条都不认。
    message_types: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    #: 可选关键词。非空时,消息文本里要出现任意一个(大小写不敏感)才算命中。
    keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    #: 可选白名单。非空时只认这些飞书 open_id 发来的消息。
    only_from_open_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    #: 入参映射:`{"<开始节点参数名>": "<含 {{trigger.*}} 的模板>"}`(ADR 0065 §2)。
    params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    #: 要不要在群里说话:起跑回执 + 跑完的结果。关掉之后只在站内留痕。
    reply_in_chat: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    #: 每分钟最多真起跑几次(限流,ADR 0065 §4)。1–60。
    max_runs_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=6, server_default="6")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    #: 上一次**真的起跑了**是什么时候(被限流、被拒的不算)。
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class WorkflowTriggerEvent(Base):
    """一条消息被一条触发器认领过的那一次。

    **它同时是三件事**,所以不能当成可以随手清掉的日志:

    1. **去重**:`(trigger_id, message_id)` 唯一约束。飞书会重放事件,而进程内的
       `seen_recently` 重启就没了 —— 重放+重启正是"同一条消息付费跑两次"的那一刻。
       处理一条消息时**先插这一行**,插得进去才继续;
    2. **限流的账本**:最近一分钟里 `status="started"` 的行数(ADR 0065 §4);
    3. **"它在干活吗"**:触发器面板上的「最近触发」就是这张表。

    状态:`started`(真的起了一次运行)/ `throttled`(限流丢了)/ `refused`(工作流没了、
    跑不起来)/ `failed`(起运行的时候抛了)/ `skipped`(一条消息认领的触发器超过上限时落选的)。
    行随触发器删(外键级联);`job_id` 指的那次运行删了就置空(留痕还在)。
    """

    __tablename__ = "workflow_trigger_events"
    __table_args__ = (
        #: 去重的判据。同一条消息被两条触发器认领是两行 —— 那是两次运行,不是重复。
        UniqueConstraint("trigger_id", "message_id", name="uq_workflow_trigger_events_trigger_message"),
        Index("idx_workflow_trigger_events_trigger_created", "trigger_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    trigger_id: Mapped[str] = mapped_column(ForeignKey("workflow_triggers.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    message_id: Mapped[str] = mapped_column(String(120), nullable=False)
    #: 这条消息从哪来 —— 触发器上的 `bot_id`/`chat_id` 可能是空串(任意),回执要按**这一次**的来。
    bot_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    chat_id: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    sender_open_id: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    message_type: Mapped[str] = mapped_column(String(24), nullable=False, default="", server_default="")
    #: 消息文本的开头一段(列表里要能认出是哪条消息,但不存整段,也不存文件)。
    text_preview: Mapped[str] = mapped_column(String(400), nullable=False, default="", server_default="")
    #: 这一次入素材库的素材 id(图片 / 文件 / 视频)。
    asset_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    #: `status=started` 时那次运行的任务;`refused` / `failed` 时为空。
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="started", server_default="started", index=True)
    #: 没跑起来的原因(拒绝 / 失败时是人话)。
    error: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
