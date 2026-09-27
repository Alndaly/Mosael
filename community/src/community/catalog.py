"""把官网静态索引里的官方条目导进社区(ADR 0026 第 4 节:「迁移成一个 `official` 作者名下的条目」)。

来源:`<官网 public>/plugins/registry.json`(插件)、`<官网 public>/workflows/catalog.json` 与它指到的
`*.mosael-workflow.json`(工作流,每个有中英两份文件)。

**幂等**:跑第二次不会多出任何东西。条目按 slug 认;插件的版本号变了才加一个新版本,工作流的文件内容
(按哈希)变了才加一个新版本;标题、简介、附带信息每次按索引覆盖。官方插件的包在 GitHub Release 上,
这里不搬文件,下载直接指过去;官方工作流的文件搬进存储(下载也要计数)。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from community.context import Context
from community.crypto import sha256_hex
from community.db import utcnow
from community.logs import log_event
from community.models import KIND_PLUGIN, KIND_WORKFLOW, VERSION_APPROVED, Item, ItemVersion, User
from community.storage import attachment
from community.submissions import publish_version, search_text
from mosael_formats import workflow_file
from mosael_formats.i18n import DEFAULT_LOCALE

logger = logging.getLogger(__name__)

OFFICIAL_HANDLE = "official"
#: 官方插件 id 的前缀。官方条目的 slug 要和官网现有的地址一致(文档里到处链着它们):插件是目录名
#: (`dev.mosael.baidu-pan` → `baidu-pan`,tests/test_items.py 核对它和 plugins/ 下的目录名一一对应),
#: 工作流是模板 id 把 `_` 换成 `-`。
OFFICIAL_PLUGIN_PREFIX = "dev.mosael."


def official_plugin_slug(plugin_id: str) -> str:
    return plugin_id.removeprefix(OFFICIAL_PLUGIN_PREFIX)


def official_workflow_slug(template_id: str) -> str:
    return template_id.replace("_", "-")


@dataclass
class SeedReport:
    created: list[str] = field(default_factory=list)
    new_versions: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)


def official_user(db: Session) -> User:
    user = db.scalars(select(User).where(User.handle == OFFICIAL_HANDLE)).first()
    if user is None:
        user = User(handle=OFFICIAL_HANDLE, display_name="Mosael", is_official=True)
        db.add(user)
        db.flush()
    user.is_official = True
    return user


def _item(db: Session, kind: str, slug: str, owner: User) -> tuple[Item, bool]:
    item = db.scalars(select(Item).where(Item.kind == kind, Item.slug == slug)).first()
    if item is not None:
        return item, False
    item = Item(kind=kind, slug=slug, owner_id=owner.id, official=True, title="", summary="", extra={}, created_at=utcnow())
    db.add(item)
    db.flush()
    return item, True


def _next_number(db: Session, item: Item) -> int:
    return int(db.scalar(select(func.coalesce(func.max(ItemVersion.number), 0)).where(ItemVersion.item_id == item.id)) or 0) + 1


def _latest(db: Session, item: Item) -> ItemVersion | None:
    return db.scalars(select(ItemVersion).where(ItemVersion.item_id == item.id).order_by(ItemVersion.number.desc()).limit(1)).first()


def seed_plugins(db: Session, owner: User, registry: dict[str, Any], report: SeedReport) -> None:
    for entry in registry.get("plugins") or []:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        plugin_id = str(entry["id"])
        item, created = _item(db, KIND_PLUGIN, official_plugin_slug(plugin_id), owner)
        item.plugin_id = plugin_id
        item.official = True
        item.owner_id = owner.id
        item.title = entry.get("name") or plugin_id
        item.summary = entry.get("description") or ""
        item.search_text = search_text(item.title, item.summary, plugin_id)
        latest = _latest(db, item)
        version_label = str(entry.get("version") or "0.0.0")
        if latest is not None and latest.version == version_label:
            latest.meta = {**(latest.meta or {}), "index_entry": entry}
            latest.external_download = entry.get("download") or None
            publish_version(item, latest)
            report.unchanged.append(f"plugin:{plugin_id}")
            continue
        version = ItemVersion(
            item_id=item.id,
            number=_next_number(db, item),
            version=version_label,
            status=VERSION_APPROVED,
            submitter_id=owner.id,
            external_download=entry.get("download") or None,
            meta={"index_entry": entry, "official": True},
            reviewed_at=utcnow(),
        )
        db.add(version)
        db.flush()
        publish_version(item, version)
        (report.created if created else report.new_versions).append(f"plugin:{plugin_id}")


def seed_workflows(ctx: Context, db: Session, owner: User, root: Path, report: SeedReport) -> None:
    catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
    for entry in catalog:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        slug = official_workflow_slug(str(entry["id"]))
        files: dict[str, bytes] = {}
        for locale, href in (entry.get("download") or {}).items():
            path = root / Path(str(href)).name
            files[str(locale)] = path.read_bytes()
        if not files:
            continue
        default_locale = DEFAULT_LOCALE if DEFAULT_LOCALE in files else next(iter(files))
        documents = {locale: json.loads(data.decode("utf-8")) for locale, data in files.items()}
        envelopes = {locale: workflow_file.read_workflow_file(doc) for locale, doc in documents.items()}
        for envelope in envelopes.values():
            workflow_file.check_graph(envelope.graph)
        summary = workflow_file.summarize_graph(envelopes[default_locale].graph)

        item, created = _item(db, KIND_WORKFLOW, slug, owner)
        item.official = True
        item.owner_id = owner.id
        item.title = entry.get("name") or slug
        item.summary = entry.get("summary") or ""
        item.extra = {key: entry[key] for key in ("requires", "stages") if key in entry}
        item.search_text = search_text(item.title, item.summary, slug)

        fingerprint = sha256_hex("".join(sha256_hex(files[locale]) for locale in sorted(files)))
        latest = _latest(db, item)
        if latest is not None and (latest.meta or {}).get("fingerprint") == fingerprint:
            publish_version(item, latest)
            report.unchanged.append(f"workflow:{slug}")
            continue
        number = _next_number(db, item)
        version = ItemVersion(
            item_id=item.id,
            number=number,
            version=str(entry.get("version") or number),
            status=VERSION_APPROVED,
            submitter_id=owner.id,
            meta={
                "graph": envelopes[default_locale].graph,
                "graphs": {locale: envelope.graph for locale, envelope in envelopes.items()},
                "summary": {
                    "node_count": summary.node_count,
                    "node_types": summary.node_types,
                    "code_node_types": summary.code_node_types,
                    "plugin_ids": summary.plugin_ids,
                },
                "fingerprint": fingerprint,
                "official": True,
            },
            reviewed_at=utcnow(),
        )
        # 官方工作流的版本号就是索引里的那个;同号而内容变了(维护者忘了加版本号)就补一个序号区分。
        if db.scalar(select(func.count()).select_from(ItemVersion).where(ItemVersion.item_id == item.id, ItemVersion.version == version.version)):
            version.version = f"{version.version}.{number}"
        db.add(version)
        db.flush()
        localized: dict[str, dict] = {}
        for locale, data in files.items():
            name = f"{slug}.{locale}{workflow_file.SUFFIX}"
            key = f"files/workflows/{item.id}/{version.id}/{name}"
            ctx.storage.put_bytes(key, data, content_type="application/json", disposition=attachment(name))
            localized[locale] = {"key": key, "sha256": sha256_hex(data), "size": len(data)}
        version.localized_files = localized
        version.file_key = localized[default_locale]["key"]
        version.file_sha256 = localized[default_locale]["sha256"]
        version.file_size = localized[default_locale]["size"]
        publish_version(item, version)
        (report.created if created else report.new_versions).append(f"workflow:{slug}")


def seed_official(ctx: Context, db: Session, catalog_dir: Path) -> SeedReport:
    report = SeedReport()
    owner = official_user(db)
    registry_path = catalog_dir / "plugins" / "registry.json"
    if registry_path.is_file():
        seed_plugins(db, owner, json.loads(registry_path.read_text(encoding="utf-8")), report)
    workflows_dir = catalog_dir / "workflows"
    if (workflows_dir / "catalog.json").is_file():
        seed_workflows(ctx, db, owner, workflows_dir, report)
    db.commit()
    log_event(
        logger,
        "official catalog seeded",
        created=len(report.created),
        new_versions=len(report.new_versions),
        unchanged=len(report.unchanged),
    )
    return report


__all__ = ["OFFICIAL_HANDLE", "SeedReport", "official_plugin_slug", "official_workflow_slug", "official_user", "seed_official"]
