"""工作流 / 画板节点用到了哪些宿主能力(ADR 0032 §4):字段写着 `options_from: "providers.<能力>"` 的就是。

**不登记,现扫** —— 新节点只要照这个写法声明「挑一家」的字段,插件页和设置页的「用在哪」就自动出现它。
"""

from __future__ import annotations

from app.core.i18n import fragment
from app.domain.capabilities import PROVIDERS_SOURCE, Use


def capability_uses() -> list[Use]:
    from app.domain.workflows import NODE_TYPES, config_label

    found: list[Use] = []
    for spec in NODE_TYPES.values():
        for key, field in (spec.get("config") or {}).items():
            source = str(field.get("options_from") or "") if isinstance(field, dict) else ""
            if source.startswith(PROVIDERS_SOURCE):
                found.append(Use(source.removeprefix(PROVIDERS_SOURCE), "workflow",
                                 fragment("capUse_workflowField", node=fragment(str(spec["label"])),
                                          field=fragment(config_label(key, field)))))
    return found


__all__ = ["capability_uses"]
