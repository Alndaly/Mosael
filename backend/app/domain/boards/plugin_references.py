"""画板上存着的**被取代的插件工具格**,改写成取代它的那个工具。

工具格(ADR 0021 P2)存的是 `form.producer = "node:plugin.<包>.<工具>"`、`form.config`(填的值)和
`form.bindings`(字段 → 从哪几格来)。插件报出的新工具声明了 `replaces` 时(见
domain/workflows/plugin_references,规则在那边一处),这里用同一套判据改画板:配置按那张表改名,
绑定的字段名跟着改;有一格对不上时,老工具还在就不动这一格,老工具已经不在了就把没有位置的配置和绑定丢掉
(和工作流那边同一条)。画板的数据归画板域写(见 domain/ownership),
所以它住在这里而不是工作流那边。

**被生成取代的工具格**(ADR 0021 修订 · 一个概念一个入口)。插件报出的工具声明了 `mirrors`(它和某个生成模型是
同一件事,见 docs/PLUGIN_MANIFEST)、而那个连接的主人在生成目录里用得上那个模型时,画板上不再列这个工具
(boards.transforms 的 `mirrored_by_generation`)。存着的这种工具格照样得能用:改写成**那种素材的生成格**
(图片 / 视频 / 音频,产出者 `generate`、选的就是那个模型),id、位置、名字不变。带得过去的:

- 提示词:填的字原样带过去;接的是上游便签 / 文档时留空 —— 连线还在,生成格的面板照上游便签填提示词、
  带上文档(和工具格运行时「绑定的优先」是同一个结果);
- 素材:接上游的那几格按 `mirrors.sources` 换成生成的素材角色(记着 `from`,和面板照上游挂的一样);手挑的素材 id
  照样挂上;
- 参数:按 `mirrors.parameters` 改名(值原样,面板打开时按模型的描述符解读)。

带不过去的丢掉并记日志:没有写进 `mirrors` 的入参(ComfyUI 的宽和高 —— 生成里是一格「尺寸」、也取回预览)、
选的连接(生成格选的是连接下的模型本身)、工具格的尺寸和上一轮的运行状态。在跑的那一格不动,等它落终态;
没选连接、几条连接给出的模型不是同一个时也不动(和 replaces 同一条:说不准就不改),跑的时候说清楚去用生成。

什么时候跑:和 replaces 同一个时机 —— 插件的工具清单每刷新一次(`dynamic_tools.on_refreshed`,生成目录在它前面
刷新,见清单里 `provides` 的顺序),以及每次启动(对账步骤 `rewrite-replaced-plugin-tools`)。`mirrors` 只有插件
报出清单之后才有,所以这是对账,不是一次性迁移;没有可改的就什么都不做。

**按另一个系统里的编号取东西的工具格**(boards.transforms 的 `external_id`:ComfyUI 的「导入产出」、网盘的「导入」、
对象存储的「取回」)改成一张便签,和内置流程节点的那次迁移(`migrate-board-wiring-tools-become-notes`)同一个做法:
同一个 id、位置、大小、名字,正文写明这一步归工作流、附上原来的设置;进出它的线都还连得上,它跑出来的产出一格
不动。**也是对账,不是一次性迁移**:合不合格读的是插件此刻的清单 —— 升级插件(1.5.2 的 ComfyUI、0.7.2 的网盘)
可能在任何一次启动之后,一次性迁移跑的时候清单里还没有这句声明。只认连接报得出这个工具、而且**每一条**
(选了连接就只看那一条)都说它按编号取东西的格子;没有连接知道它、或者说法不一的不动,跑的时候由注册表说清楚
(`boardErr_toolFetchesByExternalId`)。在跑的那一格等它落终态。
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Board, PluginInstance
from app.domain.boards.producer_ids import node_producer_id, node_type_of

#: 生成格的产出者(boards.producers 里内置的那一个)。
GENERATE_PRODUCER = "generate"

logger = logging.getLogger(__name__)


def _rewrite_item(item: dict[str, Any], found: list[Any]) -> dict[str, Any] | None:
    from app.domain.workflows.plugin_references import MISSING, rewrite_node

    form = item.get("form") if isinstance(item.get("form"), dict) else None
    node_type = node_type_of(str((form or {}).get("producer") or ""))
    if form is None or not node_type:
        return None
    dropped: list[str] = []
    result = rewrite_node(node_type, dict(form.get("config") or {}), found, dropped)
    if result is None:
        return None
    new_type, converted, replacement = result
    bindings = form.get("bindings") if isinstance(form.get("bindings"), dict) else {}
    renamed: dict[str, Any] = {}
    for field, refs in bindings.items():
        target = replacement.target(str(field))
        if target is MISSING:
            if not replacement.retired:
                return None
            dropped.append(f"{field}(绑定)")  # 老工具已经不在了:这一格在新工具上没有位置,绑定拆掉
            continue
        renamed[target] = refs
    if dropped:
        logger.info("画板工具格 %s 改写成 %s 时丢掉了 %s", item.get("id"), new_type, dropped)
    return {**item, "form": {**form, "producer": node_producer_id(new_type), "config": converted, "bindings": renamed}}


def rewrite_replaced_tools(db: Session) -> int:
    """把库里所有画板上能改的老插件工具格改掉。返回改了几块画板。"""
    from app.domain.workflows.plugin_references import replacements

    found = replacements(db)
    if not found:
        return 0
    changed = 0
    for board in db.scalars(select(Board)):
        canvas = board.canvas if isinstance(board.canvas, dict) else {}
        items = canvas.get("items") if isinstance(canvas.get("items"), list) else []
        touched = False
        rewritten_items = []
        for item in items:
            rewritten = _rewrite_item(item, found) if isinstance(item, dict) else None
            touched = touched or rewritten is not None
            rewritten_items.append(rewritten if rewritten is not None else item)
        if not touched:
            continue
        board.canvas = {**deepcopy(canvas), "items": rewritten_items}
        board.revision = (board.revision or 0) + 1
        changed += 1
    db.commit()
    if changed:
        logger.info("把 %d 块画板上的老插件工具格改写成了取代它的工具", changed)
    return changed


# ── 被生成取代的工具格 ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Mirror:
    """一个连接上的一个工具**和一个生成模型是同一件事**,而那个连接的主人用得上那个模型。"""

    package_id: str
    instance_id: str
    tool: str
    spec: dict[str, Any]
    kind: str
    provider: str
    provider_profile_id: str
    model: str


GenerationIndex = dict[tuple[str, str, str], Any]


def generation_index(db: Session, user_id: str | None, kinds: Any = None) -> GenerationIndex:
    """`user_id` 在生成目录里用得上的插件模型:(种类, 插件连接 id, 模型 id) → 那一行模型。

    问的就是生成选择器问的那一个(provider_models.models_for_capability),不另判「能不能用」;只收插件连接
    (`plugin_instance_id` 指回实例)下的 —— 工具和模型要是**同一个连接**的才算同一件事。
    """
    from app.domain import provider_models
    from app.domain.generation.catalog import GENERATION_KINDS

    index: GenerationIndex = {}
    for kind in kinds if kinds is not None else GENERATION_KINDS:
        if kind not in GENERATION_KINDS:
            continue
        for row in provider_models.models_for_capability(db, kind, user_id):
            profile = row.profile
            if profile is not None and profile.plugin_instance_id:
                index[(kind, str(profile.plugin_instance_id), str(row.model_id))] = row
    return index


def mirrored_model(index: GenerationIndex, instance_id: str, mirror: Any) -> Any:
    """这个连接上声明了 `mirror` 的工具,对得上的那一行生成模型;对不上(没声明、他用不了)回 None。"""
    if not isinstance(mirror, dict):
        return None
    return index.get((str(mirror.get("kind") or ""), instance_id, str(mirror.get("generation_model") or "")))


def mirrors(db: Session) -> list[Mirror]:
    """所有连接报出的工具里,声明了 `mirrors`、且连接的主人此刻用得上那个模型的那些。"""
    found: list[Mirror] = []
    indexes: dict[str, GenerationIndex] = {}
    for instance in db.scalars(select(PluginInstance)):
        for tool in instance.discovered_tools or []:
            spec = tool.get("mirrors") if isinstance(tool, dict) else None
            if not isinstance(spec, dict):
                continue
            owner = instance.owner_user_id or ""
            if owner not in indexes:
                indexes[owner] = generation_index(db, owner)
            row = mirrored_model(indexes[owner], instance.id, spec)
            if row is None:
                continue
            found.append(Mirror(instance.package_id, instance.id, str(tool.get("name") or ""), spec,
                                str(spec["kind"]), str(row.profile.vendor), str(row.provider_profile_id), str(row.model_id)))
    return found


def _given(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _to_generation(item: dict[str, Any], by_id: dict[str, dict[str, Any]], found: list[Mirror]) -> dict[str, Any] | None:
    """一格跑着被生成取代的工具的工具格 → 那种素材的生成格。改不了(不是这种格子、在跑、说不准)回 None。"""
    from app.ai.providers.contracts.generation import SOURCE_ROLES
    from app.domain.plugins.nodes import parse_node_type

    form = item.get("form") if isinstance(item.get("form"), dict) else None
    if item.get("kind") != "action" or form is None:
        return None
    parsed = parse_node_type(node_type_of(str(form.get("producer") or "")) or "")
    if parsed is None:
        return None
    if (item.get("run") or {}).get("status") in ("queued", "running"):
        return None  # 这一轮的回执要落回这一格:等它落终态,下一次对账再改
    package_id, tool_name = parsed
    config = dict(form.get("config") or {})
    bindings = form.get("bindings") if isinstance(form.get("bindings"), dict) else {}
    chosen = str(config.get("instance_id") or "")
    candidates = [one for one in found if one.package_id == package_id and one.tool == tool_name
                  and (not chosen or one.instance_id == chosen)]
    if len({(one.kind, one.provider_profile_id, one.model) for one in candidates}) != 1:
        return None
    mirror = candidates[0]
    prompt_field = str(mirror.spec.get("prompt") or "")
    parameter_names = mirror.spec.get("parameters") if isinstance(mirror.spec.get("parameters"), dict) else {}
    source_roles = mirror.spec.get("sources") if isinstance(mirror.spec.get("sources"), dict) else {}

    dropped: list[str] = []
    prompt = ""
    parameters: dict[str, Any] = {}
    #: 字段 → 挂上去的素材。和运行时(tools.resolve_bindings)同一个先后:接了上游、上游有素材的,盖过手挑的。
    sources: dict[str, list[dict[str, str]]] = {}
    for field, value in config.items():
        if field == "instance_id" or not _given(value):
            continue
        if field == prompt_field:
            #: 接了上游的话,运行时用的是上游的字(绑定优先);生成格的面板照连线填,这里留空。
            prompt = "" if bindings.get(field) else str(value)
        elif field in parameter_names:
            parameters[str(parameter_names[field])] = value
        elif source_roles.get(field) in SOURCE_ROLES:
            sources[field] = [{"asset_id": str(value), "role": str(source_roles[field])}]
        else:
            dropped.append(field)
    for field, refs in bindings.items():
        if field == prompt_field:
            continue  # 连线还在:上游便签 / 文档由生成格的面板接上
        role = source_roles.get(field)
        if role not in SOURCE_ROLES:
            dropped.append(f"{field}(绑定)")
            continue
        #: 和面板照上游挂的一样:记着 `from`,线断了、上游换了素材就摘掉(canvas._drop_detached_bindings)。
        upstream = [by_id.get(str(ref.get("from") or "")) for ref in refs if isinstance(ref, dict)] if isinstance(refs, list) else []
        attached = [{"asset_id": str(one["asset_id"]), "role": str(role), "from": str(one["id"])}
                    for one in upstream if one is not None and one.get("asset_id")]
        if attached:
            sources[field] = attached
    if dropped:
        logger.info("画板工具格 %s 改写成生成格(%s · %s)时带不过去:%s", item.get("id"), mirror.provider, mirror.model, dropped)
    kept = {key: value for key, value in item.items() if key not in ("kind", "form", "run", "width", "height")}
    return {
        **kept,
        "kind": mirror.kind,
        "form": {
            "prompt": prompt,
            "provider": mirror.provider,
            "provider_profile_id": mirror.provider_profile_id,
            "model": mirror.model,
            "parameters": parameters,
            "source_assets": [one for attached in sources.values() for one in attached],
            "producer": GENERATE_PRODUCER,
        },
    }


def rewrite_mirrored_tools(db: Session) -> int:
    """把库里所有画板上跑着被生成取代的工具的工具格,改写成生成格。返回改了几块画板。"""
    found = mirrors(db)
    if not found:
        return 0
    changed = 0
    for board in db.scalars(select(Board)):
        canvas = board.canvas if isinstance(board.canvas, dict) else {}
        items = canvas.get("items") if isinstance(canvas.get("items"), list) else []
        by_id = {str(one.get("id")): one for one in items if isinstance(one, dict)}
        touched = False
        rewritten_items = []
        for item in items:
            rewritten = _to_generation(item, by_id, found) if isinstance(item, dict) else None
            touched = touched or rewritten is not None
            rewritten_items.append(rewritten if rewritten is not None else item)
        if not touched:
            continue
        board.canvas = {**deepcopy(canvas), "items": rewritten_items}
        board.revision = (board.revision or 0) + 1
        changed += 1
    db.commit()
    if changed:
        logger.info("把 %d 块画板上被生成取代的插件工具格改写成了生成格", changed)
    return changed


# ── 按另一个系统里的编号取东西的工具格 ─────────────────────────────────────


#: 便签正文最长多少字(和内置流程节点改成便签的那次迁移同一档)。
_NOTE_LIMIT = 20_000


def _fetchers(db: Session) -> dict[tuple[str, str], dict[str, str]]:
    """(包, 工具) → {连接 id: 工具的名字}:连接报出的工具,**按另一个系统里的编号取东西**的记名字
    (boards.transforms 的 `external_id`),不是的记空串 —— 几条连接说法不一就不改。"""
    from app.domain.boards.transforms import content_transform_gap
    from app.domain.plugins.errors import PluginDomainError
    from app.domain.plugins.nodes import node_meta
    from app.domain.plugins.tools import all_tools

    found: dict[tuple[str, str], dict[str, str]] = {}
    for instance in db.scalars(select(PluginInstance)):
        try:
            tools = all_tools(db, instance)
        except PluginDomainError:
            continue  # 包已经删了:说不出它的工具是什么
        for tool in tools:
            gap = content_transform_gap(node_meta({**tool, "package_id": instance.package_id}))
            label = str(tool.get("label") or tool["name"]) if gap == "external_id" else ""
            found.setdefault((instance.package_id, str(tool["name"])), {})[instance.id] = label
    return found


def _to_note(item: dict[str, Any], fetchers: dict[tuple[str, str], dict[str, str]]) -> dict[str, Any] | None:
    """一格跑着按编号取东西的工具的工具格 → 写明「这一步归工作流」的便签。改不了的(说不准、在跑)回 None。"""
    from app.core.i18n import t
    from app.domain.plugins.nodes import parse_node_type

    form = item.get("form") if isinstance(item.get("form"), dict) else None
    if item.get("kind") != "action" or form is None:
        return None
    parsed = parse_node_type(node_type_of(str(form.get("producer") or "")) or "")
    if parsed is None or (item.get("run") or {}).get("status") in ("queued", "running"):
        return None  # 这一轮的回执要落回这一格:等它落终态,下一次对账再改
    config = form.get("config") if isinstance(form.get("config"), dict) else {}
    by_instance = fetchers.get(parsed) or {}
    chosen = str(config.get("instance_id") or "")
    labels = [label for instance_id, label in by_instance.items() if not chosen or instance_id == chosen]
    if not labels or not all(labels):
        return None
    #: 迁移时没有请求,也就没有读的人的语言:按部署缺省(见 core/i18n 开头那段)。
    body = t("boardNote_toolFetchesByExternalId", tool=labels[0])
    settings = {key: value for key, value in config.items() if key != "instance_id"}
    if settings:
        body += f"\n\n{t('boardNote_originalSettings')}\n" + json.dumps(settings, ensure_ascii=False, indent=2)
    if len(body) > _NOTE_LIMIT:
        body = body[: _NOTE_LIMIT - 1] + "…"
    kept = {key: value for key, value in item.items() if key not in ("kind", "form", "run", "text")}
    return {**kept, "kind": "note", "text": body, "form": {"producer": "write"}}


def retire_external_id_tools(db: Session) -> int:
    """把库里所有画板上跑着「按编号取东西」的工具格改成便签。返回改了几块画板。"""
    fetchers = _fetchers(db)
    if not any(label for by_instance in fetchers.values() for label in by_instance.values()):
        return 0
    changed = 0
    for board in db.scalars(select(Board)):
        canvas = board.canvas if isinstance(board.canvas, dict) else {}
        items = canvas.get("items") if isinstance(canvas.get("items"), list) else []
        touched = False
        rewritten_items = []
        for item in items:
            rewritten = _to_note(item, fetchers) if isinstance(item, dict) else None
            touched = touched or rewritten is not None
            rewritten_items.append(rewritten if rewritten is not None else item)
        if not touched:
            continue
        board.canvas = {**deepcopy(canvas), "items": rewritten_items}
        board.revision = (board.revision or 0) + 1
        changed += 1
    db.commit()
    if changed:
        logger.info("把 %d 块画板上按编号取东西的插件工具格改成了便签", changed)
    return changed


def reconcile_plugin_tool_cells(db: Session) -> None:
    """画板上存着的插件工具格跟上插件报出的清单:先按 `replaces` 改名,再把被生成取代的改成生成格,
    按编号取东西的改成便签。"""
    rewrite_replaced_tools(db)
    rewrite_mirrored_tools(db)
    retire_external_id_tools(db)


def _after_refresh(db: Session, instance: PluginInstance) -> None:
    reconcile_plugin_tool_cells(db)


def install() -> None:
    from app.domain.plugins import dynamic_tools

    dynamic_tools.on_refreshed(_after_refresh)


__all__ = [
    "Mirror",
    "generation_index",
    "install",
    "mirrored_model",
    "mirrors",
    "reconcile_plugin_tool_cells",
    "retire_external_id_tools",
    "rewrite_mirrored_tools",
    "rewrite_replaced_tools",
]
