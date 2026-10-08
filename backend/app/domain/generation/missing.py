"""记着的生成模型现在不在生成选项里:它叫什么、为什么不在、怎么修(ADR 0045 修订之一)。

会话、画板格子、工作流的生成节点存着一对「连接 + 模型 id」。那一对后来可能用不了了 —— 连接删了或停了、模型行停了,
ComfyUI 上那张工作流改了名、挪了文件夹、删了表单,或者表单还是上一版的格式。**界面照常显示记着的那个**(人话的名字,
两层)、说原因、不让跑,不拿默认模型顶上;生成的漏斗在模型解析不出来时也照这里说的那句报。

能说的由近到远:连接没了 / 不是他的 / 停用了;模型行在,只是停用了或不再被认成这种生成;插件连接问插件
(`op: explain`,插件能分清「表单是旧格式、要升级」「表单删了」「工作流不在了」);都说不上来就说「这条连接上已经没有它了」。

给人看的字**留着没翻**(文案片段 / 插件按语言分的话):漏斗把它们原样交给报错(存进运行记录,按读的人的语言翻),
接口按这次请求的语言读成字(`read`)。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import authored_text, fragment, read_param
from app.db.models import PluginInstance, ProviderModel, ProviderProfile
from app.domain.generation.catalog import GENERATION_KINDS
from app.domain.plugins import generation as plugin_generation
from app.domain.plugins.groups import readable_group

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MissingModel:
    """一个用不了的记着的模型。`label`、`reason` 留着没翻(见模块说明);`group` 是插件说的「来自哪样东西」(和生成选项上
    那一格同一个形状),没有是 None。`upgrade`:修法是到插件自己的库里升级(ComfyUI:工作流库的「查看并升级」)。"""

    provider_profile_id: str
    model: str
    label: Any
    profile_name: str
    group: dict[str, Any] | None
    reason: Any
    upgrade: bool = False
    plugin_instance_id: str = ""

    def read(self, locale: str) -> dict[str, Any]:
        """按这个语言读成给界面的样子(和生成选项同几格名字:`model_label`、`profile_name`、`group`)。"""
        return {
            "provider_profile_id": self.provider_profile_id,
            "model": self.model,
            "model_label": str(read_param(self.label, locale)),
            "profile_name": self.profile_name,
            "group": readable_group(self.group, locale),
            "reason": str(read_param(self.reason, locale)),
            "upgrade": self.upgrade,
            "plugin_instance_id": self.plugin_instance_id,
        }


def explain_missing(db: Session, *, user_id: str | None, provider_profile_id: str, model: str, kind: str) -> MissingModel:
    """`(provider_profile_id, model)` 为什么不在 `kind` 这种生成的选项里。调用方已经知道它不在(选项里没有、解析不出来)。"""
    profile = db.get(ProviderProfile, provider_profile_id) if provider_profile_id else None
    if profile is None or (user_id is not None and profile.owner_user_id != user_id):
        return MissingModel(provider_profile_id, model, fragment("genMissing_someModel"), "", None,
                            fragment("genMissing_connectionGone"))
    instance_id = profile.plugin_instance_id or ""
    row = db.scalar(select(ProviderModel).where(ProviderModel.provider_profile_id == profile.id,
                                                ProviderModel.model_id == model))
    label: Any = (row.display_name or row.model_id) if row is not None else (fragment("genMissing_someModel") if instance_id
                                                                              else model)
    group = row.declared_group if row is not None else None

    def missing(reason: Any, *, upgrade: bool = False, named: Any = None, origin: Any = None) -> MissingModel:
        return MissingModel(profile.id, model, named or label, profile.name, origin or group, reason, upgrade, instance_id)

    if not profile.enabled:
        return missing(fragment("genMissing_connectionOff", name=profile.name))
    if row is not None and not row.enabled:
        return missing(fragment("genMissing_modelOff", model=row.display_name or row.model_id, name=profile.name))
    #: 行在、连接和行都开着,却不在这种生成的选项里:就是没被认成这种生成(选项正是按能力取的,见 resolution.generation_options)。
    #: 不在这里重算一遍能力 —— 那要引供应商模型那一层,它又回头引生成域(import 分层的环,见 test_import_layering)。
    if row is not None and kind in GENERATION_KINDS:
        return missing(fragment(f"genErr_modelLacksKind_{kind}", model=row.display_name or row.model_id))
    instance = db.get(PluginInstance, instance_id) if instance_id else None
    if row is None and instance is not None:
        explained = _ask_plugin(db, instance, model)
        if explained is not None:
            return missing(authored_text(explained.reason), upgrade=explained.upgrade,
                           named=authored_text(explained.label) if isinstance(explained.label, dict) else explained.label,
                           origin=explained.group)
    return missing(fragment("genMissing_modelGone", name=profile.name))


def _ask_plugin(db: Session, instance: PluginInstance, model: str) -> plugin_generation.Explained | None:
    """问插件这个 id 为什么不在(ComfyUI 要列一次目录、读那张图)。插件不支持这一问、这会儿问不到,都是 None —— 退回
    宿主自己能说的那句,不让一个解释拖垮整件事。"""
    try:
        found = plugin_generation.explain(db, instance, [model])
    except Exception:  # noqa: BLE001 — 解释不出来不是错,照宿主能说的那句说
        logger.info("插件实例 %s 解释不了模型 %s 为什么不在", instance.id, model, exc_info=True)
        return None
    return next((one for one in found if one.id == model), None)


__all__ = ["MissingModel", "explain_missing"]
