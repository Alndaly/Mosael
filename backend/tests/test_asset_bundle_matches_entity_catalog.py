"""资产分享包(mosael_formats.asset_bundle)的种类和角度,和桌面端资产目录是同一组、同一个顺序。

分享包的注释这么说,但两边各写一份元组 —— 桌面端加一种角度而格式包没跟上,分享时就会被自己的校验拒掉,
而且要等到有人真的分享才发现。
"""

from mosael_formats import asset_bundle

from app.domain.entities import catalog


def test_kinds_match() -> None:
    assert tuple(asset_bundle.KINDS) == tuple(catalog.KINDS)


def test_roles_match_in_order() -> None:
    assert tuple(asset_bundle.ROLES) == tuple(catalog.ROLES)
