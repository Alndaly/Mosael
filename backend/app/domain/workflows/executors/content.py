"""工作区内容类节点:插件、素材整理、项目与通知。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Asset, Project, Workflow
from app.domain.jobs import current_actor
from app.domain.notifications import notify
from app.domain.sequences import create_sequence_scaffold
from app.domain.workflows import WorkflowDomainError
from app.domain.plugins.nodes import PLUGIN_NODE_PREFIX
from app.domain.workflows.executors import register, register_prefix
from app.domain.workflows.executors.common import id_list, provided


def _run_plugin_tool(
    db: Session, instance_id: str, tool_name: str, payload: dict[str, Any], *, workspace_id: str
) -> dict[str, Any]:
    from app.domain.plugins import PluginDomainError
    from app.domain.plugins.tools import find, invoke

    tool = find(db, instance_id, tool_name)
    if tool is not None and tool["internal"]:
        # 只给宿主适配层调的工具(见 plugins/manifest.ToolOverride.internal):图里存着也不跑。
        raise WorkflowDomainError("wfErr_pluginToolInternal", params={"tool": tool_name})
    # 收在这里而不是各节点里:插件节点和通用插件节点曾经一个过滤一个不过滤(见 common.provided)。
    payload = provided(payload)
    try:
        # 带上工作区:插件交出的**文件**产出要收进这个工作区的素材库,输出里换成 asset_id。
        # 不带的话,一个从网盘拉文件的节点在工作流里跑不通 —— 它没地方放拿到的东西。
        invocation = invoke(db, instance_id, tool_name, payload, workspace_id=workspace_id)
    except PluginDomainError as exc:  # 停用 / 撤权 / 删掉 —— 是这次运行的失败,不是服务端故障
        raise WorkflowDomainError.from_error(exc) from exc
    if invocation.status != "succeeded":
        raise WorkflowDomainError("wfErr_pluginToolFailed", params={"reason": invocation.error or invocation.status})
    return invocation.output


def _resolve_instance(db: Session, package_id: str, tool_name: str, chosen: str) -> str:
    """节点上选的连接;没选而只有一个可用连接时自动用它。

    自动选是有理由的:绝大多数包只会被接一次,逼用户在下拉里点一下那唯一的一项是纯仪式。
    但有多个时**不猜** —— 从 B 站取和从抖音取是两件事,替用户选错比报错更糟。

    候选只有**跑这条流程的人**自己接的连接:接入归人,别人那条带着别人的密钥和额度。
    """
    from app.domain.plugins.nodes import instances_for_node, node_type_id

    available = instances_for_node(db, node_type_id(package_id, tool_name), current_actor(db))
    if chosen:
        if any(item["id"] == chosen for item in available):
            return chosen
        raise WorkflowDomainError("wfErr_pluginInstanceGone", params={"package": package_id})
    if len(available) == 1:
        return available[0]["id"]
    if not available:
        raise WorkflowDomainError("wfErr_pluginNoInstance", params={"package": package_id})
    names = "、".join(item["name"] for item in available)
    raise WorkflowDomainError("wfErr_pluginManyInstances", params={"package": package_id, "names": names})


@register("plugin_tool")
def plugin_tool(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    """通用插件节点。**保留但不再进节点面板** —— 插件工具现在各自是一个节点(见下面的前缀
    执行器),但用户磁盘上和导出文件里已经存着这种节点,它得继续跑。

    它存的是 plugin_id(包),在实例模型下要先落到一个具体连接上。"""
    tool_name = str(config.get("tool_name", ""))
    instance_id = _resolve_instance(db, str(config.get("plugin_id", "")), tool_name, str(config.get("instance_id", "")))
    return {
        "output": _run_plugin_tool(
            db, instance_id, tool_name, dict(config.get("input") or {}), workspace_id=workflow.workspace_id
        )
    }


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
        from app.domain.plugins.tools import find

        parsed = parse_node_type(node_type)
        if parsed is None:
            raise WorkflowDomainError("wfErr_pluginNodeType", params={"type": node_type})
        package_id, tool_name = parsed
        instance_id = _resolve_instance(db, package_id, tool_name, str(config.get("instance_id") or ""))
        payload = {key: value for key, value in config.items() if key != "instance_id"}
        output = _run_plugin_tool(db, instance_id, tool_name, payload, workspace_id=workflow.workspace_id)

        tool = find(db, instance_id, tool_name)
        outputs = node_meta(tool)["outputs"] if tool else ["output"]
        if outputs == ["output"]:
            return {"output": output}
        return {name: output.get(name) for name in outputs}

    return run


@register("notify")
def send_notify(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    title = str(config.get("title", "")).strip()
    if not title:
        raise WorkflowDomainError("wfErr_notifyTitleEmpty")
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
        # 字面量:素材名里的 `_` / `%` 不是通配符(和笔记检索同一个写法)。
        stmt = stmt.where(Asset.name.contains(name_contains, autoescape=True))
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
        raise WorkflowDomainError("wfErr_tagUnknownMode", params={"mode": mode})
    if not asset_ids:
        raise WorkflowDomainError("wfErr_tagNoAssets")
    if not tags and mode != "replace":
        raise WorkflowDomainError("wfErr_tagsEmpty")

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
        raise WorkflowDomainError("wfErr_updateNoAssets")
    if not name and not project_id:
        raise WorkflowDomainError("wfErr_updateNothingToDo")
    if project_id:
        project = db.get(Project, project_id)
        if project is None or project.workspace_id != workflow.workspace_id:
            raise WorkflowDomainError("wfErr_targetProjectMissing")

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
        raise WorkflowDomainError("wfErr_projectNameEmpty")
    project = Project(workspace_id=workflow.workspace_id, name=name)
    db.add(project)
    db.commit()
    db.refresh(project)
    return {"project_id": project.id, "name": project.name}


@register("project_sequence_create")
def project_sequence_create(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    """建立可立即编排和导出的项目骨架。

    普通「新建项目」只负责归档素材；自动成片需要的是项目 + 序列 + 默认音视频轨。如果让模板
    分别创建这四行，就会有半成品泄漏和轨道 id 无处获取的问题，因此把它们作为一个事务节点。
    """
    name = str(config.get("name") or "").strip()
    if not name:
        raise WorkflowDomainError("wfErr_sequenceProjectNameEmpty")
    try:
        width = int(config.get("width") or 1920)
        height = int(config.get("height") or 1080)
        fps = float(config.get("fps") or 30)
    except (TypeError, ValueError) as exc:
        raise WorkflowDomainError("wfErr_canvasNumbers") from exc
    if not 16 <= width <= 16384 or not 16 <= height <= 16384:
        raise WorkflowDomainError("wfErr_canvasSizeRange")
    if not 1 <= fps <= 240:
        raise WorkflowDomainError("wfErr_fpsRange")

    project = Project(workspace_id=workflow.workspace_id, name=name)
    scaffold = create_sequence_scaffold(
        db,
        project,
        name=name,
        width=width,
        height=height,
        fps=fps,
    )
    project.active_sequence_id = scaffold.sequence.id
    db.commit()
    return {
        "project_id": project.id,
        "sequence_id": scaffold.sequence.id,
        "video_track_id": scaffold.video_track.id,
        "audio_track_id": scaffold.audio_track.id,
        "name": project.name,
    }
