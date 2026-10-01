"""工作区内容类节点:插件、素材整理、项目与通知。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import String, select, type_coerce, update
from sqlalchemy.orm import Session

from app.db.models import Asset, Project
from app.domain.jobs import current_actor
from app.domain.notifications import notify
from app.domain.projects import create_project
from app.domain.sequences import create_sequence_scaffold
from app.domain.workflows import WorkflowDomainError
from app.domain.plugins.nodes import PLUGIN_NODE_PREFIX
from app.domain.workflows.executors.registry import (
    Preflight,
    PreflightNode,
    RunScope,
    register,
    register_prefix,
    register_prefix_preflight,
)
from app.domain.workflows.executors.common import id_list, provided, whole_number


def _run_plugin_tool(
    db: Session, instance_id: str, tool_name: str, payload: dict[str, Any], *, workspace_id: str
) -> dict[str, Any]:
    from app.domain.plugins import PluginDomainError
    from app.domain.plugins.tools import invoke

    # 只给宿主适配层调的工具(internal)图里存着也不跑 —— 那道门在 invoke 里(pluginErr_toolInternal)。
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
    """节点上选的连接,只在**跑这条流程的人**自己的连接里找(见 plugins.nodes.resolve_instance)。"""
    from app.domain.plugins import PluginDomainError
    from app.domain.plugins.nodes import resolve_instance

    try:
        return resolve_instance(db, package_id, tool_name, chosen, current_actor(db))
    except PluginDomainError as exc:
        raise WorkflowDomainError.from_error(exc) from exc


@register("plugin_tool")
def plugin_tool(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """通用插件节点。**保留但不再进节点面板** —— 插件工具现在各自是一个节点(见下面的前缀
    执行器),但用户磁盘上和导出文件里已经存着这种节点,它得继续跑。

    它存的是 plugin_id(包),在实例模型下要先落到一个具体连接上。"""
    tool_name = str(config.get("tool_name", ""))
    instance_id = _resolve_instance(db, str(config.get("plugin_id", "")), tool_name, str(config.get("instance_id", "")))
    return {
        "output": _run_plugin_tool(
            db, instance_id, tool_name, dict(config.get("input") or {}), workspace_id=scope.workspace_id
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

    def run(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
        from app.domain.plugins.nodes import declared_outputs
        from app.domain.plugins.tools import find, output_port

        parsed = parse_node_type(node_type)
        if parsed is None:
            raise WorkflowDomainError("wfErr_pluginNodeType", params={"type": node_type})
        package_id, tool_name = parsed
        instance_id = _resolve_instance(db, package_id, tool_name, str(config.get("instance_id") or ""))
        payload = {key: value for key, value in config.items() if key != "instance_id"}
        output = _run_plugin_tool(db, instance_id, tool_name, payload, workspace_id=scope.workspace_id)

        tool = find(db, instance_id, tool_name)
        outputs = declared_outputs(tool) if tool else ["output"]
        if outputs == ["output"]:
            return {"output": output}
        return {name: output_port(output, name) for name in outputs}

    return run


@register_prefix_preflight(PLUGIN_NODE_PREFIX)
def plugin_node_preflight(node_type: str) -> Preflight:
    """插件节点开跑前先问「轮到它时落得到一条连接吗」:选的连接停用了、有好几条却没选 —— 此前开跑前只看节点类型,
    放行之后要等前面的节点跑完(钱花完)才在这一步失败。判法和执行时同一条(plugins.nodes.check_plugin_node_instance)。"""

    def check(db: Session, config: dict[str, Any], actor: str | None, _place: PreflightNode) -> None:
        from app.domain.plugins.nodes import check_plugin_node_instance

        problem = check_plugin_node_instance(db, {"type": node_type, "config": config}, actor)
        if problem is not None:
            raise WorkflowDomainError.from_error(problem)

    return check


@register("notify")
def send_notify(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    title = str(config.get("title", "")).strip()
    if not title:
        raise WorkflowDomainError("wfErr_notifyTitleEmpty")
    notify(
        db,
        scope.workspace_id,
        type="workflow",
        title=title,
        body=str(config.get("body", "")),
        link="#/workflows",
        payload={"workflow_id": scope.id},
    )
    return {"sent": True}


@register("asset_query")
def asset_query(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """Batch-select workspace assets by filters → {assets, ids, count}. Feeds loop_foreach.items."""
    kind = str(config.get("kind") or "all").strip()
    name_contains = str(config.get("name_contains") or "").strip()
    # 和「素材打标签」同一种解析(id_list):手填是逗号分隔的一串,接上游时常常是一个真列表 ——
    # 此前 `str()` 了它,`['a', 'b']` 被当成一个叫 "['a'" 的标签,什么都筛不出来,也不报错。
    wanted_tags = set(id_list(config.get("tags")))
    limit = max(1, min(whole_number(config, "limit", node_type="asset_query", default=50), 500))

    stmt = select(Asset).where(Asset.workspace_id == scope.workspace_id)
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
def asset_tag(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
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

    def change(current: list[Any]) -> list[Any]:
        if mode == "add":
            return current + [tag for tag in tags if tag not in current]
        if mode == "remove":
            return [tag for tag in current if tag not in tags]
        return list(tags)

    updated: list[dict[str, Any]] = []
    for asset_id in asset_ids:
        asset = db.get(Asset, asset_id)
        # Cross-workspace ids are skipped rather than fatal: a workflow fed by a query cannot
        # produce them, and one fed by hand should not be able to reach another workspace.
        if asset is None or asset.workspace_id != scope.workspace_id:
            continue
        merged = _retag(db, asset, change)
        updated.append({"id": asset.id, "name": asset.name, "tags": merged})
    return {"updated": updated, "count": len(updated)}


#: 一份素材的标签被同时改时,最多重读几次。
_TAG_ATTEMPTS = 8


def _retag(db: Session, asset: Asset, change: Any) -> list[Any]:
    """读这份素材**库里最新**的标签 → 改 → 只在库里还是读到的那一份时写回;被别人抢先就重读再改。

    并行的两个「打标签」(两条分支、并发的循环项)各在自己的会话里读到同一份标签、各自合并、整列写回
    —— 后写的那个把先写的那个加的标签盖掉。素材没有版本号,比的是库里存的**那一段原文**(读出来、写回去
    都按原文比,不经 JSON 转换 —— 同一份标签有不同写法时也不会误判)。SQLite 一次只有一个写入方:后来者
    在写的那一刻等前一个节点提交,然后撞上新标签、重试。
    """
    stored = type_coerce(Asset.tags, String)
    for _attempt in range(_TAG_ATTEMPTS):
        raw = db.scalar(select(stored).where(Asset.id == asset.id))
        current = list(json.loads(raw) or []) if raw else []
        merged = change(current)
        if merged == current:
            return merged
        written = db.execute(
            update(Asset)
            .where(Asset.id == asset.id, stored == raw if raw is not None else Asset.tags.is_(None))
            .values(tags=merged)
            .execution_options(synchronize_session=False)
        ).rowcount
        if written:
            db.refresh(asset)
            return merged
    raise WorkflowDomainError("wfErr_tagConflict")


@register("asset_update")
def asset_update(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
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
        if project is None or project.workspace_id != scope.workspace_id:
            raise WorkflowDomainError("wfErr_targetProjectMissing")

    updated: list[dict[str, Any]] = []
    for index, asset_id in enumerate(asset_ids):
        asset = db.get(Asset, asset_id)
        if asset is None or asset.workspace_id != scope.workspace_id:
            continue
        if name:
            # One name across many assets would produce N identical names, which is unusable
            # in a picker — number them instead.
            asset.name = name if len(asset_ids) == 1 else f"{name} {index + 1}"
        if project_id:
            asset.project_id = project_id
        updated.append({"id": asset.id, "name": asset.name, "project_id": asset.project_id})
    return {"updated": updated, "count": len(updated)}


@register("image_grid_split")
def image_grid_split(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """一张宫格拼图 → 几张单图(见 assets.image_grid)。`asset_id` 是第一张,下游多数节点只接一份。"""
    from app.domain.assets.image_grid import ImageGridError, parse_grid, split_image_grid

    asset = db.get(Asset, str(config.get("asset_id") or ""))
    if asset is None or asset.workspace_id != scope.workspace_id:
        raise WorkflowDomainError("wfErr_gridAssetNotInWorkspace")
    grid = str(config.get("grid") or "3x3")
    try:
        _rows, cols = parse_grid(grid)
        pieces = split_image_grid(db, asset, grid=grid, gutter=str(config.get("gutter") or "keep") == "trim")
    except ImageGridError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    ids = [piece.id for piece in pieces]
    return {"asset_ids": ids, "asset_id": ids[0] if ids else "", "count": len(ids), "columns": cols,
            "source_asset_id": asset.id}


@register("project_create")
def project_create(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    name = str(config.get("name") or "").strip()
    if not name:
        raise WorkflowDomainError("wfErr_projectNameEmpty")
    project = create_project(db, scope.workspace_id, name)
    db.flush()
    return {"project_id": project.id, "name": project.name}


@register("project_sequence_create")
def project_sequence_create(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """建立可立即编排和导出的项目骨架。

    普通「新建项目」只负责归档素材；自动成片需要的是项目 + 序列 + 默认音视频轨。如果让模板
    分别创建这四行，就会有半成品泄漏和轨道 id 无处获取的问题，因此把它们作为一个事务节点。
    """
    name = str(config.get("name") or "").strip()
    if not name:
        raise WorkflowDomainError("wfErr_sequenceProjectNameEmpty")
    #: 宽高是整数格,和别的整数格同一个判法(common.whole_number):`"1920.0"` 是 1920,`"1920.5"` 报哪一格不是整数。
    #: 此前 `int(… or 1920)`:"1920.0" 报一句笼统的「必须是数字」,填 0 悄悄换成 1920。
    width = whole_number(config, "width", node_type="project_sequence_create", default=1920)
    height = whole_number(config, "height", node_type="project_sequence_create", default=1080)
    try:
        fps = float(config.get("fps") or 30)
    except (TypeError, ValueError) as exc:
        raise WorkflowDomainError("wfErr_canvasNumbers") from exc
    if not 16 <= width <= 16384 or not 16 <= height <= 16384:
        raise WorkflowDomainError("wfErr_canvasSizeRange")
    if not 1 <= fps <= 240:
        raise WorkflowDomainError("wfErr_fpsRange")

    #: 给了项目就把这条时间线建在它里面 —— 「一条长视频切十条竖屏」是一个项目十条时间线,不是十个项目。
    #: 项目 id 常常来自上游节点,所以和别处一样先比对工作区。
    project_id = str(config.get("project_id") or "").strip()
    if project_id:
        project = db.get(Project, project_id)
        if project is None or project.workspace_id != scope.workspace_id:
            raise WorkflowDomainError("wfErr_sequenceProjectMissing")
    else:
        project = create_project(db, scope.workspace_id, name)
    scaffold = create_sequence_scaffold(
        db,
        project,
        name=name,
        width=width,
        height=height,
        fps=fps,
    )
    #: 打开项目时停在哪条时间线:新项目停在这一条;已有项目保持它原来那条(没有才用这一条)。
    if not project.active_sequence_id:
        project.active_sequence_id = scaffold.sequence.id
    db.flush()
    return {
        "project_id": project.id,
        "sequence_id": scaffold.sequence.id,
        "video_track_id": scaffold.video_track.id,
        "audio_track_id": scaffold.audio_track.id,
        "name": project.name,
    }
