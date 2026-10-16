from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.db.model_base import new_id, now


class Workflow(Base):
    """可执行工作流的当前投影；不可变历史由 :class:`WorkflowRevision` 持有。"""

    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    graph: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    graph_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class WorkflowRevision(Base):
    """工作流图的一份不可变快照。

    `Workflow.graph` 是读路径上的当前投影；这里才是历史与执行复现的事实来源。恢复旧图会
    追加新行，不修改任何已有修订。模板版本仍留在 graph.meta 中，它描述模板出处，不与用户
    每次保存产生的 revision 混为一谈。
    """

    __tablename__ = "workflow_revisions"
    __table_args__ = (
        UniqueConstraint("workflow_id", "revision", name="uq_workflow_revisions_workflow_revision"),
        Index("idx_workflow_revisions_workflow_revision", "workflow_id", "revision"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    graph: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    graph_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="edit", server_default="edit")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class WorkflowRevisionAttestation(Base):
    """有人「认可了这一版」:不改图、不增版,只为这一版多担保一个人。

    一次运行用私有发布账号 / 浏览器档案 / 本机文件时,被执行那一版的担保人(作者 + 这里记下的人)
    里得有一个自己用得了(见 domain/authority)。同事改过的一版借不到主人的东西,直到主人认可它。
    挂在修订上而不是再存一版:修订不可变,执行语义没变也不增版。
    """

    __tablename__ = "workflow_revision_attestations"
    __table_args__ = (
        UniqueConstraint("revision_id", "user_id", name="uq_workflow_revision_attestations_revision_user"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    revision_id: Mapped[str] = mapped_column(ForeignKey("workflow_revisions.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class WorkflowRunOutput(Base):
    """一次运行里某个节点某个输出的**全文** —— 只存事件快照截断了的那些长文字。

    `workflow.node.finished` 事件和 `job.result` 里存的是有界快照(长文字只留开头):它们随运行列表、
    事件流一起反复下发,不能无界。但用户要复制 / 下载的是那段模型回复本身,不是它的开头。全文单独
    一张表,界面按需取一段(见 routes/workflows 的 run_output),不拖着别的列表一起变重。
    随任务一起删(外键级联)。
    """

    __tablename__ = "workflow_run_outputs"
    __table_args__ = (
        UniqueConstraint("job_id", "node_id", "output_key", name="uq_workflow_run_outputs_job_node_key"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(String(120), nullable=False)
    output_key: Mapped[str] = mapped_column(String(120), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class WorkflowRunApproval(Base):
    """工作流跑到「等人确认」节点时**落库**的那一次等待:问题、超时怎么算、谁批的、批成什么。

    一次运行里同一个节点只有一张单(唯一约束 `job_id + node_id`):重启之后接着等、决定已经做过再
    被读到,认的都是同一行,不会又发一张卡。

    `checkpoint` 是暂停那一刻的现场(见 domain/workflows/approvals 与 engine.GraphResume):
    **已经落定的那些节点的产物**加上"哪些节点跑过了"。恢复时从暂停的那一个节点接着跑,靠的就是它
    —— 前面跑完的节点不重跑(它们可能已经烧了钱、落了素材)。

    行随任务删(外键级联)。这不是定时任务那套「等主人认可这一版」(scheduler.approvals):那一条
    判的是**要不要花主人的连接**,只提醒不拦、没有单子、也不需要唤醒哪一次运行。
    """

    __tablename__ = "workflow_run_approvals"
    __table_args__ = (
        UniqueConstraint("job_id", "node_id", name="uq_workflow_run_approvals_job_node"),
        Index("idx_workflow_run_approvals_status_expires", "status", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(String(120), nullable=False)
    #: 暂停时那个节点叫什么(节点起过名就是那个名字)—— 事件和列表里说人话要用,图改了也还认得出。
    node_name: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    #: 按钮文案(飞书卡片和应用内那两处共用一份):留空时出口按语言给缺省的「确认 / 拒绝」。
    approve_label: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    reject_label: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    #: 卡片上要不要一个备注输入框(飞书那条路);不要的话决定里不带备注。
    allow_note: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    #: 多久算超时(秒);空 = 一直等。
    timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: 超时之后怎么办:continue(当 timeout 继续往下)/ abort(中止这一次运行)/ remind(只再提醒一次,继续等)。
    on_timeout: Mapped[str] = mapped_column(String(16), nullable=False, default="continue", server_default="continue")
    #: 拒绝之后怎么办:branch(当成决定交给下游)/ abort(中止这一次运行)。
    on_reject: Mapped[str] = mapped_column(String(16), nullable=False, default="abort", server_default="abort")
    #: pending / approved / rejected / timeout / cancelled。**只有 pending 是可以被决定的那一态。**
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending", index=True)
    #: 节点交给下游的那一格:approved / rejected / timeout(空 = 还没决定)。
    decision: Mapped[str] = mapped_column(String(16), nullable=False, default="", server_default="")
    decided_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    #: 决定那一刻把显示名抄下来:人后来改名 / 注销,回执上仍是当时那个人。
    decided_by_name: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    #: 飞书卡片上那个输入框里的话(应用内批的时候也可以留一句)。
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    #: 决定是从哪条路来的:feishu / app / timeout / cancel —— 两条路汇到同一处,但看得出来历。
    decided_via: Mapped[str] = mapped_column(String(16), nullable=False, default="", server_default="")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: 什么时候算超时(空 = 不超时)。到期由后台那一拍处理(workers/scheduler)。
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: 「只提醒」那一档提醒过一次的时刻 —— 到点提醒之后把 expires_at 往后推一格,不是发一条就完。
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: 暂停那一刻的现场:{context, executed, done}(见 engine.GraphResume)。
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    #: 飞书路由:卡片发回哪个机器人的哪个会话(和工具确认卡同一个做法,但这里要跨重启活着,所以存下来)。
    #: `receive_type` 是 chat_id 或 open_id —— 这个运行**来自飞书会话**时发回那个群,否则退化成私聊
    #: 发起这次运行的那个人(见 integrations/feishu/approvals):都发不出去就只剩站内那条路。
    feishu_bot_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    feishu_receive_id: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    feishu_receive_type: Mapped[str] = mapped_column(String(16), nullable=False, default="", server_default="")
    #: 这一次等待**真的发到飞书了吗**:`sent` / `failed` / `not_attempted`(空 = 还没走过这一遍)。
    #: 此前只有日志分得清这三件事,单上看不出来 —— 而"到底发到飞书没有"决定了人该去哪儿批。
    #: `not_attempted` 是**路由那一层就没打算发**(写了「仅站内」/ 没有机器人 / 发起人没绑定):
    #: 那是用户明说的选择或这次运行没有可发的去处,不是失败(见 domain/workflows/approvals)。
    feishu_delivery: Mapped[str] = mapped_column(String(16), nullable=False, default="", server_default="")
    #: 为什么是这个结果:`not_attempted` 记路由那一档的原因(`none` / `no-bot` / …),`failed` 记发出去时撞上的那一句。
    feishu_delivery_reason: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    #: 飞书那条消息的 id(`om_…`):发出去了才写。取消 / 超时时照它把群里那张卡就地收回成结果态
    #: —— 否则一张还能点的卡留在群里,别人不知道这件事已经结束(见 integrations/feishu/approvals)。
    feishu_message_id: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)
