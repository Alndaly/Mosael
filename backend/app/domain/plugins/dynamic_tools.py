"""进程插件**在运行时报出**的工具(见 docs/PLUGIN_MANIFEST 的「运行时报出的工具」)。

清单里 `declare` 的工具是写死的:ComfyUI 插件以前的通用 `run_workflow` 不管选的是哪张工作流,入参都长一个样 ——
放大工作流也问你要提示词,插件页的表单里全是 `string` 占位(它后来删掉了)。而每张工作流该收什么,图里写得清清楚楚,
只有插件在运行时看得到。所以插件可以声明一项宿主能力 `tools`(`provides: ["tools"]`,由一个只给宿主调的
工具认领),宿主向它要清单:

    {"op": "tools"}        → {"tools": [ {name, label, description, input_schema, node, stream, …} ], "fingerprint": "…"}
    {"op": "fingerprint"}  → {"fingerprint": "…"}       便宜的一问;变了才重新要清单(见 catalog_watch)

报出来的工具**和清单里声明的工具走同一条路**:存进 `plugin_instances.discovered_tools`(MCP 连接从服务拉来的
清单也存在这里 —— 一个连接只有一份「运行时知道的工具」)、同一张开关表、同一个执行入口 `tools.invoke`,
于是它们自动出现在工作流节点面板(`plugin.<包>.<工具>`)、智能体工具表和插件页。调用时插件照常收到
`{"tool": <名字>, "input": …}`。

刷新时机和生成模型目录一样(实例新建、改配置、启停、授权、插件页「刷新」、启动时、以及指纹变了),
失败不抛:清单保留上一份,原因记进 `capability_status["tools"]`。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import PluginInstance
from app.domain.effects import EFFECTS, NONE as NO_EFFECTS
from app.domain.plugins import instances as inst
from app.domain.plugins import moves as plugin_moves
from app.domain.plugins import tools
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.groups import clean_group
#: 工具名的规矩和清单里声明的工具是同一条(见 manifest.TOOL_NAME_RE)。
from app.domain.plugins.manifest import TOOL_NAME_RE, TOOLS
from app.domain.plugins.runtime import PluginRuntimeError

logger = logging.getLogger(__name__)

#: 问一次清单最多等多久(一台 ComfyUI 上百张工作流,每张拉一次图)。
CATALOG_TIMEOUT_SECONDS = 60.0
#: 一个工具最多声明取代几种老用法。
MAX_REPLACES = 8
#: 报出来的工具上宿主认的键。别的丢掉 —— 尤其是 `provides` 和 `internal`:运行时报出的工具不能替宿主
#: 认领能力,也不能把自己藏成「只给宿主」。
_KEPT = ("name", "label", "description", "input_schema", "read_only", "effects", "stream", "timeout_seconds", "node",
         "recommended", "replaces", "mirrors", "workflow", "group", "agent")
#: `mirrors` 里的键名(生成参数键、入参名、素材角色)的样子。值是插件报的,进画板表单前先卡一道。
_MIRROR_KEY = re.compile(r"^[A-Za-z0-9_.:\-]{1,128}$")
#: 模型 id 可以是一条路径(ComfyUI 的工作流就是 `people/人像.json`),只卡长度和不是空的。
_MIRROR_MODEL_MAX = 512
#: `workflow` 的路径、名字最长多少(路径和工作流库同一个上限)。
_WORKFLOW_PATH_MAX = 600
_WORKFLOW_NAME_MAX = 200

#: 清单刷新之后要跟着动的那些(把存着的老节点改写成新工具,见 domain/workflows/plugin_references)。
#: 插件域不认识工作流域 —— 由那边在组装根登记进来(和能力表的实例钩子同一个方向)。
Listener = Callable[[Session, PluginInstance], None]
_listeners: list[Listener] = []


def on_refreshed(listener: Listener) -> None:
    if listener not in _listeners:
        _listeners.append(listener)


def _clean(entry: Any, declared: set[str]) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    name = str(entry.get("name") or "").strip()
    if not TOOL_NAME_RE.match(name) or name in declared:
        return None
    schema = entry.get("input_schema")
    if not isinstance(schema, dict):
        schema = {"type": "object", "properties": {}}
    clean = {key: entry[key] for key in _KEPT if key in entry}
    clean["name"] = name
    clean["input_schema"] = schema
    for flag in ("read_only", "stream", "recommended"):
        if flag in clean:
            clean[flag] = clean[flag] is True
    # 后果(domain/effects)和清单里声明的工具同一套词。清单写错在装的时候就报,运行时报出的清单
    # 没有「装」这一刻,所以在这里按**保守那边**收:不认识的取值当没写(按包上的缺省、再按 external);
    # 只读却声明了别的后果,两句话打架,信后果那一句、只读作废 —— 反过来信只读,一个会花钱的工具
    # 就不问人地跑了,还交给了子智能体。
    if "effects" in clean and clean["effects"] not in EFFECTS:
        clean.pop("effects")
    if clean.get("read_only") and clean.get("effects", NO_EFFECTS) != NO_EFFECTS:
        clean["read_only"] = False
    if not isinstance(clean.get("node"), dict):
        clean.pop("node", None)
    # 取代一种老用法是一个对象;一个工具取代好几种(老的通用工具 + 自己以前的名字)是一组
    replaces = clean.get("replaces")
    if isinstance(replaces, list):
        replaces = [one for one in replaces if isinstance(one, dict)][:MAX_REPLACES] or None
    if isinstance(replaces, (dict, list)):
        clean["replaces"] = replaces
    else:
        clean.pop("replaces", None)
    mirror = clean_mirror(clean.get("mirrors"))
    if mirror is None:
        clean.pop("mirrors", None)
    else:
        clean["mirrors"] = mirror
    workflow = clean_workflow(clean.get("workflow"))
    if workflow is None:
        clean.pop("workflow", None)
    else:
        clean["workflow"] = workflow
    # 哪样东西的哪个入口(ADR 0045,见 plugins.groups);形状不对当没说
    group = clean_group(clean.get("group"))
    if group is None:
        clean.pop("group", None)
    else:
        clean["group"] = group
    # 只认 `agent: false`(不进智能体的工具表,别处照常);别的写法当没写 —— 缺省是进
    if clean.get("agent") is not False:
        clean.pop("agent", None)
    return clean


def clean_workflow(raw: Any) -> dict[str, Any] | None:
    """`workflow`:这个工具跑的是连接上的**哪张工作流**(见 docs/PLUGIN_MANIFEST「运行时报出的工具」)。

        {"path": "<工作流库里的路径>", "name": "<到处同一个名字,可以按语言分>"}

    宿主据此只把用得上的那几张发给智能体(画布上开着的、对话里用过或点过名的,见 agent.tool_manifest)。路径不对的整条不认 ——
    认错了的结果是一张工作流的工具在它开着的时候不发;名字不像样的只丢名字(点名认不出,画布和用过照旧认)。
    """
    if not isinstance(raw, dict):
        return None
    path = raw.get("path")
    if not isinstance(path, str) or not path.strip() or len(path) > _WORKFLOW_PATH_MAX or any(ord(char) < 32 for char in path):
        return None
    workflow: dict[str, Any] = {"path": path}
    name = raw.get("name")
    if isinstance(name, str) and 0 < len(name.strip()) <= _WORKFLOW_NAME_MAX:
        workflow["name"] = name.strip()
    elif isinstance(name, dict):
        named = {lang: text.strip() for lang, text in name.items()
                 if isinstance(lang, str) and isinstance(text, str) and 0 < len(text.strip()) <= _WORKFLOW_NAME_MAX}
        if named:
            workflow["name"] = named
    return workflow


def clean_mirror(raw: Any) -> dict[str, Any] | None:
    """`mirrors`:这个工具**和一个生成模型是同一件事**(见 docs/PLUGIN_MANIFEST「运行时报出的工具」)。

        {"generation_model": "<模型 id>", "kind": "image" | "video" | "audio",
         "prompt": "<哪个入参是提示词>",                      // 可选
         "parameters": {"<入参>": "<生成参数键>", …},          // 可选
         "sources": {"<入参>": "<素材角色>", …}}               // 可选

    前两格是这件事本身(画板上只留生成那一个入口,见 boards.transforms);后三格只给迁移用 —— 画板上存着的
    空格子上存着的这种生成器改挂生成时,填过的值怎么带过去(见 boards.plugin_references)。形状不对的整条不认:
    说错了的「同一件事」比没说更糟,它会把一个工具从画板上藏起来。
    """
    if not isinstance(raw, dict):
        return None
    model = raw.get("generation_model")
    kind = raw.get("kind")
    if not isinstance(model, str) or not model.strip() or len(model) > _MIRROR_MODEL_MAX:
        return None
    if not isinstance(kind, str) or not _MIRROR_KEY.match(kind):
        return None
    mirror: dict[str, Any] = {"generation_model": model.strip(), "kind": kind}
    prompt = raw.get("prompt")
    if isinstance(prompt, str) and _MIRROR_KEY.match(prompt):
        mirror["prompt"] = prompt
    for field in ("parameters", "sources"):
        mapping = raw.get(field)
        if isinstance(mapping, dict):
            kept = {key: value for key, value in mapping.items()
                    if isinstance(key, str) and isinstance(value, str) and _MIRROR_KEY.match(key) and _MIRROR_KEY.match(value)}
            if kept:
                mirror[field] = kept
    return mirror


def refresh(db: Session, instance: PluginInstance, refresh: bool) -> None:
    """`tools` 这项能力的宿主侧:按需向插件要一次工具清单,存进实例、补上开关。"""
    manifest = inst.manifest_for(db, instance)
    if TOOLS not in manifest.provides or manifest.is_mcp:
        return
    previous = dict((instance.capability_status or {}).get(TOOLS) or {})
    if inst.blocked_reason(db, instance) or not (refresh or not previous.get("refreshed_at")):
        return
    try:
        output = tools.invoke_host(db, instance.id, TOOLS, {"op": "tools"}, timeout=CATALOG_TIMEOUT_SECONDS)
        raw = output.get("tools")
        if not isinstance(raw, list):
            raise PluginDomainError("pluginErr_toolsBadShape", name=instance.name, shape='{"tools": [...]}')
    except (PluginDomainError, PluginRuntimeError) as exc:
        db.rollback()
        inst.record_tool_list_failure(db, instance, exc)
        logger.info("插件实例 %s 的工具清单没刷出来:%s", instance.id, exc)
        return
    declared = {str(tool.get("name")) for tool in manifest.declared_tools}
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw[:tools.MAX_TOOLS]:
        clean = _clean(entry, declared)
        if clean is None or clean["name"] in seen:
            continue
        seen.add(clean["name"])
        found.append(clean)
    instance.discovered_tools = found
    db.flush()
    _apply_moves(db, instance, output.get("moved"), {tool["name"] for tool in found})
    db.commit()
    db.refresh(instance)
    inst.seed_capabilities(
        db, instance, manifest, [tool["name"] for tool in found],
        recommended={tool["name"] for tool in found if tool.get("recommended")},
    )
    fingerprint = output.get("fingerprint")
    inst.record_tool_list(
        db, instance, len(found), fingerprint=fingerprint.strip()[:200] if isinstance(fingerprint, str) else "",
    )
    for listener in _listeners:
        try:
            listener(db, instance)
        except Exception:  # noqa: BLE001 — 跟着动的那一侧出错,不让清单刷新本身失败
            db.rollback()
            logger.exception("插件实例 %s 的工具清单刷新之后,跟着动的那一侧出错", instance.id)


@dataclass(frozen=True)
class ExplainedTool:
    """插件说的「这个工具名为什么不在清单上」(`op: explain` 带 `tools`,见 docs/PLUGIN_MANIFEST):主名、来自哪样东西(同清单里的
    `group`)、一句原因、修法是不是到插件自己的库里升级。和模型的那一问(plugins.generation.Explained)同一套,给人看的字按语言分的
    原样留着,给人看时再挑。"""

    name: str
    label: str | dict[str, str]
    group: dict[str, Any] | None
    reason: str | dict[str, str]
    upgrade: bool = False


def explain(db: Session, instance: PluginInstance, names: list[str]) -> list[ExplainedTool]:
    """问这个实例:这几个工具名(工作流节点记着、清单上没有)为什么不在 —— 工作流里用不了的插件节点据此说原因(ADR 0045 修订之二)。
    插件认不出的不回;回来的条目里认不出的丢掉。插件不支持这一问、或者这会儿问不到,照常抛(调用方退回自己能说的那一句)。"""
    from app.domain.plugins.generation import EXPLAIN_TIMEOUT_SECONDS, MAX_EXPLAIN, localizable

    asked = [one for one in dict.fromkeys(names) if TOOL_NAME_RE.match(one)][:MAX_EXPLAIN]
    if not asked:
        return []
    output = tools.invoke_host(db, instance.id, TOOLS, {"op": "explain", "tools": asked}, timeout=EXPLAIN_TIMEOUT_SECONDS)
    text = inst.manifest_for(db, instance).text
    out: list[ExplainedTool] = []
    for entry in output.get("tools") or []:
        if not isinstance(entry, dict) or entry.get("name") not in asked or any(one.name == entry["name"] for one in out):
            continue
        reason = localizable(entry.get("reason"), text, 500)
        if not reason:
            continue
        out.append(ExplainedTool(name=entry["name"], label=localizable(entry.get("label"), text, 160) or entry["name"],
                                 group=clean_group(entry.get("group")), reason=reason, upgrade=entry.get("upgrade") is True))
    return out


def _apply_moves(db: Session, instance: PluginInstance, raw: Any, names: set[str]) -> None:
    """插件说有几个工具名改了意思(一次性的改名,ADR 0045,见 plugins.moves):这个连接上没做过的那几批做一次 —— 开关
    跟着新名字(在按推荐补开关之前,不然新名字先被补成推荐的那一档),存着的工作流节点、画板格子改到新名字,记账。
    改不成就整个撤掉、不记账,下次刷新再来:改名在一个保存点里做,撤的只是它,清单本身照样和它在同一笔里提交。不提交。"""
    moves = plugin_moves.pending(instance, TOOLS, plugin_moves.clean_moves(raw, names))
    if not moves:
        return
    renames = plugin_moves.merged(moves)
    try:
        with db.begin_nested():
            inst.carry_capabilities(db, instance, renames)
            plugin_moves.tools_moved(db, instance, renames)
            plugin_moves.record(db, instance, TOOLS, moves)
    except Exception:  # noqa: BLE001 — 跟着动的那一侧出错,不让清单刷新本身失败
        logger.exception("插件实例 %s 的工具改名没做成,下次刷新再来", instance.id)


__all__ = ["CATALOG_TIMEOUT_SECONDS", "ExplainedTool", "clean_mirror", "explain", "on_refreshed", "refresh"]
