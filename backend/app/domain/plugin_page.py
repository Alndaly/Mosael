"""插件页与插件市场要读的那几份形状:装了哪些包、我接了哪些实例、市场里每一条长什么样。

此前这些组装写在 `api/routes/plugins.py` 里,路由成了第二个领域层(见 MAINTENANCE_HOTSPOTS §11
「路由只认人、翻错误」)。搬到这里之后,路由只管鉴权和把字典交给响应模型 —— 和 `assets/listing`
同一种分工。这里只读不写,不认识 HTTP,也不引用 `api.schemas`。

**为什么不放进 `domain/plugins/`**:工具的「也用在」要问能力表(`capabilities.used_by`),而能力表
本身认识插件(按插件实例找提供方)。放进 plugins 包就成了包级的环(见 tests/test_import_layering);
它和 `dashboard` 一样是一页的读模型,站在两者之上,没有领域模块会反过来引用它。
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import get_current_locale, render_message
from app.db.models import PluginInstance, PluginMarketHold, PluginPackage, User
from mosael_formats.effects import EFFECTS
from app.domain.plugins import (
    bundled,
    package_sources,
    shared_tables,
    updates,
    instances as inst,
    oauth as plugin_oauth,
    packages as pkg,
    registry as market,
    tools as tools_domain,
)
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.manifest import manifest_of
from mosael_formats.plugin_manifest import text_of, web_url
from app.domain.plugins.nodes import node_meta
from app.domain.workflows.node_catalog import translated_spec, with_data_type


def packages(db: Session, user: User) -> list[dict[str, Any]]:
    """装了哪些包 + **我自己**接的那些实例。

    包是这台机器的事实,人人看得到(否则他不知道有什么可接);实例是他自己的接入,别人的一个
    都不该出现 —— 此前这里不做过滤,新账号一进插件页就看到管理员接好的一排。
    """
    out: list[dict[str, Any]] = []
    shipped = {one.id for one in bundled.plugins()}
    for package in db.scalars(select(PluginPackage).order_by(PluginPackage.name)):
        manifest = manifest_of(package)
        out.append(
            {
                "id": package.id,
                #: 名字从清单现取,不取库里那一列 —— 那一列是装的时候定的,装的人是什么语言
                #: 就一直是什么语言;清单里若写了多语言,这里才跟得上看的人。
                "name": manifest.name,
                "version": package.version,
                "summary": manifest.summary,
                "description": manifest.description,
                #: 和市场条目同一个形状、同一个算法(registry.market_tools):「关于」里的工具和市场里的一致。
                "tools": market.market_tools(manifest),
                "kind": manifest.runtime.kind,
                "multiple": manifest.multiple,
                "permissions": manifest.permissions,
                "homepage": manifest.homepage,
                "author_name": manifest.author.name,
                "author_url": manifest.author.url,
                "docs": manifest.docs,
                "config_fields": [_field(f) for f in manifest.config],
                "summary_field": _summary_field(manifest),
                "credential_fields": [_field(f) for f in manifest.credentials],
                #: 声明了 OAuth 就给一个「去授权」的入口,不必手抄令牌(见 domain/plugins/oauth)。
                #: 声明不全的当没声明 —— 半个声明会长出一个点了必然失败的按钮。
                "oauth": (
                    {"fills": [one.key for one in plugin_oauth.fills(manifest.oauth, manifest.credentials)]}
                    if manifest.oauth is not None
                    else None
                ),
                "provides": manifest.provides,
                "generation_noun": manifest.generation_noun,
                #: 能起哪几种本机服务(ADR 0041):连接页上据此摆「本机服务」那张卡。
                "services": [{"key": one.key, "title": one.title} for one in manifest.services],
                "bundled": package.id in shipped,
                "instances": [
                    instance_view(db, i)
                    for i in pkg.instances_of(db, package.id)
                    if i.owner_user_id == user.id
                ],
            }
        )
    return out


def instance_view(db: Session, instance: PluginInstance) -> dict[str, Any]:
    """一个接入在插件页上的样子:配置、授权、工具清单(带勾选与表单)、各项能力的状态。"""
    chosen = inst.exposed_tools(db, instance.id)
    tools = tools_domain.all_tools(db, instance)
    return {
        "id": instance.id,
        "package_id": instance.package_id,
        "name": instance.name,
        "enabled": instance.enabled,
        "config": instance.config or {},
        "blocked_reason": inst.blocked_reason(db, instance),
        "pending_permissions": inst.pending_permissions(db, instance),
        "permissions_added": inst.permissions_added(db, instance),
        "authorization": inst.authorization_state(db, instance),
        # internal 的工具只给宿主适配层用,勾选列表里不出现 —— 勾上也不会暴露,列出来只会让人以为能。认领调用类能力的
        # (MinerU 的解析)是普通工具,在这张表里,带着能力和「也用在」(ADR 0033)。
        #: `input_schema` 里重复的大表按内容收一次(见 domain/plugins/shared_tables):界面读的是 `form`,
        #: 这份原始的声明一个字段都不读它 —— 收完这一份 2,929,540 字节的工具清单少 23 万字节,而展平回来
        #: 逐字节相同。`form` 原样不动(界面按它的 `options` 直接画下拉)。
        "tools": [{**tool, "exposed": tool["name"] in chosen, "form": _tool_form(tool),
                   "used_by": _used_by(tool["provides"]),
                   "input_schema": shared_tables.share(tool["input_schema"] or {})}
                  for tool in tools if not tool["internal"]],
        "capability_status": {
            capability: _capability_status(status)
            for capability, status in (instance.capability_status or {}).items()
            if isinstance(status, dict)
        },
        "network": {"mode": instance.network_mode, "proxy_url": instance.proxy_url},
        "package_sources": package_sources.describe(inst.manifest_for(db, instance).package_sources,
                                                    instance.package_sources),
    }


def market_page(db: Session) -> dict[str, Any]:
    """市场里有什么。

    **随应用内置的插件总在里面**,不管远端索引有没有它、拉不拉得到:它就装在这台机器上,
    条目由本地那份清单生成(版本也是本地的)。远端若也列了它,以本地为准 —— 内置插件的新版
    跟着应用发,远端的版本号不该在这里长出一个「更新」。
    """
    installed = {row.id: row for row in db.scalars(select(PluginPackage))}
    shipped = [one for one in bundled.plugins() if one.id in installed]
    index_error = ""
    try:
        remote = market.fetch_index(market.index_url(db))
    except PluginDomainError as exc:
        remote, index_error = [], str(exc)
    local_ids = {one.id for one in shipped}
    entries = [market.bundled_entry(manifest_of(installed[one.id])) for one in shipped] + [
        entry for entry in remote if entry["id"] not in local_ids
    ]
    holds = updates.holds(db)
    return {
        "plugins": [_market_entry(entry, installed, holds) for entry in entries],
        "index_error": index_error,
    }


def _market_entry(
    entry: dict[str, Any], installed: dict[str, PluginPackage], holds: dict[str, PluginMarketHold]
) -> dict[str, Any]:
    package = installed.get(entry["id"])
    update = updates.state_of(entry, package, holds.get(entry["id"]))
    return {
        **{key: str(entry.get(key, "")) for key in ("id", "version", "author", "homepage", "download", "sha256")},
        "author_url": web_url(entry.get("author_url")),
        #: docs 在索引里也可以按语言分,和名字、简介一样在这儿定语言。
        "docs": web_url(text_of(entry.get("docs"))),
        #: 索引里的名字和简介照搬清单,而清单里它们可以是按语言分的对象 —— 在这儿定语言。
        "name": text_of(entry.get("name")),
        "summary": text_of(entry.get("summary")),
        "description": text_of(entry.get("description")),
        "permissions": [p for p in (entry.get("permissions") or []) if isinstance(p, str)],
        "runtime": str(entry.get("runtime") or "process"),
        "provides": [p for p in (entry.get("provides") or []) if isinstance(p, str)],
        "tools": [
            {
                "name": str(tool["name"]),
                "label": text_of(tool.get("label")),
                "description": text_of(tool.get("description")),
                #: 索引里写了什么就是什么;不认识的值当没写(界面不标),不在这里替它猜。
                "effects": str(tool.get("effects")) if tool.get("effects") in EFFECTS else "",
            }
            for tool in (entry.get("tools") or [])
            if isinstance(tool, dict) and tool.get("name")
        ],
        "installed": package is not None,
        "installed_version": package.version if package else "",
        "update_available": update.available,
        "update_unreleased": update.unreleased,
        "bundled": entry.get("bundled") is True,
    }


_TEMPLATE_KEY = re.compile(r"\{([A-Za-z0-9_]+)(?::label)?\}")


def _summary_field(manifest) -> str:
    """插件页上**收起的连接**那一行摆哪一项配置(「关键地址」):名字模板里引用的第一个配置项(ComfyUI 的
    `{server_url}`、TikHub 的 `{platform:label}`);没写模板就是第一个必填的文本配置项;都没有就是空串(不摆)。"""
    config = {field.key: field for field in manifest.config}
    for key in _TEMPLATE_KEY.findall(manifest.name_template or ""):
        if key in config:
            return key
    return next((field.key for field in manifest.config if field.required and field.type == "string"), "")


def _field(spec) -> dict[str, Any]:
    return {
        "key": spec.key,
        "label": spec.label,
        "type": spec.type,
        "help": spec.help,
        "required": spec.required,
        "secret": spec.secret,
        "options": spec.options,
        "default": spec.default,
        "multiline": spec.multiline,
        "language": spec.language,
    }


def _used_by(provides: list[str]) -> list[dict[str, Any]]:
    from app.domain import capabilities

    return [{"capability": capability, **use} for capability in provides for use in capabilities.used_by(capability)]


def _tool_form(tool: dict[str, Any]) -> dict[str, Any]:
    """插件页「试一下」那张表单的字段 —— **和这个工具在工作流里当节点时是同一份声明**(名字、素材选择器、
    下拉、数字框、高级那一档),前端用同一个表单组件渲染。选连接那一格不要:试跑就是在这个连接上。"""

    locale = get_current_locale()
    config = node_meta(tool).get("config") or {}
    return {
        key: translated_spec(key, with_data_type(key, spec), locale)
        for key, spec in config.items()
        if key != "instance_id" and isinstance(spec, dict)
    }


def _capability_status(status: dict[str, Any]) -> dict[str, Any]:
    """落库的那一份(失败原因存的是文案 key + 参数,见 jobs.blame)→ 按看的人的语言说出来。"""
    key = str(status.get("error_key") or "")
    error = render_message(key, get_current_locale(), status.get("error_params") or {}) if key else str(
        status.get("error") or ""
    )
    return {
        "models": status.get("models"),
        "tools": status.get("tools"),
        "refreshed_at": status.get("refreshed_at"),
        "error": error,
    }
