"""进程插件**在运行时报出**的工具(见 docs/PLUGIN_MANIFEST 的「运行时报出的工具」)。

清单里 `declare` 的工具是写死的:ComfyUI 插件的 `run_workflow` 不管选的是哪张工作流,入参都长一个样 ——
放大工作流也问你要提示词,插件页的表单里全是 `string` 占位。而每张工作流该收什么,图里写得清清楚楚,
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
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import PluginInstance
from app.domain.effects import EFFECTS, NONE as NO_EFFECTS
from app.domain.plugins import host_capabilities
from app.domain.plugins import instances as inst
from app.domain.plugins import tools
from app.domain.plugins.errors import PluginDomainError
#: 工具名的规矩和清单里声明的工具是同一条(见 manifest.TOOL_NAME_RE)。
from app.domain.plugins.manifest import TOOL_NAME_RE, TOOLS
from app.domain.plugins.runtime import PluginRuntimeError

logger = logging.getLogger(__name__)

#: 问一次清单最多等多久(一台 ComfyUI 上百张工作流,每张拉一次图)。
CATALOG_TIMEOUT_SECONDS = 60.0
#: 一个连接最多报多少个工具。再多工具表和节点面板就没法用了。
MAX_TOOLS = 300
#: 一个工具最多声明取代几种老用法。
MAX_REPLACES = 8
#: 报出来的工具上宿主认的键。别的丢掉 —— 尤其是 `provides` 和 `internal`:运行时报出的工具不能替宿主
#: 认领能力,也不能把自己藏成「只给宿主」。
_KEPT = ("name", "label", "description", "input_schema", "read_only", "effects", "stream", "timeout_seconds", "node",
         "recommended", "replaces")

#: 清单刷新之后要跟着动的那些(把存着的老节点改写成新工具,见 domain/workflows/plugin_references)。
#: 插件域不认识工作流域 —— 由那边在组装根登记进来,方向和 host_capabilities 一样。
Listener = Callable[[Session, PluginInstance], None]
_listeners: list[Listener] = []


def on_refreshed(listener: Listener) -> None:
    if listener not in _listeners:
        _listeners.append(listener)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


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
    return clean


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
        from app.domain.jobs import blame

        inst.set_capability_status(db, instance, TOOLS, {**previous, **blame(exc), "attempted_at": _now()})
        logger.info("插件实例 %s 的工具清单没刷出来:%s", instance.id, exc)
        return
    declared = {str(tool.get("name")) for tool in manifest.declared_tools}
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw[:MAX_TOOLS]:
        clean = _clean(entry, declared)
        if clean is None or clean["name"] in seen:
            continue
        seen.add(clean["name"])
        found.append(clean)
    instance.discovered_tools = found
    db.commit()
    db.refresh(instance)
    inst.seed_capabilities(
        db, instance, manifest, [tool["name"] for tool in found],
        recommended={tool["name"] for tool in found if tool.get("recommended")},
    )
    fingerprint = output.get("fingerprint")
    inst.set_capability_status(db, instance, TOOLS, {
        "tools": len(found),
        "refreshed_at": _now(),
        "fingerprint": fingerprint.strip()[:200] if isinstance(fingerprint, str) else "",
        "error": "", "error_key": "", "error_params": {},
    })
    for listener in _listeners:
        try:
            listener(db, instance)
        except Exception:  # noqa: BLE001 — 跟着动的那一侧出错,不让清单刷新本身失败
            db.rollback()
            logger.exception("插件实例 %s 的工具清单刷新之后,跟着动的那一侧出错", instance.id)


def install() -> None:
    """组装根调一次:登记 `tools` 这项能力的宿主侧。"""
    host_capabilities.register(TOOLS, refresh)


__all__ = ["CATALOG_TIMEOUT_SECONDS", "MAX_TOOLS", "install", "on_refreshed", "refresh"]
