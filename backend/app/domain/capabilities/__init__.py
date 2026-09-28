"""宿主能力:插件(和宿主自带的实现)能替 Mosael 做成的那几件事 —— 一张表,一套挑法(ADR 0031 §5)。

此前每多一项 `provides`,宿主就各写一套:清单里的特判、默认连接的设置页、调用时挑哪一家、挑不出来时说哪句话
(素材外链是第一项,它的挑法写在 generation/public_links 里)。第二项(文档解析)再照抄一遍,第三项还要再抄。
现在每项能力登记一份契约(`Capability`),挑法只有这里一份:

- **候选**:宿主自带的实现(有的话,排第一)+ 这个人**自己的**、启用着的、声明了这项能力的插件连接 ——
  按声明找,不按名字猜;
- **挑哪一家**:他定了默认就用它;没定时,有内置实现的用内置的,没有的只有一家配好才不问就用(`auto_single`),
  几家都配好了就当场问,不替他挑;
- **挑不出来**时各说各的下一步(没有连接、没配好、几家没定、插件太旧),文案 key 由契约给;
- 「设置 → 能力提供方」一页按这张表列出每项能力的候选和当前选择。

内置实现和插件在候选表里是同一种东西(`Provider`):调用方拿到一个提供方,不关心它是内置的还是哪个插件 ——
以后把内置实现拆成插件,调用方一行不改。

**这里不认识任何一项能力的宿主侧**:外链由 generation/public_links、文档解析由 documents 各自定义契约,
在组装根登记进来(见 app.main._wire_seams),和 plugins/host_capabilities 同一个手法。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError, tr

logger = logging.getLogger(__name__)


class CapabilityUnavailable(LocalizedError, RuntimeError):
    """这一次挑不出能用的提供方。消息给用户看,要说清下一步;每项能力可以有自己的子类(调用方按它认)。"""


@dataclass(frozen=True)
class Builtin:
    """宿主自带的实现。`id` 以 `builtin:` 开头,和插件连接的 id 分得开。"""

    id: str
    #: 在设置页和结果上叫什么(i18n key)。
    name_key: str


@dataclass(frozen=True)
class Capability:
    """一项宿主能力的契约。名字就是插件清单里 `provides` 写的那个。"""

    name: str
    label_key: str
    description_key: str
    #: 挑不出来时抛哪一种(调用方按它 catch)。
    error: type[CapabilityUnavailable] = CapabilityUnavailable
    #: 挑不出来时的四句话(i18n key)。参数:`plugin` 那一家的名字、`missing` 缺的项、`names` 几家的名字,
    #: 再加上调用方给的(`subject`,比如素材名)。
    none_key: str = "capErr_none"
    incomplete_key: str = "capErr_incomplete"
    ambiguous_key: str = "capErr_ambiguous"
    outdated_key: str = "capErr_outdated"
    builtin: Builtin | None = None
    #: 没定默认、也没有内置实现时,只有一家配好就不问直接用。**数据会离开本机的能力**(文档交给云端解析)
    #: 不该这样:用哪家必须他自己定过。
    auto_single: bool = True


@dataclass(frozen=True)
class Provider:
    """一个候选:内置实现,或一个插件连接。"""

    id: str
    name: str
    builtin: bool = False
    #: 还缺哪些项(配置、凭据、待授予的权限);缺了就用不了。
    missing: tuple[str, ...] = ()
    instance: Any = None
    #: 插件里认领这项能力的那个工具;空 = 插件太旧(包上声明了、没有工具认领)。
    tool: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


_registry: dict[str, Capability] = {}


def register(capability: Capability) -> None:
    """某项能力的宿主侧登记自己的契约。同一项登记两次是装配错误,不是覆盖。"""
    if capability.name in _registry and _registry[capability.name] is not capability:
        raise RuntimeError(f"capability {capability.name!r} registered twice")
    _registry[capability.name] = capability


def get(name: str) -> Capability | None:
    return _registry.get(name)


def registered() -> list[Capability]:
    """登记过的全部能力,按名字排(设置页照这个顺序列)。"""
    return [_registry[name] for name in sorted(_registry)]


def _missing(db: Session, instance: Any) -> tuple[str, ...]:
    """这个连接还缺哪些项:配置、凭据、待授予的权限。

    和 `instances.blocked_reason` 用的是同几道门(missing_config / missing_credentials / permissions_granted),
    不另写一份判定 —— 否则设置页下拉里选得到、真解析时才被权限挡回来,两边说的不是一回事。
    """
    from app.domain.plugins import instances as inst

    absent = inst.missing_config(db, instance) + inst.missing_credentials(db, instance)
    if not inst.permissions_granted(db, instance):
        absent.append(tr("capMissing_permissions"))
    return tuple(absent)


def plugin_providers(db: Session, owner_user_id: str | None, capability: Capability) -> list[Provider]:
    """这个人**自己的**、启用着的、声明了这项能力的插件连接,按名字排。装坏了的插件跳过,不拖垮整条链。"""
    from app.db.models import PluginInstance
    from app.domain.plugins import instances as inst

    if not owner_user_id:
        return []
    found: list[Provider] = []
    rows = db.scalars(select(PluginInstance).where(
        PluginInstance.owner_user_id == owner_user_id, PluginInstance.enabled.is_(True),
    ))
    for instance in rows:
        try:
            manifest = inst.manifest_for(db, instance)
        except Exception:  # noqa: BLE001
            logger.warning("读不出插件 %s 的清单,跳过", instance.id, exc_info=True)
            continue
        if capability.name not in manifest.provides:
            continue
        found.append(Provider(id=instance.id, name=instance.name or "", missing=_missing(db, instance),
                              instance=instance, tool=manifest.tool_providing(capability.name)))
    return sorted(found, key=lambda one: one.name)


def _builtin(capability: Capability) -> Provider | None:
    if capability.builtin is None:
        return None
    return Provider(id=capability.builtin.id, name=tr(capability.builtin.name_key), builtin=True)


def providers(db: Session, owner_user_id: str | None, capability: Capability) -> list[Provider]:
    """全部候选:内置的排第一,再是插件连接。"""
    builtin = _builtin(capability)
    return ([builtin] if builtin else []) + plugin_providers(db, owner_user_id, capability)


def _default_id(db: Session, owner_user_id: str | None, capability: Capability) -> str | None:
    from app.domain.plugins import capability_defaults

    return capability_defaults.default_of(db, owner_user_id, capability.name) if owner_user_id else None


def _automatic(capability: Capability, candidates: list[Provider]) -> Provider | None:
    """**不定默认**时会用哪一家:有内置的用内置的;没有的,只有一家配好(且这项能力允许)才用它。"""
    builtin = next((one for one in candidates if one.builtin), None)
    if builtin:
        return builtin
    ready = [one for one in candidates if not one.missing]
    return ready[0] if capability.auto_single and len(ready) == 1 else None


def choices(db: Session, owner_user_id: str, capability: Capability) -> dict[str, Any]:
    """设置页那一格要画的:候选(配没配好、缺什么)、他定的那家、不定时实际会用哪家。"""
    candidates = providers(db, owner_user_id, capability)
    chosen = _default_id(db, owner_user_id, capability)
    if chosen not in {one.id for one in candidates}:
        chosen = None
    automatic = _automatic(capability, candidates)
    return {
        "capability": capability.name,
        "label": tr(capability.label_key),
        "description": tr(capability.description_key),
        "current": chosen,
        #: **不选的话**会用哪一家 —— 和当前选没选无关(选定之后它不改口)。
        "automatic": automatic.id if automatic else None,
        "options": [{"id": one.id, "name": one.name, "builtin": one.builtin, "missing": list(one.missing)}
                    for one in candidates],
    }


def choose(db: Session, owner_user_id: str | None, capability: Capability, **subject: Any) -> Provider:
    """挑出这一次用哪一家;挑不出来时抛 `capability.error`,消息说清下一步。`subject` 进文案(比如素材名)。"""
    sep = tr("punct_listSep")

    def fail(key: str, **params: Any) -> CapabilityUnavailable:
        return capability.error(key, **params, **subject)

    candidates = plugin_providers(db, owner_user_id, capability)
    chosen_id = _default_id(db, owner_user_id, capability)
    chosen = next((one for one in candidates if one.id == chosen_id), None)
    if chosen is None:
        builtin = _builtin(capability)
        if builtin is not None:
            return builtin
        if not candidates:
            raise fail(capability.none_key)
        ready = [one for one in candidates if not one.missing]
        if capability.auto_single and len(ready) == 1:
            chosen = ready[0]
        elif not ready:
            raise fail(capability.incomplete_key, plugin=candidates[0].name, missing=sep.join(candidates[0].missing))
        else:
            raise fail(capability.ambiguous_key, names=sep.join(one.name for one in ready))
    if chosen.missing:
        raise fail(capability.incomplete_key, plugin=chosen.name, missing=sep.join(chosen.missing))
    if not chosen.tool:
        raise fail(capability.outdated_key, plugin=chosen.name)
    return chosen


def pick(db: Session, owner_user_id: str | None, capability: Capability, provider_id: str | None, **subject: Any) -> Provider:
    """点名用哪一家(界面上「用 ×× 重新解析」);没点名就按默认挑(choose)。点名的得是他自己的、配好了的。"""
    if not provider_id:
        return choose(db, owner_user_id, capability, **subject)
    builtin = _builtin(capability)
    if builtin is not None and provider_id == builtin.id:
        return builtin
    found = next((one for one in plugin_providers(db, owner_user_id, capability) if one.id == provider_id), None)
    if found is None:
        raise capability.error(capability.none_key, **subject)
    if found.missing:
        raise capability.error(capability.incomplete_key, plugin=found.name,
                               missing=tr("punct_listSep").join(found.missing), **subject)
    if not found.tool:
        raise capability.error(capability.outdated_key, plugin=found.name, **subject)
    return found


def set_default(db: Session, owner_user_id: str, capability: Capability, provider_id: str | None) -> None:
    """定下(或清掉)这个人在这项能力上的默认。选内置的 = 清掉(没定默认时本来就用内置的)。"""
    from app.domain.plugins import capability_defaults

    builtin = capability.builtin
    if provider_id is None or (builtin is not None and provider_id == builtin.id):
        capability_defaults.set_default(db, owner_user_id, capability.name, None)
        return
    capability_defaults.set_default(db, owner_user_id, capability.name, provider_id)


__all__ = [
    "Builtin",
    "Capability",
    "CapabilityUnavailable",
    "Provider",
    "choices",
    "choose",
    "get",
    "pick",
    "plugin_providers",
    "providers",
    "register",
    "registered",
    "set_default",
]
