"""`migrate-workflow-run-approvals-take-the-current-shape`:老库的待批单表补上 `on_reject` 和飞书路由那两列、去掉
`feishu_chat_id`。

这张表是 1.9 开发期才有的,而开发机上它是**当天更早的一版模型**建出来的(那时只有 `feishu_chat_id`,没有
`on_reject`);`create_all` 只建缺失的**表**、从不给已有的表加列 —— 那些库于是永远停在旧形状上,任何
`SELECT ... FROM workflow_run_approvals` 都当场炸在 `no such column: on_reject`。

喂它一份**真实的老形状**:三列没有、多一列 `feishu_chat_id`,而且表里已经有一行停着的待批单。看它补成什么样
(列定义与模型逐字一致)、老行是不是活着拿到缺省值、`feishu_chat_id` 是不是没了;再跑一次什么都不做。

**这条和 `test_schema_migrations_cover_the_models` 里那条端到端的种子测试是两回事**:那条的种子库是照
`schema_baseline.json` 建的,而这张表在基线里**出生就带着终版三列** —— 那条在这张表上走的是 no-op 分支,
真正喂过旧形状的是这里(以及交付报告里那份真实开发库的只读副本)。
"""

from __future__ import annotations

from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_workflow_run_approvals_take_the_current_shape as migrate
from app.db.models import Job, Workflow, WorkflowRunApproval
from tests.util import fresh_client

#: 模型上这三列的定义(`db/model_slices/workflows.WorkflowRunApproval`):(类型, NOT NULL, 缺省)。
#: `on_reject` 的缺省是 `abort` —— 拒绝默认让这次运行停下;两列路由缺省是空 = 没发出去过。
_WANTED = {
    "on_reject": ("VARCHAR(16)", True, "'abort'"),
    "feishu_receive_id": ("VARCHAR(120)", True, "''"),
    "feishu_receive_type": ("VARCHAR(16)", True, "''"),
}


def _columns() -> dict[str, tuple[str, bool, object]]:
    with engine.connect() as conn:
        return {
            row[1]: (row[2], bool(row[3]), row[4])
            for row in conn.execute(text("PRAGMA table_info(workflow_run_approvals)"))
        }


def _old_shape() -> str:
    """建一行真数据,再把表削回**老模型建出来的形状**(新代码写不出这个样子)。返回那行的 id。"""
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
        )
        db.add(approval)
        db.commit()
        approval_id = approval.id
    with engine.begin() as conn:
        for column in _WANTED:
            conn.execute(text(f"ALTER TABLE workflow_run_approvals DROP COLUMN {column}"))
        conn.execute(
            text("ALTER TABLE workflow_run_approvals ADD COLUMN feishu_chat_id VARCHAR(64) NOT NULL DEFAULT ''")
        )
    engine.dispose()
    return approval_id


def _paused_row(approval_id: str) -> tuple[str, str, str]:
    """那条炸掉的 SELECT 本身(见现场):`on_reject` 不在时它就跑不通。"""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT on_reject, feishu_receive_id, feishu_receive_type FROM workflow_run_approvals WHERE id = :id"),
            {"id": approval_id},
        ).one()
    return tuple(row)


def test_老库的待批单表补成模型现在的形状_老行活着_再跑一次什么都不做() -> None:
    approval_id = _old_shape()
    before = _columns()
    assert not (set(_WANTED) & set(before)), "老形状里不该已经有那三列"
    assert "feishu_chat_id" in before

    migrate()
    engine.dispose()

    columns = _columns()
    for name, wanted in _WANTED.items():
        assert columns.get(name) == wanted, f"{name} 的列定义和模型对不上:{columns.get(name)} != {wanted}"
    assert "feishu_chat_id" not in columns, "旧形状里那一列没人读了,照仓库规矩删掉;留着只会让人以为它有用"
    assert _paused_row(approval_id) == ("abort", "", ""), "老行活着,拒绝之后按模型缺省走 abort"

    migrate()  # 再跑一次:加列、删列各自判「在不在」,不报 duplicate column、也不抛 no such column
    engine.dispose()
    assert _columns() == columns
