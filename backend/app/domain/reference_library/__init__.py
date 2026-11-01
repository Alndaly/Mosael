"""参考库(ADR 0091 §3):认领 `reference_library` 的插件提供**只读的外部图集**。

插件按 `op` 回答:

- `collections` —— 有哪几本图集(姿势 / 服装 / ……)、每本的种类、条目数与筛选维度;
- `search` —— 关键词 + 筛选 + 游标翻页;
- `item` —— 一个条目的完整信息(多语言名称、标签、各视角缩略图 / 原图、NSFW、出处);
- `fetch` —— 把用户点中的那一张原图下载到插件暂存目录,宿主收走并登记成素材。

**宿主不镜像、不打包、不替插件缓存原图**:浏览只加载插件给的缩略图地址;取用是单条、由人发起,
登记进工作区时把出处一起写进素材的 `media_info`。分享包和 MosaelCloud 同步永远不带这些素材
(姿势 / 服装目前不在 `mosael.asset/1` 的 KINDS 里;以后加也要先看 `external_source`)。
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError, fragment, get_current_locale
from app.db.models import PluginInstance, PluginPackage, User
from app.domain import capabilities
from app.domain.assets.deletion import delete_asset
from app.domain.assets.importer import register_file_asset
from app.domain.assets.media_info import patch_media_info
from app.domain.entities.catalog import DEFAULT_ROLE, KINDS, ROLES_BY_KIND
from app.domain.entities.library import add_reference, create_entity
from app.domain.permissions import ensure_workspace_perm
from app.domain.plugins import instances as inst, tools
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.runtime import CATALOG_OUTPUT_BYTES, PluginRuntimeError
from app.domain.plugins.tools import staged_artifact
from mosael_formats.plugin_manifest import REFERENCE_LIBRARY

QUICK_TIMEOUT_SECONDS = 120
FETCH_TIMEOUT_SECONDS = 900
MAX_ITEMS = 200
ITEM_KINDS = frozenset({"pose", "costume"})


class ReferenceLibraryError(LocalizedError, ValueError):
    """参考库这一侧说不行。带文案 key,按请求方语言翻;api 回 422。"""


def _require(db: Session, instance: PluginInstance) -> None:
    if REFERENCE_LIBRARY not in inst.manifest_for(db, instance).provides:
        raise ReferenceLibraryError("referenceLibErr_notProvided", name=instance.name)


def _text(value: Any, limit: int = 500) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _http(value: Any) -> str:
    text = _text(value, 2000)
    return text if text.startswith(("http://", "https://")) else ""


def _pair(value: Any) -> dict[str, str]:
    """`{"zh":…, "en":…}` 或一个字符串 → 两种语言的名称。插件通常已经按 locale 给了一句,
    这里两种都保留,界面按当前语言挑。"""
    if isinstance(value, dict):
        return {lang: _text(value.get(lang), 300) for lang in ("zh", "en") if _text(value.get(lang), 300)}
    text = _text(value, 300)
    return {"zh": text, "en": text} if text else {}


def _filters(raw: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for one in raw if isinstance(raw, list) else []:
        if not isinstance(one, dict) or not _text(one.get("key"), 80):
            continue
        values = []
        for value in one.get("values") or []:
            if isinstance(value, dict) and value.get("value") is not None:
                values.append({"value": _text(value.get("value"), 120), "label": _text(value.get("label"), 200)})
            elif isinstance(value, str) and value.strip():
                values.append({"value": value.strip()[:120], "label": value.strip()[:200]})
        out.append({"key": _text(one.get("key"), 80), "label": _text(one.get("label"), 200), "values": values})
    return out[:20]


def _collection(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    cid = _text(raw.get("id"), 80)
    kind = _text(raw.get("kind"), 30)
    if not cid or kind not in ITEM_KINDS:
        return None
    return {
        "id": cid,
        "kind": kind,
        "name": _pair(raw.get("name")),
        "count": max(0, int(raw.get("count") or 0)) if isinstance(raw.get("count"), (int, float)) else 0,
        "filters": _filters(raw.get("filters")),
    }


def _view(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    role = _text(raw.get("role"), 40)
    thumb = _http(raw.get("thumbnail"))
    original = _http(raw.get("original"))
    return {"role": role, "thumbnail": thumb, "original": original} if thumb or original else None


def _item(raw: Any, collection: str = "") -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    iid = _text(raw.get("id"), 160)
    kind = _text(raw.get("kind"), 30)
    if not iid or kind not in ITEM_KINDS:
        return None
    views = [one for one in (_view(v) for v in raw.get("views") or []) if one]
    first_view = views[0] if views else {}
    provenance = raw.get("provenance") if isinstance(raw.get("provenance"), dict) else {}
    return {
        "id": iid,
        "collection": _text(raw.get("collection"), 80) or collection,
        "kind": kind,
        "name": _pair(raw.get("name")),
        "tags": [_text(one, 80) for one in raw.get("tags") or [] if _text(one, 80)][:40],
        "thumbnail": _http(raw.get("thumbnail")) or first_view.get("thumbnail", ""),
        "views": views,
        "nsfw": raw.get("nsfw") is True,
        "provenance": {
            "author": _text(provenance.get("author"), 200),
            "url": _http(provenance.get("url")),
            "license": _text(provenance.get("license"), 500),
        },
    }


def connections(db: Session, user_id: str) -> list[dict[str, str]]:
    """这个人接的、启用着且认领了 `reference_library` 的连接。"""
    out: list[dict[str, str]] = []
    rows = db.scalars(select(PluginInstance).where(PluginInstance.owner_user_id == user_id)).all()
    for row in rows:
        package = db.get(PluginPackage, row.package_id)
        if package is None or not row.enabled:
            continue
        try:
            provides = inst.manifest_for(db, row).provides
        except PluginDomainError:
            continue
        if REFERENCE_LIBRARY in provides:
            out.append({"id": row.id, "name": row.name})
    return out


def collections(db: Session, instance: PluginInstance) -> list[dict[str, Any]]:
    _require(db, instance)
    output = tools.invoke_host(
        db, instance.id, REFERENCE_LIBRARY, {"op": "collections", "locale": get_current_locale()},
        timeout=QUICK_TIMEOUT_SECONDS, record=False, output_budget=CATALOG_OUTPUT_BYTES,
    )
    raw = output.get("collections") if isinstance(output, dict) else None
    return [one for one in (_collection(v) for v in raw or []) if one][:50]


def search(
    db: Session,
    instance: PluginInstance,
    *,
    collection: str = "",
    q: str = "",
    filters: dict[str, str] | None = None,
    cursor: str = "",
    limit: int = 40,
) -> dict[str, Any]:
    _require(db, instance)
    output = tools.invoke_host(
        db, instance.id, REFERENCE_LIBRARY,
        {"op": "search", "collection": collection, "q": q, "filters": dict(filters or {}),
         "cursor": cursor, "limit": max(1, min(limit, MAX_ITEMS)), "locale": get_current_locale()},
        timeout=QUICK_TIMEOUT_SECONDS, record=False, output_budget=CATALOG_OUTPUT_BYTES,
    )
    items = [one for one in (_item(raw, collection) for raw in (output.get("items") or [])) if one]
    return {"items": items[:MAX_ITEMS], "next_cursor": _text(output.get("next_cursor"), 500)}


def item(db: Session, instance: PluginInstance, *, item_id: str, collection: str = "") -> dict[str, Any]:
    _require(db, instance)
    output = tools.invoke_host(
        db, instance.id, REFERENCE_LIBRARY,
        {"op": "item", "item_id": item_id, "collection": collection, "locale": get_current_locale()},
        timeout=QUICK_TIMEOUT_SECONDS, record=False,
    )
    found = _item(output.get("item") if isinstance(output.get("item"), dict) else output, collection)
    if found is None:
        raise ReferenceLibraryError("referenceLibErr_badItem")
    return found


def search_everywhere(
    db: Session,
    user_id: str,
    *,
    query: str = "",
    kind: str = "",
    connection_id: str = "",
    limit: int = 12,
    lang: str = "zh",
) -> dict[str, Any]:
    """在这个人接的每个参考库(或指定的那一个)、每本图集里找,给智能体用(`search_references`,ADR 0091 §6)。

    **标了成人内容的条目一条都不交给智能体** —— 插件的开关只管图集里出不出现,界面另有预览图设置兜着;
    智能体读的是文字和链接,没有「模糊」可言。一个连接出错不挡别的连接,出错的那句照实放进 `notes`。
    """
    cap = max(1, min(int(limit or 12), 40))
    items: list[dict[str, Any]] = []
    notes: list[str] = []
    chosen = [one for one in connections(db, user_id) if not connection_id or one["id"] == connection_id]
    for connection in chosen:
        instance = inst.owned(db, connection["id"], user_id)
        if instance is None:
            continue
        try:
            for collection in collections(db, instance):
                if kind and collection["kind"] != kind:
                    continue
                for found in search(db, instance, collection=collection["id"], q=query, limit=cap)["items"]:
                    if found["nsfw"]:
                        continue
                    items.append({
                        "connection_id": connection["id"], "library": connection["name"],
                        "collection": found["collection"], "id": found["id"], "kind": found["kind"],
                        "name": found["name"].get(lang) or found["name"].get("en") or found["id"],
                        "tags": found["tags"][:8], "angles": [view["role"] for view in found["views"]],
                        "thumbnail": found["thumbnail"], "provenance": found["provenance"],
                    })
        except (ReferenceLibraryError, PluginDomainError, PluginRuntimeError) as exc:
            notes.append(f"{connection['name']}: {exc}")
    return {"items": items, "connections": len(chosen), **({"notes": notes} if notes else {})}


def use(
    db: Session,
    user: User,
    instance: PluginInstance,
    *,
    workspace_id: str,
    item_id: str,
    collection: str = "",
    save_entity: bool = False,
) -> dict[str, Any]:
    """把一条外部参考取进工作区:登记成素材,可选再建一个姿势 / 服装资产。

    原图由插件下载到自己的暂存目录,宿主在 `collect` 里拷走 —— 宿主不去直接请求插件给的任意 URL。
    """
    ensure_workspace_perm(db, user, workspace_id, "upload")
    _require(db, instance)
    found = item(db, instance, item_id=item_id, collection=collection)
    held: dict[str, Path] = {}

    def collect(output: dict[str, Any], scratch: Path) -> dict[str, Any]:
        staged = staged_artifact(scratch, output.get("artifact"))
        if staged is None:
            raise ReferenceLibraryError("referenceLibErr_fetchFailed")
        with tempfile.NamedTemporaryFile(prefix="mosael-reference-", suffix=staged.suffix or ".img", delete=False) as handle:
            target = Path(handle.name)
        shutil.copyfile(staged, target)
        held["path"] = target
        return {"artifact": staged.name}

    try:
        tools.invoke_host(
            db, instance.id, REFERENCE_LIBRARY,
            {"op": "fetch", "item_id": found["id"], "collection": found["collection"], "locale": get_current_locale()},
            collect=collect, timeout=FETCH_TIMEOUT_SECONDS, record=True,
        )
        if "path" not in held:
            raise ReferenceLibraryError("referenceLibErr_fetchFailed")
        name = (found["name"].get("zh") or found["name"].get("en") or found["id"])[:160]
        asset = register_file_asset(
            db, workspace_id=workspace_id, project_id=None, source_path=held["path"],
            name=name, source="reference_library",
        )
        if asset.kind != "image":
            delete_asset(db, asset)
            raise ReferenceLibraryError("referenceLibErr_badItem")
        #: 出处就是边界:这个键在分享包 / 云同步里都要被看见(ADR 0091 §3)。
        patch_media_info(db, asset.id, {"external_source": {
            "library": "reference_library", "instance_id": instance.id, "item_id": found["id"],
            "collection": found["collection"], "title": found["name"], **found["provenance"],
        }})
        entity_id = ""
        if save_entity:
            entity = create_entity(
                db, workspace_id=workspace_id, kind=found["kind"], name=name,
                description="; ".join(found["tags"]), prompt="; ".join(found["tags"]),
                tags=found["tags"], actor_id=user.id,
            )
            role = found["views"][0]["role"] if found["views"] else DEFAULT_ROLE.get(found["kind"], "front")
            if role not in ROLES_BY_KIND.get(found["kind"], ()):
                role = DEFAULT_ROLE.get(found["kind"], "front")
            add_reference(db, entity, asset.id, role, cover=True)
            entity_id = entity.id
        return {"asset_id": asset.id, "entity_id": entity_id, "item": found, "provenance": {"instance_id": instance.id,
                "item_id": found["id"], "collection": found["collection"], **found["provenance"]}}
    finally:
        if "path" in held:
            held["path"].unlink(missing_ok=True)


CAPABILITY = capabilities.Capability(
    name=REFERENCE_LIBRARY,
    label_key="capability_reference_library",
    description_key="capability_reference_library",
    pickable=False,
)


def register_uses() -> None:
    capabilities.register_use(capabilities.Use(REFERENCE_LIBRARY, "app", fragment("capUse_referenceLibrary")))


__all__ = [
    "ReferenceLibraryError", "collections", "connections", "item", "search", "search_everywhere", "use", "register_uses",
]
