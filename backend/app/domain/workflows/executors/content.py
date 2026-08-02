"""工作区内容类节点:知识库、插件、素材整理、项目与通知。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Asset, Project, Workflow
from app.domain.notifications import notify
from app.domain.workflows import WorkflowDomainError
from app.domain.plugins.nodes import PLUGIN_NODE_PREFIX
from app.domain.workflows.executors import register, register_prefix
from app.domain.workflows.executors.common import id_list


@register("kb_search")
def kb_search(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    from app.db.models import KbDataset
    from app.domain.kb import search

    limit = int(config.get("limit") or 5)
    dataset_id = str(config.get("dataset_id", "")).strip()
    dataset = db.get(KbDataset, dataset_id) if dataset_id else None
    if dataset is None:
        # 未指定库时退回工作区内最早的知识库,保持节点可用。
        dataset = db.scalars(
            select(KbDataset)
            .where(KbDataset.workspace_id == workflow.workspace_id)
            .order_by(KbDataset.created_at)
        ).first()
    if dataset is None:
        return {"text": "", "results": []}
    results = search(db, dataset, str(config.get("query", "")), top_k=limit)
    text = "\n\n".join(f"[{item['title']}] {item['snippet']}" for item in results)
    return {"text": text, "results": results}


def _run_plugin_tool(db: Session, plugin_id: str, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    from app.domain.plugins.registry import PluginDomainError, invoke_plugin_tool

    try:
        invocation = invoke_plugin_tool(db, plugin_id, tool_name, payload)
    except PluginDomainError as exc:  # 插件被停用 / 撤权 / 删掉 —— 是这次运行的失败,不是服务端故障
        raise WorkflowDomainError(f"插件 {plugin_id} 不可用: {exc}") from exc
    if invocation.status != "succeeded":
        raise WorkflowDomainError(f"插件工具失败: {invocation.error or invocation.status}")
    return invocation.output


@register("plugin_tool")
def plugin_tool(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    """通用插件节点。**保留但不再进节点面板** —— 插件工具现在各自是一个节点(见下面的前缀
    执行器),但用户磁盘上和导出文件里已经存着这种节点,它得继续跑。"""
    output = _run_plugin_tool(
        db, str(config.get("plugin_id", "")), str(config.get("tool_name", "")), dict(config.get("input") or {})
    )
    return {"output": output}


@register_prefix(PLUGIN_NODE_PREFIX)
def plugin_node(node_type: str):
    """插件自带节点:`plugin.<插件id>.<工具名>`。

    **节点的 config 就是工具的入参**,一一对应 —— 这是「插件节点」成立的前提:用户在表单里
    填的每一格,就是工具 input_schema 里的一个键,中间没有翻译层可以出错。

    输出按节点声明的 outputs 分发:声明了具名输出就从工具返回值里按同名键取,没声明(默认
    `["output"]`)就把整份返回值装进 output。前者让下游直接引用 `{{node.title}}`,后者保证
    任何工具不写一个字也能用。
    """
    from app.domain.plugins.nodes import parse_node_type

    def run(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
        from app.domain.plugins.nodes import node_meta
        from app.domain.plugins.registry import list_enabled_plugin_tools

        parsed = parse_node_type(node_type)
        if parsed is None:
            raise WorkflowDomainError(f"插件节点类型不合法: {node_type}")
        plugin_id, tool_name = parsed
        # 空字符串是编辑器给未填字段的种子值。原样发给工具会让"没填"和"填了空串"变成同一件事,
        # 而工具的必填校验就此失效 —— 它收到的是一个存在但为空的键。
        payload = {key: value for key, value in config.items() if value not in (None, "")}
        output = _run_plugin_tool(db, plugin_id, tool_name, payload)

        tool = next(
            (t for t in list_enabled_plugin_tools(db) if t["plugin_id"] == plugin_id and t["tool_name"] == tool_name),
            None,
        )
        outputs = node_meta(tool)["outputs"] if tool else ["output"]
        if outputs == ["output"]:
            return {"output": output}
        return {name: output.get(name) for name in outputs}

    return run


@register("notify")
def send_notify(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    title = str(config.get("title", "")).strip()
    if not title:
        raise WorkflowDomainError("通知标题不能为空")
    notify(
        db,
        workflow.workspace_id,
        type="workflow",
        title=title,
        body=str(config.get("body", "")),
        link="#/workflows",
        payload={"workflow_id": workflow.id},
    )
    db.commit()
    return {"sent": True}


@register("asset_query")
def asset_query(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    """Batch-select workspace assets by filters → {assets, ids, count}. Feeds loop_foreach.items."""
    kind = str(config.get("kind") or "all").strip()
    name_contains = str(config.get("name_contains") or "").strip()
    tags_raw = str(config.get("tags") or "").strip().replace("，", ",")
    wanted_tags = {tag.strip() for tag in tags_raw.split(",") if tag.strip()}
    try:
        limit = int(config.get("limit") or 50)
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 500))

    stmt = select(Asset).where(Asset.workspace_id == workflow.workspace_id)
    if kind and kind != "all":
        stmt = stmt.where(Asset.kind == kind)
    if name_contains:
        stmt = stmt.where(Asset.name.contains(name_contains))
    stmt = stmt.order_by(Asset.created_at.desc())
    rows = list(db.scalars(stmt))
    if wanted_tags:
        rows = [asset for asset in rows if wanted_tags & set(asset.tags or [])]
    rows = rows[:limit]

    assets = [
        {
            "id": asset.id,
            "name": asset.name,
            "kind": asset.kind,
            "duration": (asset.media_info or {}).get("duration"),
            "tags": list(asset.tags or []),
        }
        for asset in rows
    ]
    return {"assets": assets, "ids": [asset["id"] for asset in assets], "count": len(assets)}


@register("asset_tag")
def asset_tag(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    """Add / remove / replace tags on a batch of assets → {updated, count}."""
    asset_ids = id_list(config.get("asset_ids"))
    tags = id_list(config.get("tags"))
    mode = str(config.get("mode") or "add").strip() or "add"
    if mode not in ("add", "remove", "replace"):
        raise WorkflowDomainError(f"素材打标签:未知的模式 {mode}")
    if not asset_ids:
        raise WorkflowDomainError("素材打标签:没有可处理的素材 id")
    if not tags and mode != "replace":
        raise WorkflowDomainError("素材打标签:标签不能为空")

    updated: list[dict[str, Any]] = []
    for asset_id in asset_ids:
        asset = db.get(Asset, asset_id)
        # Cross-workspace ids are skipped rather than fatal: a workflow fed by a query cannot
        # produce them, and one fed by hand should not be able to reach another workspace.
        if asset is None or asset.workspace_id != workflow.workspace_id:
            continue
        current = list(asset.tags or [])
        if mode == "add":
            merged = current + [tag for tag in tags if tag not in current]
        elif mode == "remove":
            merged = [tag for tag in current if tag not in tags]
        else:
            merged = list(tags)
        # Assigning a new list matters: mutating asset.tags in place leaves the JSON column
        # unchanged as far as SQLAlchemy is concerned, and the write silently does nothing.
        asset.tags = merged
        updated.append({"id": asset.id, "name": asset.name, "tags": merged})
    db.commit()
    return {"updated": updated, "count": len(updated)}


@register("asset_update")
def asset_update(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    """Rename assets and/or file them under a project → {updated, count}."""
    asset_ids = id_list(config.get("asset_ids"))
    name = str(config.get("name") or "").strip()
    project_id = str(config.get("project_id") or "").strip()
    if not asset_ids:
        raise WorkflowDomainError("素材整理:没有可处理的素材 id")
    if not name and not project_id:
        raise WorkflowDomainError("素材整理:至少要设置新名称或目标项目")
    if project_id:
        project = db.get(Project, project_id)
        if project is None or project.workspace_id != workflow.workspace_id:
            raise WorkflowDomainError("素材整理:目标项目不存在,或不属于当前工作区")

    updated: list[dict[str, Any]] = []
    for index, asset_id in enumerate(asset_ids):
        asset = db.get(Asset, asset_id)
        if asset is None or asset.workspace_id != workflow.workspace_id:
            continue
        if name:
            # One name across many assets would produce N identical names, which is unusable
            # in a picker — number them instead.
            asset.name = name if len(asset_ids) == 1 else f"{name} {index + 1}"
        if project_id:
            asset.project_id = project_id
        updated.append({"id": asset.id, "name": asset.name, "project_id": asset.project_id})
    db.commit()
    return {"updated": updated, "count": len(updated)}


@register("project_create")
def project_create(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    name = str(config.get("name") or "").strip()
    if not name:
        raise WorkflowDomainError("新建项目:项目名不能为空")
    project = Project(workspace_id=workflow.workspace_id, name=name)
    db.add(project)
    db.commit()
    db.refresh(project)
    return {"project_id": project.id, "name": project.name}
