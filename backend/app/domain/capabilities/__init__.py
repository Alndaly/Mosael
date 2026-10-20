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
在组装根登记进来(见 app.main._wire_seams)。

**只有这一张表**(ADR 0032 §1)。生成、工具清单也登记在这里,只是不参与挑选(`pickable=False`:生成按「连接 +
模型」挑,工具清单是每个连接自己报的);它们在表里是为了叫得出名字、说得出用在哪,以及挂上**插件实例变了
之后宿主侧怎么跟着对齐**的钩子(`on_instance_change` / `listing`)。插件域经 plugins/host_capabilities 转发通知,
但不再自己存一张登记表 —— 组装根把 `instance_hooks` 交给它查(插件域照旧不 import 这里)。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, NoReturn

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError, tr

logger = logging.getLogger(__name__)


class CapabilityUnavailable(LocalizedError, RuntimeError):
    """这一次挑不出能用的提供方。消息给用户看,要说清下一步;每项能力可以有自己的子类(调用方按它认)。"""


@dataclass(frozen=True)
class Builtin:
    """宿主自带的实现。`id` 以 `builtin:` 开头,和插件连接的 id 分得开。

    一项能力可以有几个(ADR 0032 §1):降噪的 ffmpeg / rnnoise / deepfilternet、分离的 demucs……本地引擎就是
    内置提供方,和插件连接并列在候选里。
    """

    id: str
    #: 在设置页和结果上叫什么(i18n key)。
    name_key: str
    #: 这个人此刻缺什么(没装依赖、没拉权重、没配那条连接):`ready(db, owner_user_id)` 回一串给人看的说明,
    #: 空 = 跑得起来。不给 = 总是跑得起来。带着人:要钥匙的内置实现(配音的 OpenAI、翻译的对话模型)看的是**他**
    #: 配没配好 —— 钥匙归人。
    ready: Callable[[Session, str | None], tuple[str, ...]] | None = None
    #: 没人定默认时能不能自动用它。会顺手去掉配乐的语音降噪模型就不能 —— 用户说「降噪」没要求把音乐拿掉。
    automatic: bool = True


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
    #: 点名了一家,却不在候选里(参数 `name`:点的那个 id;`available`:这台机器上现在能用的几家)。
    unknown_key: str = "capErr_unknown"
    #: 和上一句同一种错,但**一家能用的都没有**(参数 `name`)。**空 = 不区分**,照旧用 `unknown_key` ——
    #: 只有少数能力(翻译)那句话的下一步不一样,不替所有能力改口。
    unknown_none_key: str = ""
    incomplete_key: str = "capErr_incomplete"
    ambiguous_key: str = "capErr_ambiguous"
    outdated_key: str = "capErr_outdated"
    #: 宿主自带的实现,按挑选的先后排(没人定默认时用第一个 `automatic` 且跑得起来的)。
    builtins: tuple[Builtin, ...] = ()
    #: 旧 id → 规范 id(小写比较)。**只在 `canonical_id` 里解析一次**:改名之后,老工作流、老画板、
    #: 智能体工具、第三方客户端手里仍是旧 id —— 让每个调用点各认一遍,迟早会漏掉一处,而且每处认法
    #: 还会慢慢不一样。不把旧 id 注册成第二个实现:那会让下拉里出现两个同一家的选项。
    aliases: tuple[tuple[str, str], ...] = ()
    #: 没定默认、也没有内置实现时,只有一家配好就不问直接用。**数据会离开本机的能力**(文档交给云端解析)
    #: 不该这样:用哪家必须他自己定过。
    auto_single: bool = True
    #: 这项能力有没有「默认用哪家」。配音也有,只是它的默认是**一对**(引擎 + 音色),见 `default_shape`。
    defaultable: bool = True
    #: 默认那一行画什么:`provider` = 一个下拉(选一家提供方);`engine_voice` = 两个控件(引擎 + 音色),
    #: 给配音:引擎和音色是成对选的(克隆音色的 id 换到 Edge 上就是错的),单独一个下拉设不出默认。
    default_shape: str = "provider"
    #: 走不走这里的挑法。生成(按连接 + 模型挑,ADR 0020)和工具清单(每个连接自己报)不走:它们没有候选、没有默认,
    #: 不进设置页,`get` 查不到;表里只留名字、用在哪和下面两个钩子。
    pickable: bool = True
    #: 插件实例变了(改名、换服务器、启停、授权、凭据),宿主那一侧怎么跟着对齐:`(db, instance, refresh)`。
    #: `refresh` = 这次变动可能让「插件能做什么」变了,该重新问插件一遍。经 plugins/host_capabilities.notify 调。
    on_instance_change: Callable[[Session, Any, bool], None] | None = None
    #: 这个实例在这项能力上做出来的东西怎么列给插件页(生成 → 它提供的模型)。
    listing: Callable[[Session, Any], list[dict[str, Any]]] | None = None


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


