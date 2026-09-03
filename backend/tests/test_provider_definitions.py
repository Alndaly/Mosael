"""Provider 定义是强类型契约，不是供业务层随意解释的字典。"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.domain.provider_presets import ProviderDefinition, provider_definition, provider_definitions
from app.domain import provider_presets


def test_definition_exposes_typed_immutable_provider_metadata() -> None:
    alibaba = provider_definition("alibaba")

    assert alibaba is not None
    assert alibaba.vendor == "alibaba"
    assert alibaba.capability_ids == ("chat", "image", "video", "tts")
    assert alibaba.auth_types == ("api_key",)
    assert alibaba.field("api_key") is not None
    assert alibaba.field("api_key").secret is True

    with pytest.raises(FrozenInstanceError):
        alibaba.label = "changed"  # type: ignore[misc]


def test_unknown_provider_is_explicitly_absent() -> None:
    assert provider_definition("does-not-exist") is None


def test_untyped_preset_table_is_not_a_public_interface() -> None:
    assert not hasattr(provider_presets, "VENDOR_PRESETS")


def test_registry_order_is_stable_and_vendor_ids_are_unique() -> None:
    definitions = provider_definitions()

    assert definitions
    assert len({definition.vendor for definition in definitions}) == len(definitions)
    assert definitions[0].vendor == "alibaba"


@pytest.mark.parametrize(
    ("mapping", "message"),
    [
        ({"label": "Broken", "capability_ids": ["telepathy"]}, "未知能力"),
        ({"label": "Broken", "auth": ["password"]}, "未知鉴权方式"),
        (
            {
                "label": "Broken",
                "fields": [
                    {"key": "token", "label": "Token"},
                    {"key": "token", "label": "Token again"},
                ],
            },
            "重复字段",
        ),
    ],
)
def test_invalid_provider_definition_fails_at_composition_time(mapping: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ProviderDefinition.from_mapping("broken", mapping)
