"""「这张图会伸到应用外面去吗」—— 工作流类工具共用的两件事。

从确认内核里搬出来的:它们说的是**工作流这种工具**的规矩,不是确认卡的生命周期。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session


def graph_to_persist(db: Session, tool: str, payload: dict[str, Any]) -> object:
    """这张卡批准之后**会写进库**的那张图。**特权门禁**看的是它。

    只有三个工具会落库。`run_workflow` 不在其中 —— 它执行一张**已经落过库**的图,而那张图在写入
    的那一刻就过过门禁了;把运行也当成落库,等于让不是 instance-admin 的 editor 连别人建好的
    工作流都跑不了(而且定时/webhook 触发根本没有"操作人"可校验)。

    create/update_workflow 带着整份图,取 `payload["graph"]` 就是它。edit_workflow 只带
    `operations` —— 图要把 ops 应用到当前图上才出现。此前门禁一律读 `payload.get("graph")`,
    于是 edit_workflow 那条恒为 None、静默跳过:editor 在画布上存不下 code 节点(三条路由都挡),
    却可以让智能体 add_node(type=code) 再自己批一下,门就白设了。

    必须**应用后再扫**,不能只看 ops 里的 node type:`set_node_config` 能把一整张含 code 的图
    塞进子图体里,那一手在 ops 层面看不见,在结果图上一眼就能看见(扫描器本来就递归子图体)。

    ops 应用不了(图在开卡后被改过)就返回 None:同一份 apply_graph_ops 紧接着会在执行里再跑
    一次并失败,什么都不会落库 —— 这里不放行任何东西,所以不是 fail-open。
    """
    if tool in ("create_workflow", "update_workflow"):
        return payload.get("graph")
    if tool != "edit_workflow":
        return None
    from app.db.models import Workflow
    from app.domain.workflows import WorkflowDomainError
    from app.domain.workflows.graph_ops import apply_graph_ops

    workflow = db.get(Workflow, str(payload.get("workflow_id") or ""))
    if workflow is None:
        return None
    try:
        return apply_graph_ops(workflow.graph or {}, payload.get("operations") or [])
    except WorkflowDomainError:
        return None


def graph_under_review(db: Session, tool: str, payload: dict[str, Any]) -> object:
    """这次调用会**落库或执行**的那张图。**档位派生**看的是它。

    比落库那张多一个 `run_workflow`:运行不写库,但它把图里的每个节点真的执行一遍 —— 对"后果落在
    哪"这个问题,运行恰恰是后果发生的那一刻。两个问题的答案不同,所以是两个函数而不是一个带开关的
    (一个开关迟早会被下一个调用方按错)。
    """
    if tool == "run_workflow":
        from app.db.models import Workflow

        workflow = db.get(Workflow, str(payload.get("workflow_id") or ""))
        return workflow.graph if workflow is not None else None
    return graph_to_persist(db, tool, payload)


def external_warning(external: set[str] | None) -> str:
    """把「这张图会伸到应用外面去」写成人话,挂在摘要末尾。

    摘要是用户点批准之前唯一会读的一行。`edit_workflow` 早就为 code 节点这么做了(见
    test_confirmation_disclosure);同样的理由对 `run_workflow` 一字不差地成立 —— 而它此前只说
    「可能产生 AI/渲染消耗」,把"会用你的账号发帖"整个咽了回去。
    """
    if not external:
        return ""
    from app.core.i18n import get_current_locale, t
    from app.domain.workflows import NODE_TYPES

    #: 目录里存的是 key(见 core/i18n),这句话是给**用户**看的 —— 直接拼进去的话卡上会写
    #: 「含 wfNode_code 节点」。这里就是出口,所以在这里翻。
    locale = get_current_locale()
    labels = sorted(t(str((NODE_TYPES.get(name) or {}).get("label") or name), locale) for name in external)
    return f"  ⚠️ 含{'、'.join(labels)}节点(后果在本应用之外,撤不回)"