#: 宿主内置实现的 id 前缀(`builtin:funasr`、`builtin:rnnoise`)。内置实现和插件连接在候选表里
#: 是同一类,只由这个前缀分得开 —— 各家能力此前各写一遍字面量,谁要按前缀拆引擎名都得先 import
#: 那一家。放在契约这一层,是因为它描述的是**提供方 id 的形状**,不是某一项能力的细节。
BUILTIN_PREFIX = "builtin:"

_registry: dict[str, Capability] = {}
#: 调用类能力的收尾(ADR 0033 §3):智能体、工作流、插件页调了认领它的工具之后,插件交回的产出怎么交给调用方
#: (文档解析 → 存成那份文档的一次解析)。没登记 = 按通用规矩收(文件进素材库、别的原样交回)。宿主自己的入口
#: 有自己的落点,不走它。`(db, plugins.host_capabilities.CapabilityCall) -> dict`。
#:
#: 不是 `Capability` 上的一格:收尾要读写宿主数据(文档的解析行),住在那一侧的深处;契约本身(documents/__init__)
#: 被那一侧 import,反过来指着它就是一个环。所以和「用在哪」一样,由组装根登记。
_finishers: dict[str, Callable[[Session, Any], dict[str, Any]]] = {}


def register(capability: Capability) -> None:
    """某项能力的宿主侧登记自己的契约。同一项登记两次是装配错误,不是覆盖。"""
    if capability.name in _registry and _registry[capability.name] is not capability:
        raise RuntimeError(f"capability {capability.name!r} registered twice")
    _registry[capability.name] = capability


def register_finish(name: str, finish: Callable[[Session, Any], dict[str, Any]]) -> None:
    """某项调用类能力登记它的收尾(组装根调)。"""
    if name in _finishers and _finishers[name] is not finish:
        raise RuntimeError(f"capability {name!r} finish registered twice")
    _finishers[name] = finish


def get(name: str) -> Capability | None:
    """一项**走挑法**的能力;生成、工具清单这类不参与挑选的查不到(见 `pickable`)。"""
    found = _registry.get(name)
    return found if found is not None and found.pickable else None


def registered() -> list[Capability]:
    """走挑法的全部能力,按名字排(设置页照这个顺序列)。"""
    return [_registry[name] for name in sorted(_registry) if _registry[name].pickable]


def instance_hooks(name: str) -> tuple[Any, Any, Any]:
    """这项能力插到插件域的三个钩子:实例变动时的对齐、列清单,调用之后的收尾;没登记这项能力或没有钩子时是 None。
    组装根把它交给 plugins/host_capabilities 查 —— 插件域不 import 这里。"""
    found = _registry.get(name)
    return (found.on_instance_change if found else None, found.listing if found else None, _finishers.get(name))


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


# ── 用在哪(ADR 0032 §4)────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Use:
    """一处用到某项能力的地方:插件页、设置页照这份列出「它用在哪」—— **现算,不手写**。

    `kind`:`app`(宿主界面上的一个入口)/ `workflow`(工作流或画板的一个节点字段)/ `agent`(智能体的一个工具)。
    `label` 是 `core.i18n.fragment` 的半句(带 key 的小字典),读的时候按读的人的语言展开。
    """

    capability: str
    kind: str
    label: Any


#: 宿主界面入口:各自领域在组装根登记一条(`register_use`)。
_uses: list[Use] = []
#: 从别的注册表现算的(工作流节点、智能体工具):登记一个函数,每次问的时候扫一遍 —— 新节点、新工具声明了
#: 就自动出现,不用再来这里补一行。
_use_finders: list[Callable[[], list[Use]]] = []


def register_use(use: Use) -> None:
    if use not in _uses:
        _uses.append(use)


def register_use_finder(finder: Callable[[], list[Use]]) -> None:
    if finder not in _use_finders:
        _use_finders.append(finder)


def uses_of(name: str, *, settings: bool = True) -> list[Use]:
    """这项能力用在哪。设置页的「设成默认」是每项能力都有的,排第一;再是登记的入口,最后是现算的。
    `settings=False`:设置页自己列的时候不带那一条 —— 在「能力提供方」里写「能力提供方:设成默认」是废话。"""
    from app.core.i18n import fragment

    #: 没有默认的能力不在设置里「设成默认」(今天每一项都有,包括配音 —— 它的默认是一对)。
    found = [Use(name, "app", fragment("capUse_settingsDefault"))] \
        if settings and get(name) is not None and _registry[name].defaultable else []
    found += [one for one in _uses if one.capability == name]
    for finder in _use_finders:
        found += [one for one in finder() if one.capability == name]
    return found


