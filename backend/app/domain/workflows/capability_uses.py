"""工作流 / 画板节点用到了哪些宿主能力(ADR 0032 §4):字段写着 `options_from: "providers.<能力>"` 的就是。

**不登记,现扫** —— 新节点只要照这个写法声明「挑一家」的字段,插件页和设置页的「用在哪」就自动出现它。
"""

from __future__ import annotations

from app.core.i18n import fragment
from app.domain.capabilities import PROVIDERS_SOURCE, Use
from app.domain.plugins.manifest import SPEECH

#: 有自己选项来源、但同样是在点名某项能力的字段。配音的引擎格不走通用的 `providers.speech`:克隆音色那一项
#: 总要在(没装好时它的音色清单是空的,选择本身仍然成立)、播客不列 —— 见 field_options._speech_engines。
_SOURCE_CAPABILITIES = {"speech_engines": SPEECH}


def capability_uses() -> list[Use]:
    from app.domain.workflows import NODE_TYPES, config_label

    found: list[Use] = []
    for spec in NODE_TYPES.values():
        for key, field in (spec.get("config") or {}).items():
            source = str(field.get("options_from") or "") if isinstance(field, dict) else ""
            capability = source.removeprefix(PROVIDERS_SOURCE) if source.startswith(PROVIDERS_SOURCE) \
                else _SOURCE_CAPABILITIES.get(source)
            if capability:
                found.append(Use(capability, "workflow",
                                 fragment("capUse_workflowField", node=fragment(str(spec["label"])),
                                          field=fragment(config_label(key, field)))))
    return found


__all__ = ["capability_uses"]
