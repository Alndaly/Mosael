"""工作流库(ADR 0035):认领 `workflow_library` 的连接上存着哪些工作流 —— 宿主这一侧。

插件回答「这台服务器上存着哪些工作流、每张长什么样、缺什么」,替宿主改那台机器上的工作流文件(复制、改名、挪进 / 挪出
回收目录)。宿主做的是插件做不了、也不该做的:

- **规整**:插件报的每一条都过一遍(没有路径的丢掉、长文本截断、图摘要限量),界面拿到的形状只有一种;
- **它在 Mosael 里的样子**:这张工作流是不是这个连接下的一个生成模型(用它生成要它)、这个工作区里最近一次用它生成的
  产出、这个工作区里哪些工作流节点 / 画板格子选的是它(引用表,见 db/references 的 `generation_model`);
- **路径先查一遍**:只认 `workflows/` 里的相对路径(`.json`,不带 `..`、反斜杠、控制字符和 Windows 不收的字符),
  回收目录里的只认插件报过的那种形状 —— 不交给插件猜;
- **改完马上刷新**:这个连接的生成目录和工具清单重拉一遍(`host_capabilities.notify(refresh=True)`),不等一分钟的指纹。

**不覆盖**:复制、改名、恢复撞了名,插件回 `conflict` 和一个建议名,这里翻成 409(带着建议名),界面要求换名。

**这里不认识 ComfyUI**:任何认领 `workflow_library` 的连接,插件页上都有「工作流库」。列表不存库,每次现问插件。
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError, fragment
from app.db.models import Board, GenerationJob, PluginInstance, ProviderProfile, User, Workflow
from app.db.references import generation_model_key
from app.domain import capabilities
from app.domain.permissions import ensure_workspace_access
from app.domain.plugins import host_capabilities
from app.domain.plugins import instances as inst
from app.domain.plugins import tools
from app.domain.plugins.manifest import WORKFLOW_LIBRARY
from app.domain.providers import models as provider_models
from app.domain.references import referrers

#: 列一遍最多等多久:要取每张工作流、转一遍、再列一遍模型目录。
LIBRARY_TIMEOUT_SECONDS = 600
#: 取一张、存一张、挪一张:一两个请求的事。
QUICK_TIMEOUT_SECONDS = 120

_MAX_WORKFLOWS = 2000
_MAX_LIST = 200
_MAX_GRAPH_NODES = 400
_MAX_GRAPH_LINKS = 1200
_MAX_GRAPH_GROUPS = 60
_MAX_USES = 50
_ROLES = {"input", "model", "sampler", "text", "output", "note", "missing", "other"}
#: Windows 上文件名里不能有的字符(那台 ComfyUI 可能在 Windows 上):路径段里一个都不收。
_BAD_SEGMENT = re.compile(r'[\x00-\x1f<>:"|?*\\]')
#: 回收目录里的一张:`.mosael-trash/workflows/<时刻>/<原来的相对路径>`(ADR 0035 §3)。
_TRASH_PATH = re.compile(r"^\.mosael-trash/workflows/\d{8}-\d{6}(-\d+)?/(?P<original>.+)$")


class WorkflowLibraryError(LocalizedError, ValueError):
    """工作流库这一侧说不行(这个连接不提供工作流库、路径不对)。带文案 key(`workflowLibErr_*`)。"""


class WorkflowConflict(WorkflowLibraryError):
    """撞名了:那台服务器上已经有这个名字。`suggestion` 是一个不撞名的建议。"""

    def __init__(self, path: str, suggestion: str) -> None:
        super().__init__("workflowLibErr_exists", path=path)
        self.path = path
        self.suggestion = suggestion


def _require(db: Session, instance: PluginInstance) -> None:
    if WORKFLOW_LIBRARY not in inst.manifest_for(db, instance).provides:
        raise WorkflowLibraryError("workflowLibErr_notProvided", name=instance.name)


def _text(value: Any, limit: int = 500) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def workflow_path(value: str) -> str:
    """`workflows/` 里的一张:相对路径、`.json` 结尾、`/` 分段,每段不空、不是 `.` / `..`、不以点开头(那是隐藏的)、
    没有 Windows 不收的字符。不合格就拒,不交给插件。"""
    text = (value or "").strip()
    segments = text.split("/")
    if not text.lower().endswith(".json") or len(text) > 500 or any(
        not one or one in (".", "..") or one.startswith(".") or one != one.strip() or _BAD_SEGMENT.search(one)
        for one in segments
    ):
        raise WorkflowLibraryError("workflowLibErr_badPath", path=text)
    return text


def trash_path(value: str) -> str:
    text = (value or "").strip()
    found = _TRASH_PATH.match(text)
    if found is None or ".." in text.split("/"):
        raise WorkflowLibraryError("workflowLibErr_badPath", path=text)
    workflow_path(found.group("original"))
    return text


# --- 列出来 ------------------------------------------------------------------

def _graph(raw: Any) -> dict[str, Any]:
    """画缩略图用的图摘要:节点(位置、大小、种类、是否旁路、标题)、连线(节点下标)、分组。限量,坏条目丢掉。"""
    raw = raw if isinstance(raw, dict) else {}
    nodes: list[dict[str, Any]] = []
    for one in raw.get("nodes") or []:
        if not isinstance(one, dict) or len(nodes) >= _MAX_GRAPH_NODES:
            continue
        x, y, w, h = (_number(one.get(key)) for key in ("x", "y", "w", "h"))
        if x is None or y is None:
            continue
        role = _text(one.get("role"), 20)
        nodes.append({
            "x": x, "y": y, "w": max(w or 0.0, 20.0), "h": max(h or 0.0, 20.0),
            "role": role if role in _ROLES else "other",
            "muted": one.get("muted") is True,
            "title": _text(one.get("title"), 120),
        })
    links: list[list[int]] = []
    for one in raw.get("links") or []:
        if len(links) >= _MAX_GRAPH_LINKS:
            break
        if isinstance(one, list) and len(one) >= 2 and all(isinstance(i, int) and not isinstance(i, bool) for i in one[:2]) \
                and 0 <= one[0] < len(nodes) and 0 <= one[1] < len(nodes):
            links.append([one[0], one[1]])
    groups: list[dict[str, Any]] = []
    for one in raw.get("groups") or []:
        if not isinstance(one, dict) or len(groups) >= _MAX_GRAPH_GROUPS:
            continue
        x, y, w, h = (_number(one.get(key)) for key in ("x", "y", "w", "h"))
        if None in (x, y, w, h):
            continue
        color = _text(one.get("color"), 20)
        groups.append({"x": x, "y": y, "w": w, "h": h, "title": _text(one.get("title"), 120),
                       "color": color if re.fullmatch(r"#[0-9a-fA-F]{3,8}", color) else ""})
    return {
        "nodes": nodes,
        "links": links,
        "groups": groups,
        "auto_layout": raw.get("auto_layout") is True,
        "truncated": raw.get("truncated") is True or len(raw.get("nodes") or []) > _MAX_GRAPH_NODES,
    }


def _items(value: Any, keys: dict[str, int]) -> list[dict[str, str]]:
    """一串 `{键: 字}`:只留认得的键,截断;一个都没有的条目丢掉。"""
    out: list[dict[str, str]] = []
    for one in value if isinstance(value, list) else []:
        if isinstance(one, dict):
            item = {key: _text(one.get(key), limit) for key, limit in keys.items()}
            if any(item.values()):
                out.append(item)
    return out[:_MAX_LIST]


def _missing_nodes(value: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for one in value if isinstance(value, list) else []:
        if not isinstance(one, dict) or not _text(one.get("type"), 200):
            continue
        packs = [
            {"id": _text(pack.get("id"), 300), "title": _text(pack.get("title"), 200) or _text(pack.get("id"), 300),
             "installed": pack.get("installed") is True}
            for pack in one.get("packs") or [] if isinstance(pack, dict) and _text(pack.get("id"), 300)
        ][:10]
        out.append({"type": _text(one.get("type"), 200), "count": int(_number(one.get("count")) or 1), "packs": packs})
    return out[:_MAX_LIST]


def _workflow(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    try:
        path = workflow_path(_text(raw.get("path"), 500))
    except WorkflowLibraryError:
        return None
    size = _number(raw.get("size"))
    return {
        "path": path,
        "label": path[:-5].rsplit("/", 1)[-1],
        "folder": path.rsplit("/", 1)[0] if "/" in path else "",
        "size": int(size) if size is not None else None,
        "modified": _number(raw.get("modified")),
        "kind": _text(raw.get("kind"), 20),
        "problem": _text(raw.get("problem"), 2000),
        "node_count": int(_number(raw.get("node_count")) or 0),
        "graph": _graph(raw.get("graph")),
        "inputs": _items(raw.get("inputs"), {"node": 40, "title": 200, "media": 20, "role": 40}),
        "parameters": _items(raw.get("parameters"), {"key": 200, "title": 200, "type": 20}),
        "outputs": _items(raw.get("outputs"), {"node": 40, "title": 200, "media": 20}),
        "models": [
            {"folder": item["folder"], "name": item["name"], "present": bool(one.get("present"))}
            for one in raw.get("models") or [] if isinstance(one, dict)
            for item in [{"folder": _text(one.get("folder"), 200), "name": _text(one.get("name"), 1000)}]
            if item["folder"] and item["name"]
        ][:_MAX_LIST],
        "missing_nodes": _missing_nodes(raw.get("missing_nodes")),
        "missing_models": [
            one for one in _items(raw.get("missing_models"), {"folder": 200, "name": 1000, "url": 4000})
            if one["folder"] and one["name"]
        ],
    }


def _trash(value: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for one in value if isinstance(value, list) else []:
        if not isinstance(one, dict):
            continue
        try:
            path = trash_path(_text(one.get("path"), 600))
        except WorkflowLibraryError:
            continue
        original = _TRASH_PATH.match(path).group("original")  # type: ignore[union-attr]
        out.append({"path": path, "original": original, "label": original[:-5].rsplit("/", 1)[-1],
                    "deleted_at": _number(one.get("deleted_at"))})
    return out[:_MAX_WORKFLOWS]


def _profile(db: Session, instance: PluginInstance) -> ProviderProfile | None:
    return db.scalar(select(ProviderProfile).where(ProviderProfile.plugin_instance_id == instance.id))


def _in_mosael(db: Session, instance: PluginInstance, workspace_id: str, workflows: list[dict[str, Any]]) -> None:
    """每张工作流在 Mosael 里的样子:是不是这个连接下的生成模型、这个工作区里最近一次用它生成的产出、谁在用它。"""
    profile = _profile(db, instance)
    rows = {row.model_id: row for row in provider_models.list_models(db, profile.id)} if profile is not None else {}
    for flow in workflows:
        flow["generation"] = None
        flow["last_output"] = None
        flow["used_by"] = []
        row = rows.get(flow["path"])
        if profile is None or row is None:
            continue
        kinds = [kind for kind in row.capability_ids or [] if kind in ("image", "video", "audio")]
        if row.enabled and kinds:
            flow["generation"] = {"provider_profile_id": profile.id, "kind": kinds[0], "model": row.model_id}
        if not workspace_id:
            continue
        last = db.scalar(
            select(GenerationJob)
            .where(GenerationJob.workspace_id == workspace_id, GenerationJob.provider_profile_id == profile.id,
                   GenerationJob.model == row.model_id, GenerationJob.result_asset_id.is_not(None))
            .order_by(GenerationJob.created_at.desc())
            .limit(1)
        )
        if last is not None:
            flow["last_output"] = {"asset_id": last.result_asset_id, "created_at": last.created_at}
        key = generation_model_key(profile.id, row.model_id)
        uses: list[dict[str, str]] = [
            {"kind": "workflow", "id": workflow.id, "name": workflow.name}
            for workflow in db.scalars(select(Workflow).where(
                Workflow.workspace_id == workspace_id, Workflow.id.in_(referrers("generation_model", key, "workflow"))))
        ]
        uses += [
            {"kind": "board", "id": board.id, "name": board.name}
            for board in db.scalars(select(Board).where(
                Board.workspace_id == workspace_id, Board.id.in_(referrers("generation_model", key, "board"))))
        ]
        flow["used_by"] = uses[:_MAX_USES]


def library(db: Session, user: User, instance: PluginInstance, *, workspace_id: str = "") -> dict[str, Any]:
    """现问插件:这个连接上存着的全部工作流(连同图摘要、识别出的输入 / 参数 / 输出、用到的模型、缺什么)、不是工作流的
    文件、回收目录里的;再补上它们在 Mosael 里的样子(只看 `workspace_id` 这个工作区,`user` 得进得去)。"""
    if workspace_id:
        ensure_workspace_access(db, user, workspace_id)
    _require(db, instance)
    output = tools.invoke_host(db, instance.id, WORKFLOW_LIBRARY, {"op": "workflows"},
                               timeout=LIBRARY_TIMEOUT_SECONDS, record=False)
    workflows = [one for one in (_workflow(raw) for raw in (output.get("workflows") or [])[:_MAX_WORKFLOWS]) if one]
    _in_mosael(db, instance, workspace_id, workflows)
    manager = output.get("manager") if isinstance(output.get("manager"), dict) else {}
    return {
        "workflows": workflows,
        "others": [one for one in _items(output.get("others"), {"path": 500, "reason": 2000}) if one["path"]],
        "trash": _trash(output.get("trash")),
        "manager": {"version": _text(manager.get("version"), 40)},
    }


# --- 一张的原文 ----------------------------------------------------------------

def content(db: Session, instance: PluginInstance, path: str) -> dict[str, Any]:
    """一张工作流的原文(导出成 JSON 用)。"""
    _require(db, instance)
    path = workflow_path(path)
    output = tools.invoke_host(db, instance.id, WORKFLOW_LIBRARY, {"op": "workflow", "path": path},
                               timeout=QUICK_TIMEOUT_SECONDS, record=False)
    graph = output.get("content")
    if not isinstance(graph, dict):
        raise WorkflowLibraryError("workflowLibErr_badAnswer", name=instance.name)
    return {"path": path, "content": graph}


# --- 改那台机器上的文件 ---------------------------------------------------------

def _write(db: Session, instance: PluginInstance, request: dict[str, Any], *, wanted: str) -> str:
    """一次写操作:交给插件,撞名翻成 WorkflowConflict;成了就让这个连接的目录重拉一遍。回改完之后的路径。"""
    output = tools.invoke_host(db, instance.id, WORKFLOW_LIBRARY, request, timeout=QUICK_TIMEOUT_SECONDS)
    if output.get("conflict") is True:
        suggestion = _text(output.get("suggestion"), 500)
        raise WorkflowConflict(wanted, suggestion if suggestion.lower().endswith(".json") else "")
    path = _text(output.get("path"), 600)
    if not path:
        raise WorkflowLibraryError("workflowLibErr_badAnswer", name=instance.name)
    # 生成选项、工具清单里的那张跟着变(新的一张、换了名字的、删掉的),不等那一分钟的指纹
    host_capabilities.notify(db, instance, refresh=True)
    return path


def copy(db: Session, instance: PluginInstance, path: str, new_path: str) -> dict[str, str]:
    """复制一张:存成 `new_path`(已有就撞名,不覆盖)。插件给副本换一个新的图 id —— 两张同 id 的图,工具名会撞。"""
    _require(db, instance)
    path, new_path = workflow_path(path), workflow_path(new_path)
    return {"path": _write(db, instance, {"op": "copy_workflow", "path": path, "new_path": new_path}, wanted=new_path)}


def rename(db: Session, instance: PluginInstance, path: str, new_path: str) -> dict[str, str]:
    """改名 / 挪目录(已有就撞名,不覆盖)。"""
    _require(db, instance)
    path, new_path = workflow_path(path), workflow_path(new_path)
    if path == new_path:
        return {"path": path}
    return {"path": _write(db, instance, {"op": "rename_workflow", "path": path, "new_path": new_path}, wanted=new_path)}


def trash(db: Session, instance: PluginInstance, path: str) -> dict[str, str]:
    """「删除」:挪进回收目录(ADR 0035 §3),不硬删。回回收目录里的路径。"""
    _require(db, instance)
    path = workflow_path(path)
    return {"path": _write(db, instance, {"op": "trash_workflow", "path": path}, wanted=path)}


def restore(db: Session, instance: PluginInstance, path: str, new_path: str = "") -> dict[str, str]:
    """从回收目录挪回去:默认回原处,原处被占了就撞名(界面要求换名,再带着 `new_path` 来)。"""
    _require(db, instance)
    path = trash_path(path)
    target = workflow_path(new_path) if new_path else _TRASH_PATH.match(path).group("original")  # type: ignore[union-attr]
    return {"path": _write(db, instance, {"op": "restore_workflow", "path": path, "new_path": target}, wanted=target)}


def register_uses() -> None:
    capabilities.register_use(capabilities.Use(WORKFLOW_LIBRARY, "app", fragment("capUse_workflowLibrary")))


#: 能力表里的 `workflow_library`(ADR 0035):不走挑法(每个连接各有各的工作流),登记它是为了叫得出名字、说得出用在哪。
CAPABILITY = capabilities.Capability(
    name=WORKFLOW_LIBRARY,
    label_key="capability_workflow_library",
    description_key="capability_workflow_library",
    pickable=False,
)


__all__ = [
    "CAPABILITY",
    "WorkflowConflict",
    "WorkflowLibraryError",
    "content",
    "copy",
    "library",
    "register_uses",
    "rename",
    "restore",
    "trash",
    "trash_path",
    "workflow_path",
]