def used_by(name: str, *, settings: bool = True) -> list[dict[str, str]]:
    """`uses_of` 译成给人看的一行一条(设置页、插件页照着列)。"""
    return [{"kind": use.kind, "label": tr(use.label["__key"], **use.label.get("params", {}))}
            for use in uses_of(name, settings=settings)]


def vocabulary() -> list[dict[str, Any]]:
    """`provides` 里能写的每一项:名字、界面上叫什么、装上之后用在哪。插件市场、插件页照它说,不各写一份。
    走挑法的在前,再是不参与挑选的(生成、工具清单),各按名字排。"""
    outside = [_registry[name] for name in sorted(_registry) if not _registry[name].pickable]
    return [{"name": one.name, "label": tr(one.label_key), "used_by": used_by(one.name)}
            for one in registered() + outside]


#: 工作流 / 画板字段里「挑一家」的通用选项来源:`options_from: "providers.<能力>"`(ADR 0032 §3)。
PROVIDERS_SOURCE = "providers."


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


def _builtins(db: Session, owner_user_id: str | None, capability: Capability) -> list[Provider]:
    return [Provider(id=one.id, name=tr(one.name_key), builtin=True,
                     missing=tuple(one.ready(db, owner_user_id) if one.ready else ()),
                     extra={"automatic": one.automatic})
            for one in capability.builtins]


def providers(db: Session, owner_user_id: str | None, capability: Capability) -> list[Provider]:
    """全部候选:内置的在前(按契约给的先后),再是插件连接。"""
    return _builtins(db, owner_user_id, capability) + plugin_providers(db, owner_user_id, capability)


def default_id(db: Session, owner_user_id: str | None, capability: Capability) -> str | None:
    """他在这项能力上定的那一家(提供方 id);没定过是 None。**不起任何探测** —— 模板前置检查按它推
    「真跑的时候 choose 会用哪一家」,不能为了列一张状态表去起子进程。"""
    from app.domain.plugins import capability_defaults

    return capability_defaults.default_of(db, owner_user_id, capability.name) if owner_user_id else None


def _automatic(capability: Capability, candidates: list[Provider]) -> Provider | None:
    """**不定默认**时会用哪一家:第一个允许自动、跑得起来的内置实现;没有的话,只有一家插件配好
    (且这项能力允许)才用它。"""
    builtin = next((one for one in candidates if one.builtin and one.extra.get("automatic") and not one.missing), None)
    if builtin:
        return builtin
    ready = [one for one in candidates if not one.builtin and not one.missing]
    return ready[0] if capability.auto_single and len(ready) == 1 else None


def choices(db: Session, owner_user_id: str, capability: Capability) -> dict[str, Any]:
    """设置页那一格要画的:候选(配没配好、缺什么)、他定的那家、不定时实际会用哪家。"""
    candidates = providers(db, owner_user_id, capability)
    chosen = default_id(db, owner_user_id, capability)
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
        #: 有没有「默认用哪家」;有的话默认那一行长什么样(配音是 `engine_voice`:引擎 + 音色两个控件)。
        "defaultable": capability.defaultable,
        "default_shape": capability.default_shape,
        "options": [{"id": one.id, "name": one.name, "builtin": one.builtin, "missing": list(one.missing)}
                    for one in candidates],
        #: 定了这一家,哪些地方跟着换(ADR 0032 §4)。
        "used_by": used_by(capability.name, settings=False),
    }


def _usable(capability: Capability, chosen: Provider, subject: dict[str, Any]) -> Provider:
    """挑中的这一家能不能用:缺东西、插件太旧都说清楚。"""
    if chosen.missing:
        raise capability.error(capability.incomplete_key, plugin=chosen.name,
                               missing=tr("punct_listSep").join(chosen.missing), **subject)
    if not chosen.builtin and not chosen.tool:
        raise capability.error(capability.outdated_key, plugin=chosen.name, **subject)
    return chosen


def choose(db: Session, owner_user_id: str | None, capability: Capability, **subject: Any) -> Provider:
    """挑出这一次用哪一家;挑不出来时抛 `capability.error`,消息说清下一步。`subject` 进文案(比如素材名)。"""
    sep = tr("punct_listSep")
    candidates = providers(db, owner_user_id, capability)
    chosen_id = default_id(db, owner_user_id, capability)
    chosen = next((one for one in candidates if one.id == chosen_id), None)
    if chosen is None:
        chosen = _automatic(capability, candidates)
    if chosen is None:
        if not candidates:
            raise capability.error(capability.none_key, **subject)
        plugins = [one for one in candidates if not one.builtin]
        ready = [one for one in plugins if not one.missing]
        if len(ready) > 1:
            raise capability.error(capability.ambiguous_key, names=sep.join(one.name for one in ready), **subject)
        #: 一家都跑不起来(或者只有一家插件,但这项能力不许自动用它):说第一家缺什么,下一步最清楚。
        first = next((one for one in candidates if one.missing), candidates[0])
        if not first.missing and not first.builtin:
            raise capability.error(capability.none_key, **subject)
        chosen = first
    return _usable(capability, chosen, subject)


