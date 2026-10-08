"""工作流库(ADR 0035):认领 `workflow_library` 的连接上存着哪些工作流 —— 宿主这一侧。

插件回答「这台服务器上存着哪些工作流、每张长什么样、缺什么」,替宿主改那台机器上的工作流文件(复制、改名、挪进 / 挪出
回收目录)。宿主做的是插件做不了、也不该做的:

- **规整**:插件报的每一条都过一遍(没有路径的丢掉、长文本截断、图摘要限量),界面拿到的形状只有一种;
- **它在 Mosael 里的样子**:这张工作流是不是这个连接下的一个生成模型(用它生成要它)、这个工作区里它最近的产出
  (用它生成的、当工具跑的,一批出的每一张都算;每张带着 NSFW 的判断,见「最近的产出」)、这个工作区里哪些工作流节点 /
  画板格子选的是它(引用表,见 db/references 的 `generation_model`);
- **路径先查一遍**:只认 `workflows/` 里的相对路径(`.json`,不带 `..`、反斜杠、控制字符和 Windows 不收的字符),
  回收目录里的只认插件报过的那种形状 —— 不交给插件猜;
- **改完马上刷新**:这个连接的生成目录和工具清单重拉一遍(`host_capabilities.notify(refresh=True)`),不等一分钟的指纹;
- **在哪里编辑**:插件可以报一个编辑器(种类 + 网页地址,「在编辑器里打开」用),这里只认简单的种类名和不带用户名密码
  的 http(s) 地址,不对就当没有。

**不覆盖**:复制、改名、恢复撞了名,插件回 `conflict` 和一个建议名,这里翻成 409(带着建议名),界面要求换名。

**文件夹**就是那台机器上 `workflows/` 里的子目录(和 ComfyUI 自己的侧栏同一份,宿主不另记):列出来的带着全部子目录
(空的也在);新建、改名 / 挪走、删除经插件,名字先在这里过一遍(和工作流路径同一套分段规则,不以 `.json` 结尾)。删除只删
**空的**:插件现查,里面还有文件就回 `not_empty`,这里翻成 409(`WorkflowFolderNotEmpty`,带着几个文件)—— 不一下子带走一整个
文件夹的工作流。改名、删除之后生成目录重拉(里面的工作流换了路径);新建不重拉(什么模型都没变)。

**导入**(ADR 0035 §5):要导入的东西只给一样(一段文字 / 一个文件 / 一个链接),太大的不交;插件认出来、换成界面格式,
这里规整预览(和列出来的每一张同一套);存进去和别的写操作同一套,原文以 JSON 字符串交给插件 —— 调用记录里只留截断的
一段,不把整张图存进记录。

**补齐缺的节点**:装节点包是一个后台任务(`node_install`,经插件交给 ComfyUI-Manager,进度照插件说的),装完要重启
ComfyUI 才加载;重启经插件(等它停下再起来),回来以后这个连接的目录重拉一遍。包名先在这里过一遍(几个、多长、没有控制字符)。

**应用表单**(ADR 0038 §2):作者从一张工作流全部能填的项里挑几项、起名、排序、收窄可选值,标哪个输出节点是结果,存进
那张工作流自己的 JSON。读(`app_form`)给编辑器全部能填的项、文件里的标记和读到时的改动时间;写(`annotate`)是 Mosael
**唯一覆盖写一张已有工作流**的地方:只改 `mosael` 那几处标记,带着读到时的改动时间去 —— 那台机器上的文件在这之间被改过,
插件不写、回 stale,这里翻成 409(`WorkflowStale`)。形状先在这里过一遍(根图上的节点号、几项、多长),界面每次都先确认。

**这里不认识 ComfyUI**:任何认领 `workflow_library` 的连接,插件页上都有「工作流库」。列表不存库,每次现问插件。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError, fragment, pick_text
from app.core.unit_of_work import unit_of_work
from app.db.models import (
    Asset,
    AssetNsfwMark,
    Board,
    GeneratedAsset,
    GenerationJob,
    GenerationSession,
    Job,
    PluginInstance,
    PluginInvocation,
    ProviderDefault,
    ProviderModel,
    ProviderProfile,
    ScheduledTask,
    User,
    Workflow,
)
from app.db.references import generation_model_key
from app.domain import capabilities, local_services
from app.domain.agent import places
from app.domain.boards.producer_ids import node_producer_id
from app.domain.jobs import create_job, dispatch_job, emit_job_event, finish_job, say
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm
from app.domain.plugins import generation as plugin_generation
from app.domain.plugins import host_capabilities
from app.domain.plugins import instances as inst
from app.domain.plugins import moves as plugin_moves
from app.domain.plugins import tools
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.manifest import GENERATION, TOOLS, WORKFLOW_LIBRARY
from app.domain.plugins.nodes import PLUGIN_NODE_PREFIX
from app.domain.plugins.runtime import PluginRuntimeError, StreamHooks
from app.domain.plugins.tools import MAX_GENERATION_TIMEOUT_SECONDS
from app.domain.providers import models as provider_models
from app.domain.providers import moved_models
from app.domain.references import referrers
from app.media.paths import resolve_key

logger = logging.getLogger(__name__)

#: 列一遍最多等多久:要取每张工作流、转一遍、再列一遍模型目录。
LIBRARY_TIMEOUT_SECONDS = 600
#: 取一张、存一张、挪一张:一两个请求的事。
QUICK_TIMEOUT_SECONDS = 120
#: 重启:插件等 ComfyUI 停下再起来,最多 4 分钟,再留一点余量。
REBOOT_TIMEOUT_SECONDS = 300
#: 装节点包的任务种类(见 job_catalog);工作流库列这个连接最近几次。
NODE_INSTALL_KIND = "node_install"
RECENT_INSTALLS = 5
_MAX_PACKS = 10

_MAX_WORKFLOWS = 2000
_MAX_LIST = 200
_MAX_GRAPH_NODES = 400
_MAX_GRAPH_LINKS = 1200
_MAX_GRAPH_GROUPS = 60
_MAX_USES = 50
#: 详情里「最近的产出」最多交几份(新的在前,一批出的几张都算);更早的在素材库里。
RECENT_OUTPUTS = 48
#: 往回翻几次运行:生成任务、工具调用各自最多这么多次。
_RECENT_RUNS = 40
_ROLES = {"input", "model", "sampler", "text", "output", "note", "missing", "other"}
#: Windows 上文件名里不能有的字符(那台 ComfyUI 可能在 Windows 上):路径段里一个都不收。
_BAD_SEGMENT = re.compile(r'[\x00-\x1f<>:"|?*\\]')
#: 回收目录里的一张:`.mosael-trash/workflows/<时刻>/<原来的相对路径>`(ADR 0035 §3)。
_TRASH_PATH = re.compile(r"^\.mosael-trash/workflows/\d{8}-\d{6}(-\d+)?/(?P<original>.+)$")
#: 要导入的东西最多多长(字符):文件是 base64,30 MB 的文件约 40 M 个字符。
MAX_IMPORT_CHARS = 40 * 1024 * 1024
_IMPORT_FORMATS = {"ui", "api"}
_IMPORT_SOURCES = {"json", "png", "webp", "zip", "url"}
#: 编辑器的种类名(界面按它决定怎么打开那一张,如 `comfyui`)。
_EDITOR_KIND = re.compile(r"[a-z][a-z0-9-]{0,39}")


class WorkflowLibraryError(LocalizedError, ValueError):
    """工作流库这一侧说不行(这个连接不提供工作流库、路径不对)。带文案 key(`workflowLibErr_*`)。"""


class WorkflowStale(WorkflowLibraryError):
    """要改的那张在那台服务器上被改过了(改动时间和读到时的对不上):应用表单没存,重新打开再改。"""

    def __init__(self, path: str, modified: float | None) -> None:
        super().__init__("workflowLibErr_stale", path=path)
        self.path = path
        self.modified = modified


class WorkflowFolderNotEmpty(WorkflowLibraryError):
    """要删的文件夹里还有文件(插件挪之前现查的):不删。先把里面的挪走或删掉(各自确认、各自能恢复)。"""

    def __init__(self, path: str, count: int) -> None:
        super().__init__("workflowLibErr_folderNotEmpty", path=path, count=str(count))
        self.path = path
        self.count = count


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


def folder_path(value: str) -> str:
    """`workflows/` 里的一个子目录:和工作流路径同一套分段规则,只是不以 `.json` 结尾(那像一张工作流)。不合格就拒。"""
    text = (value or "").strip()
    segments = text.split("/")
    if not text or text.lower().endswith(".json") or len(text) > 400 or any(
        not one or one in (".", "..") or one.startswith(".") or one != one.strip() or _BAD_SEGMENT.search(one)
        for one in segments
    ):
        raise WorkflowLibraryError("workflowLibErr_badFolder", path=text)
    return text


def _folders(raw: Any, workflows: list[dict[str, Any]]) -> list[str]:
    """左边那一列的文件夹:插件报的(空的也在)加上每张工作流所在的,连同各级上级;名字不像样的丢掉。按名字排。"""
    found: set[str] = set()
    for one in [*(raw if isinstance(raw, list) else []), *(flow["folder"] for flow in workflows)]:
        try:
            parts = folder_path(_text(one, 400)).split("/")
        except WorkflowLibraryError:
            continue
        found.update("/".join(parts[:depth]) for depth in range(1, len(parts) + 1))
    return sorted(found, key=lambda one: (one.lower(), one))[:_MAX_WORKFLOWS]


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
        # 输出节点给人看的名字(插件按语言给的 `label`:用户起的标题,没起就是 ComfyUI 给这类节点的名字),不是类名
        "outputs": [{**one, "title": _picked(source.get("label"), 200) or one["title"]}
                    for one, source in _outputs(raw.get("outputs"), {"node": 40, "title": 200, "media": 20})],
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
        "app": _app_summary(raw.get("app")),
    }


#: 表单(ADR 0038、0045):有没有标记、版本认不认。
_APP_STATUSES = {"none", "ok", "unsupported"}
#: 一张表最多几项、一项最多几个可选值、最多标几个结果、一张工作流最多几张表单;名字、标题、说明最长多少字(和插件那一侧
#: 同一套数)。
MAX_APP_ITEMS = 200
MAX_APP_CHOICES = 1000
MAX_APP_RESULTS = 64
MAX_FORMS = 20
_MAX_APP_LABEL = 120
_MAX_APP_DESCRIPTION = 1000
_GRAPH_ITEMS = {"seed", "size", "runs"}
#: 根图上的节点号(子图里面的节点 —— `12:5` 这种 —— 这一版不能放进表单)。
_ROOT_NODE = re.compile(r"\d{1,9}")
#: 一格输入的名字:不收控制字符,不太长。
_INPUT_NAME = re.compile(r"[^\x00-\x1f]{1,200}")
#: 表单 id:小写字母和数字,1–8 位(插件起的,只在一张工作流里唯一;ADR 0045 §1)。
_FORM_ID = re.compile(r"[a-z0-9]{1,8}")
#: 一张表单的模型 id、工具名最长多少(模型 id 和 provider_models.model_id 一样长)。
_MAX_FORM_MODEL = 160
_MAX_FORM_TOOL = 64


def _app_items(raw: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for one in raw if isinstance(raw, list) else []:
        if not isinstance(one, dict) or len(items) >= MAX_APP_ITEMS:
            continue
        node, name = _text(one.get("node"), 20), _text(one.get("input"), 200)
        if not name or (node and not _ROOT_NODE.fullmatch(node)):
            continue
        item: dict[str, Any] = {"key": f"{node}.{name}" if node else name, "node": node, "input": name,
                                "label": _text(one.get("label"), _MAX_APP_LABEL), "main": one.get("main") is True,
                                "title": _text(one.get("title"), 200), "problem": _text(one.get("problem"), 500)}
        if isinstance(one.get("choices"), list):
            item["choices"] = [str(choice)[:1000] for choice in one["choices"][:MAX_APP_CHOICES]
                               if isinstance(choice, (str, int, float)) and not isinstance(choice, bool)]
        items.append(item)
    return items


def _app_form(raw: Any) -> dict[str, Any] | None:
    """插件说的一张表单:id、标题、说明、每一项(对不上的带着原因)、几项有效 / 失效、它的模型 id 和工具名(说得出的话)。"""
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not _FORM_ID.fullmatch(raw["id"]):
        return None
    return {
        "id": raw["id"],
        "title": _text(raw.get("title"), _MAX_APP_LABEL),
        "description": _text(raw.get("description"), _MAX_APP_DESCRIPTION),
        "items": _app_items(raw.get("items")),
        "fields": int(_number(raw.get("fields")) or 0),
        "invalid": int(_number(raw.get("invalid")) or 0),
        "model": _text(raw.get("model"), _MAX_FORM_MODEL),
        "tool": _text(raw.get("tool"), _MAX_FORM_TOOL),
    }


def _app_summary(raw: Any) -> dict[str, Any] | None:
    """插件说的这张工作流的表单(有没有标记、版本、能不能升级、每张表单、标成结果的节点、对不上任何一张表单的标记几处),
    规整一遍。没说就是 None。"""
    if not isinstance(raw, dict):
        return None
    status = _text(raw.get("status"), 20)
    version = raw.get("version")
    forms = [one for one in (_app_form(item) for item in (raw.get("forms") or [])[:MAX_FORMS]
                             if isinstance(raw.get("forms"), list)) if one]
    return {
        "status": status if status in _APP_STATUSES else "none",
        "version": str(version)[:20] if isinstance(version, (int, float, str)) and not isinstance(version, bool) else "",
        "upgradable": raw.get("upgradable") is True,
        "forms": [one for index, one in enumerate(forms) if one["id"] not in {other["id"] for other in forms[:index]}],
        "results": [_text(one, 20) for one in raw.get("results") or []
                    if isinstance(one, str) and _ROOT_NODE.fullmatch(one)][:MAX_APP_RESULTS],
        "invalid": int(_number(raw.get("invalid")) or 0),
        "stray": int(_number(raw.get("stray")) or 0),
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
    """每张工作流在 Mosael 里的样子:是不是这个连接下的生成模型、这个工作区里它最近的那一份产出(卡片上的那一张,
    带着 NSFW 的判断)、谁在用它。"""
    profile = _profile(db, instance)
    rows = {row.model_id: row for row in provider_models.list_models(db, profile.id)} if profile is not None else {}
    mirrored = _mirroring_tools(instance)
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
        latest, _ = _produced(db, _runs(db, instance, profile, workspace_id, row.model_id,
                                       mirrored.get(row.model_id, []), limit=1), workspace_id, limit=1)
        flow["last_output"] = latest[0] if latest else None
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


def _editor(raw: Any) -> dict[str, str] | None:
    """插件说这些工作流在哪里编辑。地址会在桌面版的内嵌浏览器 / 网页版的新标签页里打开:只认 http(s)、有主机名、
    不带「用户名:密码@」(凭据不该出现在地址里,见插件的连接配置)。"""
    if not isinstance(raw, dict):
        return None
    kind, url = raw.get("kind"), raw.get("url")
    if not isinstance(kind, str) or not _EDITOR_KIND.fullmatch(kind) or not isinstance(url, str) or len(url) > 500:
        return None
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname or "@" in parts.netloc:
        return None
    return {"kind": kind, "url": url.strip()}


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
        "folders": _folders(output.get("folders"), workflows),
        "others": [one for one in _items(output.get("others"), {"path": 500, "reason": 2000}) if one["path"]],
        "trash": _trash(output.get("trash")),
        "manager": {"version": _text(manager.get("version"), 40)},
        "editor": _editor(output.get("editor")),
        "installs": node_installs(db, instance),
    }


# --- 最近的产出 ----------------------------------------------------------------

def _mirroring_tools(instance: PluginInstance) -> dict[str, list[str]]:
    """生成模型 id → 和它是同一件事的那几个工具(插件报的 `mirrors`)。工作流在工作流节点、智能体里是当工具跑的,产出记在
    工具调用上 —— 只看生成任务的话,维护者在工作流里跑出来的那几张在这里看不见。"""
    out: dict[str, list[str]] = {}
    for tool in instance.discovered_tools or []:
        mirror = tool.get("mirrors") if isinstance(tool, dict) else None
        if isinstance(mirror, dict) and mirror.get("generation_model") and tool.get("name"):
            out.setdefault(str(mirror["generation_model"]), []).append(str(tool["name"]))
    return out


def _runs(db: Session, instance: PluginInstance, profile: ProviderProfile, workspace_id: str, model_id: str,
          tools: list[str], *, limit: int) -> list[tuple[datetime, list[str]]]:
    """这张工作流最近的几次运行(新的在前):每次 `(什么时候, 交出的素材 id —— 一批几张都在)`。

    两种运行:用它**生成**(这个工作区、这个连接、这个模型的生成任务;每一份产出各有一行 GeneratedAsset,任务被「清空已结束」
    删掉的只剩封面那一张)和当**工具**跑(和它是同一件事的工具在这个连接上成功的调用,交出的 `asset_ids`;调用不记工作区,
    素材按工作区筛,见 _produced)。"""
    jobs = list(db.scalars(
        select(GenerationJob)
        .where(GenerationJob.workspace_id == workspace_id, GenerationJob.provider_profile_id == profile.id,
               GenerationJob.model == model_id, GenerationJob.result_asset_id.is_not(None))
        .order_by(GenerationJob.created_at.desc())
        .limit(limit)
    ))
    made: dict[str, list[str]] = {}
    job_ids = [job.job_id for job in jobs if job.job_id]
    if job_ids:
        for job_id, asset_id in db.execute(select(GeneratedAsset.job_id, GeneratedAsset.asset_id)
                                           .where(GeneratedAsset.job_id.in_(job_ids))):
            made.setdefault(str(job_id), []).append(str(asset_id))
    runs = [(job.created_at, made.get(job.job_id or "") or [str(job.result_asset_id)]) for job in jobs]
    if tools:
        calls = db.scalars(
            select(PluginInvocation)
            .where(PluginInvocation.instance_id == instance.id, PluginInvocation.tool_name.in_(tools),
                   PluginInvocation.status == "succeeded")
            .order_by(PluginInvocation.created_at.desc())
            .limit(limit)
        )
        for call in calls:
            ids = [one for one in (call.output or {}).get("asset_ids") or [] if isinstance(one, str) and one]
            if ids:
                runs.append((call.created_at, ids))
    runs.sort(key=lambda run: run[0], reverse=True)
    return runs


def _produced(db: Session, runs: list[tuple[datetime, list[str]]], workspace_id: str, *,
             limit: int) -> tuple[list[dict[str, Any]], bool]:
    """几次运行的产出摊成一串(新的运行在前,一次里按收进来的先后):这个工作区里还在的素材,每份带着种类和 NSFW 的判断。
    交回前 `limit` 份,和后面还有没有。"""
    wanted = list(dict.fromkeys(asset_id for _, ids in runs for asset_id in ids))
    if not wanted:
        return [], False
    assets = {asset.id: asset for asset in db.scalars(
        select(Asset).where(Asset.id.in_(wanted), Asset.workspace_id == workspace_id))}
    ordered: list[Asset] = []
    seen: set[str] = set()
    for _, ids in runs:
        for asset in sorted((assets[one] for one in ids if one in assets), key=lambda one: one.created_at):
            if asset.id not in seen:
                seen.add(asset.id)
                ordered.append(asset)
    shown = ordered[:limit]
    marks = {row.asset_id: row.nsfw for row in db.scalars(
        select(AssetNsfwMark).where(AssetNsfwMark.asset_id.in_([asset.id for asset in shown])))} if shown else {}
    return [{"asset_id": asset.id, "kind": asset.kind, "created_at": asset.created_at,
             "nsfw": _output_nsfw(asset, marks.get(asset.id))} for asset in shown], len(ordered) > limit


def _output_nsfw(asset: Asset, manual: bool | None) -> dict[str, Any]:
    """一份产出算不算 NSFW —— 和模型预览图同一套判断(model_library.nsfw_verdict):手动标的压过一切;没标时看本机识别
    (这一张图的原文件,按内容记结果;权重没下、还没算过就没有这一条,下次列出就有)。视频、音频只认手动标记:为了识别去读
    整段视频算哈希,不值。"""
    from app.domain import model_library, model_nsfw_local

    signals: list[dict[str, Any]] = []
    if asset.kind == "image" and asset.file_key:
        path = resolve_key(asset.file_key)
        if path.is_file():
            kind = f"image/{path.suffix.lstrip('.').lower() or 'png'}"
            found = model_nsfw_local.signal(model_nsfw_local.Source(original=path, kind=kind))
            if found is not None:
                signals.append(found)
    return model_library.nsfw_verdict(manual, signals)


def outputs(db: Session, user: User, instance: PluginInstance, *, workspace_id: str, path: str) -> dict[str, Any]:
    """一张工作流在这个工作区里最近的产出(详情里那一组图):用它生成的、当工具跑的,一批出的每一张都算,新的在前,
    最多 RECENT_OUTPUTS 份;每份带着 NSFW 的判断。不是这个连接下的生成模型的,没有。"""
    ensure_workspace_access(db, user, workspace_id)
    _require(db, instance)
    path = workflow_path(path)
    profile = _profile(db, instance)
    if profile is None or provider_models.get_model(db, profile.id, path) is None:
        return {"outputs": [], "more": False}
    runs = _runs(db, instance, profile, workspace_id, path, _mirroring_tools(instance).get(path, []), limit=_RECENT_RUNS)
    found, more = _produced(db, runs, workspace_id, limit=RECENT_OUTPUTS)
    return {"outputs": found, "more": more}


def mark_output_nsfw(db: Session, user: User, instance: PluginInstance, *, workspace_id: str, asset_id: str,
                     nsfw: bool | None) -> dict[str, Any]:
    """手动标一份产出是不是 NSFW(`None` 是去掉标记,回到本机识别)。回新的判断。和模型库里标模型预览图同一件事,
    标在素材上(AssetNsfwMark)。只认这个工作区里的素材。"""
    ensure_workspace_access(db, user, workspace_id)
    _require(db, instance)
    asset = db.get(Asset, asset_id)
    if asset is None or asset.workspace_id != workspace_id:
        raise WorkflowLibraryError("workflowLibErr_outputGone")
    row = db.get(AssetNsfwMark, asset.id)
    if nsfw is None:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(AssetNsfwMark(asset_id=asset.id, nsfw=nsfw, marked_by=user.id))
    else:
        row.nsfw, row.marked_by = nsfw, user.id
    db.flush()
    return _output_nsfw(asset, nsfw)


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

def _fits(suggestion: str, *, folder: bool) -> bool:
    """插件给的建议名像不像样(文件夹名 / 工作流路径):不像样就不给,界面让人自己换。"""
    try:
        (folder_path if folder else workflow_path)(suggestion)
    except WorkflowLibraryError:
        return False
    return True


def _write(db: Session, instance: PluginInstance, request: dict[str, Any], *, wanted: str, folder: bool = False,
           refresh: bool = True, follow: Callable[[dict[str, Any]], None] | None = None) -> str:
    """一次写操作:交给插件,撞名翻成 WorkflowConflict、要删的文件夹不空翻成 WorkflowFolderNotEmpty;成了先 `follow`(改名时
    把存着的引用跟过去,见 _follow_moved),再让这个连接的目录重拉一遍(`refresh`,新建空文件夹什么模型都没变就不拉)。回改完
    之后的路径。"""
    output = tools.invoke_host(db, instance.id, WORKFLOW_LIBRARY, request, timeout=QUICK_TIMEOUT_SECONDS)
    if output.get("conflict") is True:
        suggestion = _text(output.get("suggestion"), 500)
        raise WorkflowConflict(wanted, suggestion if _fits(suggestion, folder=folder) else "")
    if output.get("not_empty") is True:
        raise WorkflowFolderNotEmpty(wanted, max(1, int(_number(output.get("count")) or 1)))
    path = _text(output.get("path"), 600)
    if not path:
        raise WorkflowLibraryError("workflowLibErr_badAnswer", name=instance.name)
    if follow is not None:
        follow(output)
    if refresh:
        # 生成选项、工具清单里的那张跟着变(新的一张、换了名字的、删掉的),不等那一分钟的指纹
        host_capabilities.notify(db, instance, refresh=True)
    return path


def copy(db: Session, instance: PluginInstance, path: str, new_path: str) -> dict[str, str]:
    """复制一张:存成 `new_path`(已有就撞名,不覆盖)。插件给副本换一个新的图 id —— 两张同 id 的图,工具名会撞。"""
    _require(db, instance)
    path, new_path = workflow_path(path), workflow_path(new_path)
    return {"path": _write(db, instance, {"op": "copy_workflow", "path": path, "new_path": new_path}, wanted=new_path)}


#: 一次改名最多跟着改多少个名字(一个文件夹里的几十张,每张几个入口)
_MAX_FOLLOWED = 1000


def _pairs(raw: Any) -> dict[str, str]:
    """插件报的一串 `{from, to}` 收成「旧名字 → 新名字」:都是像样的字符串、不一样;认不出的丢掉。"""
    found: dict[str, str] = {}
    for entry in raw[:_MAX_FOLLOWED] if isinstance(raw, list) else []:
        source = entry.get("from") if isinstance(entry, dict) else None
        target = entry.get("to") if isinstance(entry, dict) else None
        if isinstance(source, str) and isinstance(target, str) and source.strip() and target.strip() \
                and source != target and len(source) <= 600 and len(target) <= 600:
            found.setdefault(source.strip(), target.strip())
    return found


def _follow_moved(db: Session, instance: PluginInstance) -> Callable[[dict[str, Any]], None]:
    """在工作流库里改了名、挪了目录:指着旧路径的引用当场跟过去(ADR 0045 修订之二 D2–D4,维护者 2026-10-09 按推荐拍板)。

    插件在改名的回答里报 `moved`(模型 id 和工具名各一串,插件知道一张图有几个入口、工具名怎么起);这里在**同一个请求里、
    目录重拉之前**照做 —— 反过来,重拉先把旧名字那几行模型删了,就无处可改。和插件报的一次性改名走同一套:模型行原地改名
    (默认模型、停用跟着走),各领域改它们存着的 (连接, 模型) 引用(生成会话、生成记录和产出、任务回执、用量、定时任务、
    画板、工作流 —— 历史记录也改,工作流落一版 `rename` 修订);工具开关跟着新名字,工作流里用那个工具的插件节点改到新名字。

    - 不记一次性改名的账(`applied_moves`):那本账是插件报的、每个旧名字只做一次的改名;这里每次都不一样,照做就是了。账上
      做过的旧名字换了地方,新名字也算做过(plugins.moves.follow_renames)—— 不然下一次刷新又把跟过去的引用改走一次。
    - 改不成(D3):引用的改动整批撤掉(保存点),文件改名照样算成功,记一条日志 —— 不让引用的改写拖垮用户要的改名;引用停在
      旧名字上,会说清楚「工作流不在了」。
    - 只改这条连接的(D4):另一条连接哪怕指着同一台 ComfyUI,也是另一套目录。
    - 直接在 ComfyUI 里改名的(D5)宿主不知道,这一版不管。"""

    def follow(output: dict[str, Any]) -> None:
        moved = output.get("moved") if isinstance(output.get("moved"), dict) else {}
        models_moved, tools_moved = _pairs(moved.get("models")), _pairs(moved.get("tools"))
        if not models_moved and not tools_moved:
            return
        profile = _profile(db, instance)
        try:
            with db.begin_nested():
                if models_moved and profile is not None:
                    moved_models.apply(db, profile, models_moved, why=moved_models.RENAMED)
                    plugin_moves.follow_renames(db, instance, GENERATION, models_moved)
                if tools_moved:
                    inst.carry_capabilities(db, instance, tools_moved)
                    plugin_moves.tools_moved(db, instance, tools_moved, why=moved_models.RENAMED)
                    plugin_moves.follow_renames(db, instance, TOOLS, tools_moved)
        except Exception:  # noqa: BLE001 — 跟着改引用的那一侧出错,不让文件改名本身失败
            logger.exception("连接 %s 在工作流库里改了名,跟着改引用没做成(引用停在旧名字上,改名照样算成功)", instance.id)

    return follow


def rename(db: Session, instance: PluginInstance, path: str, new_path: str) -> dict[str, str]:
    """改名 / 挪目录(已有就撞名,不覆盖)。指着旧路径的引用当场跟过去(见 _follow_moved);在这张里开的对话,家跟着挪
    (ADR 0044 §9)。"""
    _require(db, instance)
    path, new_path = workflow_path(path), workflow_path(new_path)
    if path == new_path:
        return {"path": path}
    done = _write(db, instance, {"op": "rename_workflow", "path": path, "new_path": new_path}, wanted=new_path,
                  follow=_follow_moved(db, instance))
    places.follow_library_move(db, instance, path, done)
    return {"path": done}


def trash(db: Session, instance: PluginInstance, path: str) -> dict[str, str]:
    """「删除」:挪进回收目录(ADR 0035 §3),不硬删。回回收目录里的路径。在这张里开的对话,家跟着进回收目录 —— 恢复时
    一起回来(ADR 0044 §9)。"""
    _require(db, instance)
    path = workflow_path(path)
    done = _write(db, instance, {"op": "trash_workflow", "path": path}, wanted=path)
    places.follow_library_move(db, instance, path, done)
    return {"path": done}


def restore(db: Session, instance: PluginInstance, path: str, new_path: str = "") -> dict[str, str]:
    """从回收目录挪回去:默认回原处,原处被占了就撞名(界面要求换名,再带着 `new_path` 来)。"""
    _require(db, instance)
    path = trash_path(path)
    target = workflow_path(new_path) if new_path else _TRASH_PATH.match(path).group("original")  # type: ignore[union-attr]
    done = _write(db, instance, {"op": "restore_workflow", "path": path, "new_path": target}, wanted=target)
    places.follow_library_move(db, instance, path, done)
    return {"path": done}


# --- 文件夹 -------------------------------------------------------------------------

def make_folder(db: Session, instance: PluginInstance, path: str) -> dict[str, str]:
    """新建一个文件夹(可以带上级)。已经有了撞名 409,带一个建议名。"""
    _require(db, instance)
    path = folder_path(path)
    return {"path": _write(db, instance, {"op": "make_folder", "path": path}, wanted=path, folder=True, refresh=False)}


def rename_folder(db: Session, instance: PluginInstance, path: str, new_path: str) -> dict[str, str]:
    """文件夹改名,或挪到别的文件夹里:里面的工作流跟着换路径(生成目录重拉),指着它们旧路径的引用当场跟过去(见
    _follow_moved),在它们里面开的对话家也跟着挪。目标已经有了撞名 409,不合并进去。"""
    _require(db, instance)
    path, new_path = folder_path(path), folder_path(new_path)
    if path == new_path:
        return {"path": path}
    if new_path.lower().startswith(path.lower() + "/"):
        raise WorkflowLibraryError("workflowLibErr_folderIntoItself", path=path)
    request = {"op": "rename_folder", "path": path, "new_path": new_path}
    done = _write(db, instance, request, wanted=new_path, folder=True, follow=_follow_moved(db, instance))
    places.follow_library_move(db, instance, path, done, folder=True)
    return {"path": done}


def trash_folder(db: Session, instance: PluginInstance, path: str) -> dict[str, str]:
    """删除一个文件夹:只删空的,挪进回收目录(ComfyUI 删不了目录,Mosael 也不硬删)。插件现查,里面还有文件就 409。"""
    _require(db, instance)
    path = folder_path(path)
    return {"path": _write(db, instance, {"op": "trash_folder", "path": path}, wanted=path, folder=True)}


# --- 应用表单(ADR 0038 §2)----------------------------------------------------------

_ITEM_KINDS = {"text", "media", "model", "number", "choice", "toggle", "seed", "size", "runs"}
#: 编辑器一次最多列多少项(一张工作流 115 项是见过的最多的)。
_MAX_APP_FOUND = 1000


def _picked(value: Any, limit: int) -> str:
    """一段给人看的字:按看的人的语言挑好(`{"zh", "en"}`),或者本来就是一句。"""
    return _text(pick_text(value) if isinstance(value, dict) else value, limit)


def _app_item(raw: Any, text: Any) -> dict[str, Any] | None:
    """编辑器要的一项能填的项:锚点、种类、名字(按看的人的语言挑好)、节点是谁(给人看的节点名、类名)、ComfyUI 给这一格的
    说明、常用与否、JSON Schema 片段(和生成目录同一套规整,见 plugins/generation.parameters —— 预览和真的表单是同一个形状)。"""
    if not isinstance(raw, dict):
        return None
    node, name, kind = _text(raw.get("node"), 40), _text(raw.get("input"), 200), _text(raw.get("kind"), 20)
    if not name or kind not in _ITEM_KINDS:
        return None
    key = f"{node}.{name}" if node else name
    title = raw.get("title")
    item: dict[str, Any] = {
        "key": key, "node": node, "input": name, "kind": kind,
        "title": _picked(title, 200) or key,
        "node_title": _text(raw.get("node_title"), 200),
        "node_label": _picked(raw.get("node_label"), 200),
        "hint": _picked(raw.get("hint"), 500),
        "class_type": _text(raw.get("class_type"), 200),
        "common": raw.get("common") is True,
        "role": _text(raw.get("role"), 40),
        "media": _text(raw.get("media"), 20),
        "folder": _text(raw.get("folder"), 64),
        # 子图里面的节点(`12:5`)这一版不能放进应用表单(ADR 0038「这一版不做」),照样列出来、标着
        "exposable": not node or bool(_ROOT_NODE.fullmatch(node)),
    }
    if isinstance(raw.get("schema"), dict):
        schema = plugin_generation.parameters({key: raw["schema"]}, text).get(key)
        if schema is not None:
            item["spec"] = {field: pick_text(value) if isinstance(value, dict) and field in ("title", "description")
                              else value for field, value in schema.items()}
    return item


def app_form(db: Session, instance: PluginInstance, path: str) -> dict[str, Any]:
    """一张工作流的应用表单,给编辑器(工作流库详情里的「应用」):这张图全部能填的项、交回结果的输出节点、文件里的标记
    (对不上的带着原因)、读到时的改动时间(存的时候带回来)。"""
    _require(db, instance)
    path = workflow_path(path)
    output = tools.invoke_host(db, instance.id, WORKFLOW_LIBRARY, {"op": "app", "path": path},
                               timeout=QUICK_TIMEOUT_SECONDS, record=False)
    return _app_answer(db, instance, output, path)


def _app_answer(db: Session, instance: PluginInstance, output: dict[str, Any], path: str, *,
                live: bool = False) -> dict[str, Any]:
    if not isinstance(output.get("items"), list):
        raise WorkflowLibraryError("workflowLibErr_badAnswer", name=instance.name)
    text = inst.manifest_for(db, instance).text
    items = [one for one in (_app_item(raw, text) for raw in output["items"][:_MAX_APP_FOUND]) if one]
    return {
        "path": path,
        "modified": _number(output.get("modified")) if path and not live else None,
        "kind": _text(output.get("kind"), 20),
        "editable": output.get("editable") is True,
        "items": items,
        "outputs": [{**one, "label": _picked(source.get("label"), 200) or one["title"]}
                    for one, source in _outputs(output.get("outputs"), {"node": 40, "title": 200, "class_type": 200,
                                                                        "media": 20})],
        "names": _node_names(output.get("names")),
        "app": _app_summary(output.get("app")) or _app_summary({"status": "none"}),
    }


#: 一张图最多报多少个节点的名字(一张大工作流几百个节点;再多的不报,界面退回节点号前的类名)。
_MAX_NAMED_NODES = 2000


def _node_names(value: Any) -> dict[str, str]:
    """插件报的每个节点给人看的名字(按看的人的语言挑好):节点号 → 名字。工作台「运行与结果」说节点用它。"""
    if not isinstance(value, dict):
        return {}
    named = ((_text(node, 40), _picked(name, 200)) for node, name in list(value.items())[:_MAX_NAMED_NODES])
    return {node: name for node, name in named if node and name}


def _outputs(value: Any, keys: dict[str, int]) -> list[tuple[dict[str, str], dict[str, Any]]]:
    """输出节点:规整过的那几格(`keys`),连同插件原样给的那一条(给人看的节点名 `label` 按语言分,要另挑)。"""
    raw = [one for one in value if isinstance(one, dict)] if isinstance(value, list) else []
    clean = [(_items([one], keys), one) for one in raw]
    return [(found[0], one) for found, one in clean if found][:_MAX_LIST]


def _too_big() -> WorkflowLibraryError:
    return WorkflowLibraryError("workflowLibErr_appTooBig", items=str(MAX_APP_ITEMS), choices=str(MAX_APP_CHOICES),
                                results=str(MAX_APP_RESULTS))


def _results_payload(results: list[str]) -> list[str]:
    if len(results) > MAX_APP_RESULTS:
        raise _too_big()
    for one in results:
        if not _ROOT_NODE.fullmatch(one):
            raise WorkflowLibraryError("workflowLibErr_badAppItem", item=one[:200])
    return results


def _form_payload(form: dict[str, Any]) -> dict[str, Any]:
    """要写进去的一张表单先在这里过一遍:id(新表单不给)、几项、每项是根图上的节点(或图级的种子 / 尺寸 / 跑几遍)、
    名字多长、可选值几个。"""
    form_id = str(form.get("id") or "")
    if form_id and not _FORM_ID.fullmatch(form_id):
        raise WorkflowLibraryError("workflowLibErr_badFormId", form=form_id[:40])
    entries = form.get("items") or []
    if not isinstance(entries, list) or len(entries) > MAX_APP_ITEMS:
        raise _too_big()
    clean: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        node = str(entry.get("node") or "") if isinstance(entry, dict) else ""
        name = str(entry.get("input") or "") if isinstance(entry, dict) else ""
        key = f"{node}.{name}" if node else name
        if not isinstance(entry, dict) or not _INPUT_NAME.fullmatch(name) or key in seen or (
                node and not _ROOT_NODE.fullmatch(node)) or (not node and name not in _GRAPH_ITEMS):
            raise WorkflowLibraryError("workflowLibErr_badAppItem", item=key[:200])
        seen.add(key)
        item: dict[str, Any] = {"node": node, "input": name, "label": _text(entry.get("label"), _MAX_APP_LABEL)}
        if node and entry.get("main") is True:
            item["main"] = True
        choices = entry.get("choices")
        if node and isinstance(choices, list) and choices:
            if len(choices) > MAX_APP_CHOICES:
                raise _too_big()
            item["choices"] = [str(one)[:1000] for one in choices
                               if isinstance(one, (str, int, float)) and not isinstance(one, bool)]
        clean.append(item)
    return {**({"id": form_id} if form_id else {}), "title": _text(form.get("title"), _MAX_APP_LABEL),
            "description": _text(form.get("description"), _MAX_APP_DESCRIPTION), "items": clean}


def _forms_payload(forms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """要写进去的**全部**表单(ADR 0045 §7:编辑器每次交全部表单,没给 id 的是新表单,插件起 id):张数、id 不重复、每张过一遍。"""
    if len(forms) > MAX_FORMS:
        raise WorkflowLibraryError("workflowLibErr_tooManyForms", max=str(MAX_FORMS))
    clean = [_form_payload(one) for one in forms]
    ids = [one["id"] for one in clean if "id" in one]
    if len(ids) != len(set(ids)):
        raise WorkflowLibraryError("workflowLibErr_badFormId", form=next(one for one in ids if ids.count(one) > 1))
    return clean


def annotate(db: Session, instance: PluginInstance, path: str, *, modified: float, forms: list[dict[str, Any]],
             results: list[str]) -> dict[str, Any]:
    """改那台服务器上一张工作流的表单和结果标记:**只改 `mosael` 那几处**,带着读到时的改动时间去(`modified`)。
    `forms` 是**全部**表单(按要列出来的顺序;没给 id 的是新表单;空列表 = 一张都不要)。那张在这之间被改过就不写
    (`WorkflowStale`,翻成 409)。成了让这个连接的目录马上重拉一遍(生成表单、工具跟着变),回写完之后的改动时间(接着改
    用它)。界面每次都先确认:写明哪台服务器上的哪个文件、只改这几处标记。"""
    _require(db, instance)
    path = workflow_path(path)
    results = _results_payload([str(one) for one in results])
    clean = _forms_payload(forms)
    output = tools.invoke_host(db, instance.id, WORKFLOW_LIBRARY,
                               {"op": "annotate", "path": path, "modified": modified, "forms": clean, "results": results},
                               timeout=QUICK_TIMEOUT_SECONDS)
    if output.get("stale") is True:
        raise WorkflowStale(path, _number(output.get("modified")))
    if _text(output.get("path"), 600) != path:
        raise WorkflowLibraryError("workflowLibErr_badAnswer", name=instance.name)
    # 生成选项、工具清单跟着变(表单入口多了 / 少了、名字换成作者起的),不等那一分钟的指纹
    host_capabilities.notify(db, instance, refresh=True)
    return {"path": path, "modified": _number(output.get("modified"))}


#: 一次最多改写几张(和插件那一侧同一个数)。
MAX_UPGRADES = 1000


def upgrade_marks(db: Session, instance: PluginInstance, paths: list[dict[str, Any]]) -> dict[str, Any]:
    """把这个连接上上一版格式的表单标记改写成这一版(ADR 0045 §7「查看并升级」,维护者在弹窗里确认过一次):插件逐张读、
    只改 `mosael` 那几处、带着读到时的改动时间覆盖写回 —— 那台机器上在这之间改过的那张跳过。改完让这个连接的目录马上重拉
    (表单入口出来、一次性的改名照做),回改成了几张、跳过的是哪几张。"""
    _require(db, instance)
    if len(paths) > MAX_UPGRADES:
        raise WorkflowLibraryError("workflowLibErr_tooManyUpgrades", max=str(MAX_UPGRADES))
    wanted = [{"path": workflow_path(str(one.get("path") or "")), "modified": one.get("modified")} for one in paths]
    output = tools.invoke_host(db, instance.id, WORKFLOW_LIBRARY, {"op": "upgrade_marks", "paths": wanted},
                               timeout=LIBRARY_TIMEOUT_SECONDS)
    asked = {one["path"] for one in wanted}

    def listed(key: str) -> list[str]:
        return [one for one in output.get(key) or [] if isinstance(one, str) and one in asked]

    failed = [{"path": one["path"], "reason": _text(one.get("reason"), 2000)} for one in output.get("failed") or []
              if isinstance(one, dict) and one.get("path") in asked]
    if listed("upgraded"):
        host_capabilities.notify(db, instance, refresh=True)
    return {"upgraded": listed("upgraded"), "stale": listed("stale"), "skipped": listed("skipped"), "gone": listed("gone"),
            "failed": failed}


#: 一张表单最多列多少处在用它。
_MAX_FORM_USES = 50


def _count_uses(value: Any, profile_id: str, model: str, node_type: str, instance_id: str) -> int:
    """一份存着的数据(工作流的图、画板的画布,任意嵌套)里指着这张表单的有几处:选它做生成模型的(连接 + 模型 id,或者
    `<连接>:<种类>:<模型 id>` 这种生成选项 id)、用它的工具的节点(节点类型;没选连接的节点哪台都算)、画板格子上的能力和
    生成器。"""
    if isinstance(value, list):
        return sum(_count_uses(one, profile_id, model, node_type, instance_id) for one in value)
    if isinstance(value, str):
        return int(bool(model) and value.startswith(f"{profile_id}:") and value.endswith(f":{model}")
                   and value.count(":") >= 2 and value.split(":", 2)[2] == model)
    if not isinstance(value, dict):
        return 0
    own = 0
    if model and value.get("provider_profile_id") == profile_id and value.get("model") == model:
        own = 1
    elif node_type and value.get("type") == node_type and str((value.get("config") or {}).get("instance_id") or "") in (
            "", instance_id):
        own = 1
    elif node_type and value.get("producer") == node_producer_id(node_type):
        own = 1
    abilities = value.get("abilities")
    if node_type and isinstance(abilities, dict) and node_producer_id(node_type) in abilities:
        own += 1
    return own + sum(_count_uses(one, profile_id, model, node_type, instance_id) for key, one in value.items()
                     if key not in ("abilities", "producer", "type", "model", "provider_profile_id"))


def form_usages(db: Session, user: User, instance: PluginInstance, *, workspace_id: str, model: str,
                tool: str) -> list[dict[str, Any]]:
    """一张表单在这个工作区里被哪些地方用着(删表单之前说给作者听,ADR 0045 §7):画板(选它生成的格子、用它的工具的能力
    和生成器)、工作流(生成节点、用它的工具的节点)、AI Studio 的生成会话、定时任务(载荷里选着它的),外加问的这个人在设置里
    把它定成了哪几种默认模型(默认模型按人记,不按工作区)。`model` / `tool` 是插件说的这张表单的模型 id 和工具名(工作流库 `app`
    的回答里有)。删了之后那几处会说「这张表单已经没了」,不悄悄换成完整工作流。"""
    ensure_workspace_access(db, user, workspace_id)
    _require(db, instance)
    profile = _profile(db, instance)
    profile_id = profile.id if profile is not None else ""
    model = model if profile_id else ""
    node_type = f"{PLUGIN_NODE_PREFIX}{instance.package_id}.{tool}" if tool else ""
    if not model and not node_type:
        return []
    needles = [one for one in (model, node_type) if one]
    uses: list[dict[str, Any]] = []
    for board in db.scalars(select(Board).where(Board.workspace_id == workspace_id).order_by(Board.name)):
        if any(needle in json.dumps(board.canvas, ensure_ascii=False) for needle in needles):
            count = _count_uses(board.canvas, profile_id, model, node_type, instance.id)
            if count:
                uses.append({"kind": "board", "id": board.id, "name": board.name, "count": count})
    for workflow in db.scalars(select(Workflow).where(Workflow.workspace_id == workspace_id).order_by(Workflow.name)):
        if any(needle in json.dumps(workflow.graph, ensure_ascii=False) for needle in needles):
            count = _count_uses(workflow.graph, profile_id, model, node_type, instance.id)
            if count:
                uses.append({"kind": "workflow", "id": workflow.id, "name": workflow.name, "count": count})
    if model:
        sessions = db.scalars(select(GenerationSession).where(
            GenerationSession.workspace_id == workspace_id, GenerationSession.provider_profile_id == profile_id,
            GenerationSession.model == model).order_by(GenerationSession.updated_at.desc()))
        from app.domain.generation.origins import describe_origins

        #: 别处开的会话标题空着(ADR 0052):叫它那一处现在的名字
        uses += [{"kind": "session", "id": session.id, "name": session.title or session.origin_name, "count": 1}
                 for session in describe_origins(db, user, sessions)]
    for task in db.scalars(select(ScheduledTask).where(ScheduledTask.workspace_id == workspace_id).order_by(ScheduledTask.name)):
        if any(needle in json.dumps(task.payload, ensure_ascii=False) for needle in needles):
            count = _count_uses(task.payload, profile_id, model, node_type, instance.id)
            if count:
                uses.append({"kind": "task", "id": task.id, "name": task.name, "count": count})
    if model:
        row = db.scalar(select(ProviderModel).where(ProviderModel.provider_profile_id == profile_id,
                                                    ProviderModel.model_id == model))
        if row is not None:
            defaults = db.scalars(select(ProviderDefault).where(ProviderDefault.provider_model_id == row.id,
                                                                ProviderDefault.owner_user_id == user.id)
                                  .order_by(ProviderDefault.capability))
            uses += [{"kind": "default", "id": one.capability, "name": one.capability, "count": 1} for one in defaults]
    return uses[:_MAX_FORM_USES]


# --- 工作台(ADR 0038 §3、§6)------------------------------------------------------
#
# 画布是那台 ComfyUI 自己的,开在桌面版的内嵌视图里;主进程注入的桥把画布上**现在这张**(含没存的改动)导出来,界面交到这里。
# 这几样不写那台机器上的文件:应用表单改的是画布上的节点(经桥),存盘是 ComfyUI 自己的保存;运行建的是一个普通的生成任务。
# 从页面拿到的一律先规整:界面格式要有 `nodes`、API 图每个节点要有 `class_type` 和 `inputs`、整张有大小上限。

#: 前端的 clientId(ComfyUI 前端自己生成的 uuid):认不出就不带,插件用自己的。
_CLIENT_ID = re.compile(r"[A-Za-z0-9_-]{1,100}")


def _canvas(content: Any) -> dict[str, Any]:
    """画布上的那张(界面格式):有 `nodes`、不超过导入的上限。"""
    if not isinstance(content, dict) or not isinstance(content.get("nodes"), list):
        raise WorkflowLibraryError("workflowLibErr_canvasNotUi")
    if len(json.dumps(content, ensure_ascii=False)) > MAX_IMPORT_CHARS:
        raise WorkflowLibraryError("workflowLibErr_canvasTooBig", mb=str(MAX_IMPORT_CHARS // (1024 * 1024)))
    return content


def app_live(db: Session, instance: PluginInstance, content: dict[str, Any], path: str = "") -> dict[str, Any]:
    """工作台的「表单」页签:画布上现在这张的表单 —— 全部能填的项、交回结果的输出节点、画布上的标记。和读文件的
    `app_form` 同一个形状,没有改动时间(改的是画布,不是文件)。`path` 是画布开的是哪张:插件据此说出每张表单的模型 id 和
    工具名(删表单前数「Mosael 里有几处在用它」)。"""
    _require(db, instance)
    path = workflow_path(path) if path else ""
    output = tools.invoke_host(db, instance.id, WORKFLOW_LIBRARY,
                               {"op": "app", "content": _canvas(content), **({"path": path} if path else {})},
                               timeout=QUICK_TIMEOUT_SECONDS, record=False)
    return _app_answer(db, instance, output, path, live=True)


#: 一个节点上的 Mosael 标记最大多大(一张应用表单最多 200 项、每项最多 1000 个可选值,放在一个节点上也够)。
_MAX_MARK_CHARS = 2 * 1024 * 1024


def app_marks(db: Session, instance: PluginInstance, content: dict[str, Any], *, forms: list[dict[str, Any]],
              results: list[str]) -> dict[str, Any]:
    """表单和结果标记写进画布要改成的样子(工作台的「表单」页签、「以后只要这张」):`forms` 是**全部**表单(没给 id 的是
    新表单),插件按和 `annotate` 同一个函数算,交回每个带标记的根图节点上的 `properties.mosael` 和图上的 `extra.mosael`
    (新表单的 id 在里面);界面经桥改画布上的节点,存盘是 ComfyUI 自己的保存。插件交回的先规整:只认根图节点号、值是
    对象、大小有上限。"""
    _require(db, instance)
    results = _results_payload([str(one) for one in results])
    clean = _forms_payload(forms)
    output = tools.invoke_host(db, instance.id, WORKFLOW_LIBRARY,
                               {"op": "app_marks", "content": _canvas(content), "forms": clean, "results": results},
                               timeout=QUICK_TIMEOUT_SECONDS, record=False)
    raw_nodes, extra = output.get("nodes"), output.get("extra")
    if not isinstance(raw_nodes, dict) or not (extra is None or isinstance(extra, dict)):
        raise WorkflowLibraryError("workflowLibErr_badMarks", name=instance.name)
    nodes: dict[str, Any] = {}
    for node, marks in raw_nodes.items():
        if not isinstance(node, str) or not _ROOT_NODE.fullmatch(node) or not isinstance(marks, dict) \
                or len(json.dumps(marks, ensure_ascii=False)) > _MAX_MARK_CHARS:
            raise WorkflowLibraryError("workflowLibErr_badMarks", name=instance.name)
        nodes[node] = marks
    if extra is not None and len(json.dumps(extra, ensure_ascii=False)) > _MAX_MARK_CHARS:
        raise WorkflowLibraryError("workflowLibErr_badMarks", name=instance.name)
    return {"nodes": nodes, "extra": extra}


def _api_graph(prompt: Any) -> dict[str, Any]:
    """画布导出的 API 图(`graphToPrompt` 的 `output`):节点号 → `{class_type, inputs}`,不超过上限。"""
    if not isinstance(prompt, dict) or not prompt or len(prompt) > 5000 or not all(
            isinstance(key, str) and isinstance(node, dict) and isinstance(node.get("class_type"), str)
            and isinstance(node.get("inputs"), dict) for key, node in prompt.items()):
        raise WorkflowLibraryError("workflowLibErr_canvasBadPrompt")
    if len(json.dumps(prompt, ensure_ascii=False)) > MAX_IMPORT_CHARS:
        raise WorkflowLibraryError("workflowLibErr_canvasTooBig", mb=str(MAX_IMPORT_CHARS // (1024 * 1024)))
    return prompt


def run_canvas(db: Session, user: User, instance: PluginInstance, *, workspace_id: str, path: str,
               prompt: dict[str, Any], workflow: dict[str, Any] | None, client_id: str,
               project_id: str | None = None) -> tuple[GenerationJob, Job]:
    """工作台的「运行」(ADR 0038 §6):跑画布上现在这张(含没存的改动)。建一个**普通的生成任务** —— 模型是这张工作流
    (`path`,得已经是这个连接下的生成模型:新建的要先在 ComfyUI 里存一次),图放在任务的载荷里(不进生成参数),插件
    提交它、`client_id` 用前端的那个、按历史轮询跟到完成。取消、重启后接着等、用量、素材入库都是生成任务已有的那一套。"""
    from app.domain.generation.origins import COMFYUI, Origin
    from app.domain.generation.use_cases import generate

    _require(db, instance)
    path = workflow_path(path)
    graph = {
        "prompt": _api_graph(prompt),
        **({"workflow": _canvas(workflow)} if workflow is not None else {}),
        **({"client_id": client_id} if _CLIENT_ID.fullmatch(client_id or "") else {}),
    }
    profile = _profile(db, instance)
    row = next((one for one in provider_models.list_models(db, profile.id) if one.model_id == path), None) \
        if profile is not None else None
    kinds = [kind for kind in (row.capability_ids or []) if kind in ("image", "video", "audio")] if row is not None else []
    if profile is None or row is None or not row.enabled or not kinds:
        if row is None and _forms_await_upgrade(db, instance, path):
            raise WorkflowLibraryError("workflowLibErr_runFormsOld", path=path)
        raise WorkflowLibraryError("workflowLibErr_runNotModel", path=path)
    #: 这台连接上这张工作流的那条会话(ADR 0052,D44):和 0044 的 ComfyUI 地方同一种 id。工作流改了名不跟着走 —— 出处是开的那一刻
    return generate(db, user, workspace_id, session_id=None, project_id=project_id, provider=profile.vendor, model=path,
                    kind=kinds[0], prompt="", negative_prompt="", parameters={}, source_assets=[],
                    provider_profile_id=profile.id, workbench_graph=graph, origin=Origin(COMFYUI, f"{instance.id}/{path}"))


def _forms_await_upgrade(db: Session, instance: PluginInstance, path: str) -> bool:
    """这张不在目录里,是不是因为它的表单还是上一版格式、等着升级(ADR 0045 修订之二 D1:那几张升级之前一个入口都不报)。
    问插件(`op: explain`);问不到当不是 —— 照原来那句说。"""
    try:
        return any(one.id == path and one.upgrade for one in plugin_generation.explain(db, instance, [path]))
    except Exception:  # noqa: BLE001 — 解释不出来不是错,照原来那句说
        return False


# --- 导入 ---------------------------------------------------------------------

def inspect_import(db: Session, instance: PluginInstance, *, text: str = "", data: str = "", filename: str = "",
                   url: str = "") -> dict[str, Any]:
    """让插件认一遍要导入的东西,规整成预览:换成界面格式的那张图、从哪儿来、什么格式、建议的路径、要告诉人的话,
    加上和列出来的每一张同一套的描述(图摘要、识别出的输入 / 参数 / 输出、用到的模型、缺的节点和模型)。"""
    _require(db, instance)
    if len([one for one in (text, data, url) if one]) != 1:
        raise WorkflowLibraryError("workflowLibErr_importOne")
    if max(len(text), len(data), len(url)) > MAX_IMPORT_CHARS:
        raise WorkflowLibraryError("workflowLibErr_importTooBig", mb=str(MAX_IMPORT_CHARS * 3 // 4 // (1024 * 1024)))
    if url and not re.match(r"^https?://\S+$", url.strip()):
        raise WorkflowLibraryError("workflowLibErr_importBadUrl")
    request: dict[str, Any] = {"op": "inspect_import"}
    if text:
        request["text"] = text
    if data:
        request["data"] = data
    if url:
        request["url"] = url.strip()
    if filename:
        request["filename"] = _text(filename, 300)
    output = tools.invoke_host(db, instance.id, WORKFLOW_LIBRARY, request, timeout=QUICK_TIMEOUT_SECONDS, record=False)
    workflow = output.get("workflow")
    if not isinstance(workflow, dict) or not isinstance(workflow.get("nodes"), list):
        raise WorkflowLibraryError("workflowLibErr_badAnswer", name=instance.name)
    try:
        suggested = workflow_path(_text(output.get("suggested_path"), 500))
    except WorkflowLibraryError:
        suggested = ""  # 界面自己给一个
    described = _workflow({**output, "path": suggested or "imported.json"}) or {}
    for key in ("path", "label", "folder", "size", "modified"):
        described.pop(key, None)
    fmt, source = _text(output.get("format"), 10), _text(output.get("source"), 10)
    return {
        **described,
        "format": fmt if fmt in _IMPORT_FORMATS else "ui",
        "source": source if source in _IMPORT_SOURCES else "json",
        "workflow": workflow,
        "suggested_path": suggested,
        "notes": [_text(one, 1000) for one in (output.get("notes") or []) if isinstance(one, str) and one.strip()][:10],
    }


def save(db: Session, instance: PluginInstance, path: str, content: dict[str, Any]) -> dict[str, str]:
    """把导入的那张(界面格式)存进那台服务器的 workflows/:只新建、不覆盖,撞名 409 带建议名。"""
    _require(db, instance)
    path = workflow_path(path)
    if not isinstance(content.get("nodes"), list):
        raise WorkflowLibraryError("workflowLibErr_notUiWorkflow")
    text = json.dumps(content, ensure_ascii=False)
    if len(text) > MAX_IMPORT_CHARS:
        raise WorkflowLibraryError("workflowLibErr_importTooBig", mb=str(MAX_IMPORT_CHARS * 3 // 4 // (1024 * 1024)))
    return {"path": _write(db, instance, {"op": "save_workflow", "path": path, "content": text}, wanted=path)}


# --- 补齐缺的节点 ------------------------------------------------------------------

def _packs(value: list[str]) -> list[str]:
    packs = [one.strip() for one in value if isinstance(one, str)]
    if not packs or len(packs) > _MAX_PACKS or any(
        not one or len(one) > 300 or any(ord(char) < 32 for char in one) for one in packs
    ):
        raise WorkflowLibraryError("workflowLibErr_badPacks", most=str(_MAX_PACKS))
    return list(dict.fromkeys(packs))


def start_node_install(db: Session, user: User, instance: PluginInstance, *, workspace_id: str,
                       packs: list[str]) -> Job:
    """经这个连接(ComfyUI-Manager)装几个节点包:一个后台任务。装完要重启 ComfyUI 才加载 —— 任务的结果里写着。"""
    _require(db, instance)
    packs = _packs(packs)
    ensure_workspace_perm(db, user, workspace_id, "edit")
    blocked = inst.blocked_reason(db, instance)
    if blocked:
        raise PluginDomainError("pluginErr_unavailable", name=instance.name, reason=blocked)
    subject = "、".join(packs)
    job = create_job(
        db,
        workspace_id=workspace_id,
        kind="node_install",  # 和 NODE_INSTALL_KIND 同一个;任务目录的测试按字面量扫
        created_by=user.id,
        payload={"instance_id": instance.id, "packs": packs, "subject": subject},
        message="jobMsg_nodeInstallQueued",
        message_params={"name": subject},
    )
    job_id = job.id
    dispatch_job(db, job, lambda: _install(job_id))
    return job


def _install(job_id: str) -> None:
    """装节点包的任务身子。和模型下载一样,每一步一个短的 unit_of_work,状态都经 finish_job 写。"""
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        payload = dict(job.payload or {})
        subject = str(payload.get("subject") or "")
        if db.get(PluginInstance, str(payload.get("instance_id") or "")) is None:
            if finish_job(db, job, status="failed", error="", error_key="modelLibErr_instanceGone", error_params={}):
                say(job, "jobMsg_nodeInstallFailed", name=subject)
            return
        if not finish_job(db, job, status="running", progress=0.01):
            return
        say(job, "jobMsg_nodeInstallRunning", name=subject)
        emit_job_event(db, job.id, "job.running", {})

    def on_progress(fraction: float, message: str) -> None:
        with unit_of_work() as db:
            job = db.get(Job, job_id)
            if job is None or not finish_job(db, job, status="running"):
                return
            job.progress = min(0.99, max(float(job.progress or 0.0), float(fraction)))
            if message:
                say(job, message[:200])

    def cancelled() -> bool:
        from app.domain.jobs import was_cancelled

        with unit_of_work() as db:
            job = db.get(Job, job_id)
            return job is None or was_cancelled(job) or job.status not in ("queued", "running")

    hooks = StreamHooks(on_progress=on_progress, on_task=lambda _receipt: None, is_cancelled=cancelled)
    try:
        with unit_of_work() as db:
            output = tools.invoke_host(db, str(payload["instance_id"]), WORKFLOW_LIBRARY,
                                       {"op": "install_nodes", "packs": payload["packs"]}, hooks=hooks,
                                       timeout=MAX_GENERATION_TIMEOUT_SECONDS)
    except (PluginDomainError, PluginRuntimeError) as exc:
        from app.domain.jobs import blame

        with unit_of_work() as db:
            job = db.get(Job, job_id)
            if job is not None and finish_job(db, job, status="failed", **blame(exc)):
                say(job, "jobMsg_nodeInstallFailed", name=subject)
                emit_job_event(db, job.id, "job.failed", {})
        return
    installed = [_text(one, 300) for one in output.get("installed") or [] if isinstance(one, str)]
    result = {"installed": installed or list(payload["packs"]), "restart": output.get("restart") is not False}
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        if job is not None and finish_job(db, job, status="succeeded", progress=1.0, result=result):
            say(job, "jobMsg_nodeInstallDone", name=subject)
            emit_job_event(db, job.id, "job.succeeded", dict(result))


def node_installs(db: Session, instance: PluginInstance) -> list[Job]:
    """这个连接最近的几次装节点包(在跑的总在里面),新的在前。"""
    rows = db.scalars(select(Job).where(Job.kind == NODE_INSTALL_KIND).order_by(Job.created_at.desc()).limit(100))
    mine = [job for job in rows if (job.payload or {}).get("instance_id") == instance.id]
    active = [job for job in mine if job.status in ("queued", "running")]
    finished = [job for job in mine if job.status not in ("queued", "running")]
    return active + finished[: max(0, RECENT_INSTALLS - len(active))]


def reboot(db: Session, instance: PluginInstance) -> dict[str, bool]:
    """经插件(ComfyUI-Manager)重启那台 ComfyUI,等它回来;回来以后这个连接的目录重拉一遍 —— 新装的节点包这时才加载。

    那台服务器是宿主起停的本机服务时(ADR 0041),插件不自己去重启它,交回 `host_restart`:由宿主停了再起、等它就绪。
    插件自己重启它(Windows 上是另起一个进程、旧的退出),宿主会以为它崩了,也就再也停不掉它。"""
    _require(db, instance)
    output = tools.invoke_host(db, instance.id, WORKFLOW_LIBRARY, {"op": "reboot"}, timeout=REBOOT_TIMEOUT_SECONDS)
    if output.get("host_restart") is True:
        local_services.restart(db, instance, wait=True)
        back = True
    else:
        back = output.get("back") is True
    host_capabilities.notify(db, instance, refresh=True)
    return {"back": back}


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
    "WorkflowFolderNotEmpty",
    "WorkflowLibraryError",
    "WorkflowStale",
    "annotate",
    "app_form",
    "content",
    "copy",
    "folder_path",
    "inspect_import",
    "library",
    "mark_output_nsfw",
    "outputs",
    "make_folder",
    "node_installs",
    "reboot",
    "register_uses",
    "rename",
    "rename_folder",
    "restore",
    "save",
    "start_node_install",
    "trash",
    "trash_folder",
    "trash_path",
    "workflow_path",
]
