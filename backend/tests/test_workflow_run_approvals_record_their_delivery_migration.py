"""`migrate-workflow-run-approvals-record-their-delivery`:老库的待批单表补上投递结果那三列。

改之前"这一次等待到底发到飞书没有"只活在日志里。这三列之后是**唯一出处**:界面照它说
「已发飞书 / 仅站内(原因) / 发飞书失败(原因)」,取消和超时也照 `feishu_message_id` 把群里那张卡收回。
`create_all` 只建缺失的**表**、从不给已有的表加列 —— 不补这三列,那一版之前建的库一读到这张表就炸在
`no such column: feishu_delivery`。

喂它一份**真实的老形状**(三列都没有,表里已经有一行停着的待批单):看它补成什么样(列定义与模型逐字一致)、
老行是不是活着拿到空值(= 没有投递记录,取消时跳过)、再跑一次什么都不做。
"""

from __future__ import annotations

from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_workflow_run_approvals_record_their_delivery as migrate
from app.db.models import Job, Workflow, WorkflowRunApproval
from tests.util import fresh_client

#: 模型上这三列的定义(`db/model_slices/workflows.WorkflowRunApproval`):(类型, NOT NULL, 缺省)。
#: 缺省一律空 —— **空 = 这张单是这一版之前建的,没有投递记录这回事**,不猜着回填成 `sent`
#: (路由解到了哪说明不了发卡成没成,猜错会在取消时去改一条不存在的消息)。
_WANTED = {
    "feishu_delivery": ("VARCHAR(16)", True, "''"),
    "feishu_delivery_reason": ("VARCHAR(200)", True, "''"),
    "feishu_message_id": ("VARCHAR(120)", True, "''"),
}


def _columns() -> dict[str, tuple[str, bool, object]]:
    with engine.connect() as conn:
        return {
            row[1]: (row[2], bool(row[3]), row[4])
            for row in conn.execute(text("PRAGMA table_info(workflow_run_approvals)"))
        }


def _old_shape() -> str:
    """建一行真数据,再把表削回老形状(这一版之前的模型写不出现在这个样子)。返回那行的 id。"""
    workspace = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=workspace, name="确认", graph={})
        db.add(workflow)
        db.flush()
        job = Job(workspace_id=workspace, kind="workflow", payload={})
        db.add(job)
        db.flush()
        approval = WorkflowRunApproval(
            workspace_id=workspace, workflow_id=workflow.id, job_id=job.id, node_id="gate",
            node_name="上线前确认", title="要发布吗", checkpoint={"done": ["start"]},
            feishu_bot_id="fb_1", feishu_receive_id="oc_team", feishu_receive_type="chat_id",
        )
        db.add(approval)
        db.commit()
        approval_id = approval.id
    with engine.begin() as conn:
        for column in _WANTED:
            conn.execute(text(f"ALTER TABLE workflow_run_approvals DROP COLUMN {column}"))
    engine.dispose()
    return approval_id


def _delivery_row(approval_id: str) -> tuple[str, str, str]:
    """那条炸掉的 SELECT 本身:这三列不在时它当场跑不通。"""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT feishu_delivery, feishu_delivery_reason, feishu_message_id "
                "FROM workflow_run_approvals WHERE id = :id"
            ),
            {"id": approval_id},
        ).one()
    return tuple(row)


def test_老库的待批单表补上投递结果_老行留空_再跑一次什么都不做() -> None:
    approval_id = _old_shape()
    before = _columns()
    assert not (set(_WANTED) & set(before)), "老形状里不该已经有那三列"
    assert {"feishu_receive_id", "feishu_receive_type"} <= set(before), "这是补列的那一次,别的列该在原地"

    migrate()
    engine.dispose()

    columns = _columns()
    for name, wanted in _WANTED.items():
        assert columns.get(name) == wanted, f"{name} 的列定义和模型对不上:{columns.get(name)} != {wanted}"
    #: 老行活着,而且三列是空 —— **空 = 没有投递记录**,取消 / 超时时照它跳过,不去碰飞书。
    assert _delivery_row(approval_id) == ("", "", "")

    migrate()  # 再跑一次:逐列判「在不在」,不报 duplicate column
    engine.dispose()
    assert _columns() == columns
