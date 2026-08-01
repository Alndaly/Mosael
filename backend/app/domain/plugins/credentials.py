"""插件凭据:manifest 声明,用户在设置页填,运行时注入到**它自己**的进程。

插件运行时刻意不透传应用的任何凭据(见 runtime.py 的开头)。那是对的隔离,但代价是
凡是要 API Key 的插件都得自己在插件目录里放一个 config.json —— 用户得开终端 cp 文件,
而且那个文件不在备份、不在同步、也不在任何人的视野里。

这里补上缺口,但不动隔离本身:

- **声明先行**。插件在 manifest 里写清楚它要哪几个键;设置页只渲染这几个,运行时也只注入
  这几个。插件读不到别的插件的键,更读不到供应商的 key。
- **键名即环境变量名**。不做映射表 —— 多一层间接只会让"我填了怎么没生效"变难查。
- **secret 只影响回显**。标了 secret 的值读接口返回掩码,写接口收到掩码原样跳过(和供应商
  配置同一套约定),用户改别的字段时不会把 key 洗成一串星号。
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Plugin, PluginCredential

#: 掩码回显。前端把它原样发回来时表示"这项没改"。
MASK = "********"

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def declared(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """manifest 声明的凭据项。键名不是合法环境变量名的直接丢掉 —— 注入不进去的声明只会
    在设置页里变成一个填了也没用的输入框。"""
    raw = manifest.get("credentials")
    if not isinstance(raw, list):
        return []
    items: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key") or "").strip()
        if not _ENV_NAME.match(key):
            continue
        items.append(
            {
                "key": key,
                "label": str(entry.get("label") or key),
                "help": str(entry.get("help") or ""),
                "secret": entry.get("secret") is not False,  # 默认按密文对待,漏标不该导致明文回显
                "required": entry.get("required") is not False,
            }
        )
    return items


def stored(db: Session, plugin_id: str) -> dict[str, str]:
    """已保存的原值。仅供运行时注入,不要直接出接口。"""
    rows = db.scalars(select(PluginCredential).where(PluginCredential.plugin_id == plugin_id))
    return {row.key: row.value for row in rows}


def describe(db: Session, plugin: Plugin) -> list[dict[str, Any]]:
    """给设置页的清单:声明 + 是否已填 + (非密文时)当前值。"""
    values = stored(db, plugin.id)
    out: list[dict[str, Any]] = []
    for item in declared(plugin.manifest):
        value = values.get(item["key"], "")
        out.append({**item, "filled": bool(value), "value": (MASK if value else "") if item["secret"] else value})
    return out


def set_values(db: Session, plugin: Plugin, values: dict[str, str]) -> None:
    """写入。只接受 manifest 声明过的键;掩码原样回传 = 不改;空串 = 清空。"""
    allowed = {item["key"] for item in declared(plugin.manifest)}
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ValueError(f"插件未声明这些凭据项: {', '.join(unknown)}")
    for key, value in values.items():
        if value == MASK:
            continue
        row = db.get(PluginCredential, {"plugin_id": plugin.id, "key": key})
        if row is None:
            row = PluginCredential(plugin_id=plugin.id, key=key, value=value)
            db.add(row)
        else:
            row.value = value
    db.commit()


def missing(db: Session, plugin: Plugin) -> list[str]:
    """必填但还没填的键。插件启用了却缺 key 时,报"缺 TIKHUB_API_KEY"远比让插件自己
    抛一句 401 有用。"""
    values = stored(db, plugin.id)
    return [item["key"] for item in declared(plugin.manifest) if item["required"] and not values.get(item["key"])]


def env_for(db: Session, plugin: Plugin) -> dict[str, str]:
    """注入给该插件进程的环境变量。只含它自己声明且已填的键。"""
    values = stored(db, plugin.id)
    return {item["key"]: values[item["key"]] for item in declared(plugin.manifest) if values.get(item["key"])}


def expand(text: str, env: dict[str, str]) -> str:
    """把 `${KEY}` 展开成凭据值。MCP 插件的 url / headers 用它 —— 那些字段是 JSON 里的
    字符串,进不了子进程环境。未填的键展开成空串,而不是留着 `${KEY}` 发出去。"""
    return _PLACEHOLDER.sub(lambda m: env.get(m.group(1), ""), text)


__all__ = ["MASK", "declared", "describe", "env_for", "expand", "missing", "set_values", "stored"]
