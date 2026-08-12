"""平台专属发布选项:声明在一处,后端校验、前端渲染、执行器消费都只认它。

最要命的一条是**默认值必须最保守**:自动发布误发公开是收不回的(别人已经看到、可以转存),
而想公开只是到平台上改一次。所以「没说」= 私享,不是「没说」= 公开。
"""

from __future__ import annotations

import pytest

from app.domain.publish import PublishDomainError, normalize_options, option_specs


def test_defaults_are_the_most_private_choice() -> None:
    assert normalize_options("youtube", None)["visibility"] == "private"
    assert normalize_options("tiktok", None)["visibility"] == "private"


def test_missing_keys_are_filled_not_left_undefined() -> None:
    """执行器拿到的必须是**完整**字典 —— 否则它得自己猜"没有这个键"是什么意思。"""
    got = normalize_options("youtube", {"visibility": "public"})
    assert got == {"visibility": "public", "made_for_kids": False}


def test_unknown_key_is_rejected_not_silently_dropped() -> None:
    """静默丢掉的后果:用户以为自己设了公开,发出来却是私享,而界面上什么都没说。"""
    with pytest.raises(PublishDomainError, match="不支持发布选项"):
        normalize_options("youtube", {"nope": True})


def test_enum_outside_choices_is_rejected() -> None:
    with pytest.raises(PublishDomainError, match="只能是"):
        normalize_options("tiktok", {"visibility": "secret"})


def test_bool_option_rejects_non_bool() -> None:
    with pytest.raises(PublishDomainError, match="true/false"):
        normalize_options("youtube", {"made_for_kids": "yes"})


def test_platform_without_options_takes_none() -> None:
    """B 站投稿页上**实测没有可见性控件**(只有定时发布 / 存草稿),所以这里就该是空的 ——
    声明一个平台上不存在的选项,等于让用户设一个不会生效的东西。"""
    assert option_specs("bilibili") == []
    assert normalize_options("bilibili", None) == {}
    with pytest.raises(PublishDomainError):
        normalize_options("bilibili", {"visibility": "private"})


def test_every_declared_option_is_well_formed() -> None:
    """声明本身的形状:前端照它渲染控件,少一个字段就是一个画不出来的控件。"""
    for platform, specs in ((p, option_specs(p)) for p in ("youtube", "tiktok")):
        for spec in specs:
            assert {"key", "label", "type", "default"} <= spec.keys(), (platform, spec)
            assert spec["type"] in ("enum", "bool")
            if spec["type"] == "enum":
                values = [c["value"] for c in spec["choices"]]
                assert spec["default"] in values, (platform, spec["key"])