def canonical_id(capability: Capability, provider_id: str | None) -> str:
    """把一个 id 归一到能力表的规范 id:契约里登记了别名的按别名解析,**只在这里解析一次**。

    没登记过的**原样返回**(插件连接 id 大小写敏感,不能顺手归一)。空串仍是空串 —— 调用方拿它表示
    「按默认」。
    """
    wanted = (provider_id or "").strip()
    if not wanted:
        return ""
    folded = wanted.lower()
    return next((new for old, new in capability.aliases if folded == old.lower()), wanted)


def _unknown_named(capability: Capability, given: str, candidates: list[Provider], subject: dict[str, Any]) -> NoReturn:
    """点名的那一家不在候选里:说清**哪一家**、这台机器上**现在能用哪几家**、**下一步**去哪换。

    一家能用的都没有时换一句:那句的下一步是「去接一个」,不是「换成其中一家」。
    """
    usable = [one.name for one in candidates if not one.missing]
    #: 没登记 `unknown_none_key` 的能力保持原来的那句话和 key(`asrErr_unsupportedEngine` 之类已经
    #: 被别的测试钉着);`available` 照给:不用它的模板会忽略多余的参数。
    key = capability.unknown_none_key if not usable and capability.unknown_none_key else capability.unknown_key
    raise capability.error(key, name=given, available=tr("punct_listSep").join(usable), **subject)


def pick(db: Session, owner_user_id: str | None, capability: Capability, provider_id: str | None, **subject: Any) -> Provider:
    """点名用哪一家(界面上「用 ×× 重新解析」、节点里选的引擎);没点名就按默认挑(choose)。
    点名的得是内置的,或他自己的、配好了的插件连接。旧 id 按契约的 `aliases` 归一(见 `canonical_id`)。"""
    wanted = canonical_id(capability, provider_id)
    if not wanted:
        return choose(db, owner_user_id, capability, **subject)
    candidates = providers(db, owner_user_id, capability)
    found = next((one for one in candidates if one.id == wanted), None)
    if found is None:
        _unknown_named(capability, wanted, candidates, subject)
    return _usable(capability, found, subject)


def resolve_named(db: Session, owner_user_id: str | None, capability: Capability, name_or_id: str) -> Provider | None:
    """智能体说的是提供方的名字(「MinerU 文档解析」「RNNoise」)或 id:认出来就是它(不管配没配好,由 pick 说),
    认不出回 None。空串 = 按默认。旧 id 同样先归一(见 `canonical_id`)。"""
    wanted = canonical_id(capability, name_or_id).lower()
    if not wanted:
        return None
    candidates = providers(db, owner_user_id, capability)
    return next((one for one in candidates if wanted in (one.id.lower(), one.name.lower())), None) or \
        next((one for one in candidates if wanted in one.name.lower()), None)


def set_default(db: Session, owner_user_id: str, capability: Capability, provider_id: str | None) -> None:
    """定下(或清掉)这个人在这项能力上的默认。选「不定时本来就会用的」内置实现 = 清掉;别的内置实现(降噪的
    RNNoise)是一次真的选择,照样存。"""
    from app.domain.plugins import capability_defaults

    if not capability.defaultable:
        raise capability.error("capErr_notDefaultable", name=tr(capability.label_key))
    #: 旧 id 也在这里认回来(和 pick 同一份解析,见 canonical_id);空 = 清掉。
    provider_id = canonical_id(capability, provider_id) or None
    #: 选的是「不定时本来就会用的那一家」= 清掉:以后内置实现换了先后,跟着走。
    automatic = _automatic(capability, _builtins(db, owner_user_id, capability))
    if provider_id is None or (automatic is not None and provider_id == automatic.id):
        capability_defaults.set_default(db, owner_user_id, capability.name, None)
        return
    capability_defaults.set_default(db, owner_user_id, capability.name, provider_id,
                                    builtin_ids=frozenset(one.id for one in capability.builtins))


__all__ = [
    "BUILTIN_PREFIX",
    "Builtin",
    "Capability",
    "CapabilityUnavailable",
    "Provider",
    "canonical_id",
    "choices",
    "instance_hooks",
    "resolve_named",
    "PROVIDERS_SOURCE",
    "Use",
    "register_use",
    "register_use_finder",
    "used_by",
    "uses_of",
    "vocabulary",
    "choose",
    "default_id",
    "get",
    "pick",
    "plugin_providers",
    "providers",
    "register",
    "register_finish",
    "registered",
    "set_default",
]
