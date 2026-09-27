"""资产分享包 `mosael.asset/1`:形状、禁用键、参考图与封面、变体、真人的授权声明。"""

from __future__ import annotations

import copy

import pytest

from mosael_formats import asset_bundle, i18n
from mosael_formats.asset_bundle import AssetBundleError, check_consent, validate_bundle

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def bundle(**overrides) -> dict:
    base = {
        "schema": asset_bundle.SCHEMA,
        "kind": "character",
        "name": "张三",
        "description": "主角",
        "prompt": "黑色短发,红围巾",
        "tags": ["主角"],
        "attributes": {"real_person": False, "blockout_color": "#aabbcc"},
        "references": [
            {"sha256": SHA_A, "content_type": "image/png", "width": 1024, "height": 1024, "role": "front"},
            {"sha256": SHA_B, "content_type": "image/jpeg", "width": 800, "height": 1200, "role": "side"},
        ],
        "cover_sha256": SHA_A,
        "variants": [
            {
                "name": "冬装",
                "description": "",
                "prompt": "厚羽绒服",
                "tags": [],
                "attributes": {"blockout_color": "#112233"},
                "references": [{"sha256": SHA_C, "content_type": "image/webp", "role": "full_body"}],
                "cover_sha256": SHA_C,
            }
        ],
    }
    base.update(overrides)
    return base


def test_合格的分享包收集到全部哈希() -> None:
    summary = validate_bundle(bundle())
    assert summary.kind == "character" and summary.name == "张三"
    assert summary.hashes == {SHA_A, SHA_B, SHA_C}
    assert summary.reference_count == 3 and summary.variant_count == 1
    assert summary.cover_sha256 == SHA_A and summary.real_person is False


def test_场景和道具只有各自能公开的字段() -> None:
    location = bundle(kind="location", attributes={"time_of_day": "黄昏,小雨"}, variants=[])
    assert validate_bundle(location).kind == "location"
    with pytest.raises(AssetBundleError):
        validate_bundle(bundle(kind="location", attributes={"blockout_color": "#aabbcc"}, variants=[]))
    with pytest.raises(AssetBundleError):
        validate_bundle(bundle(kind="prop", attributes={"time_of_day": "夜"}, variants=[]))
    assert validate_bundle(bundle(kind="prop", attributes={}, variants=[])).real_person is False


@pytest.mark.parametrize(
    "key",
    ["voice_id", "consent", "declared_by", "scene_id", "model_asset_id", "id", "asset_id", "workspace_id"],
)
def test_不该出门的键在任何一层都拒_并点出是哪一个(key: str) -> None:
    top = bundle()
    top[key] = "x"
    with pytest.raises(AssetBundleError) as caught:
        validate_bundle(top)
    assert caught.value.key == "assetBundleErr_forbiddenKey" and caught.value.params["field"] == key

    nested = bundle()
    nested["attributes"][key] = "x"
    with pytest.raises(AssetBundleError) as caught:
        validate_bundle(nested)
    assert caught.value.key == "assetBundleErr_forbiddenKey"

    deep = bundle()
    deep["variants"][0]["references"][0][key] = "x"
    with pytest.raises(AssetBundleError) as caught:
        validate_bundle(deep)
    assert caught.value.key == "assetBundleErr_forbiddenKey" and "variants[0].references[0]" in caught.value.params["where"]


def _broken(path: tuple, value) -> dict:
    out = copy.deepcopy(bundle())
    target = out
    for part in path[:-1]:
        target = target[part]
    if value is KeyError:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return out


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schema",), "mosael.asset/2"),
        (("kind",), "style"),
        (("name",), "   "),
        (("name",), "x" * 161),
        (("extra",), 1),
        (("tags",), ["x" * 41]),
        (("attributes", "real_person"), "yes"),
        (("attributes", "blockout_color"), "red"),
        (("references",), []),
        (("references", 0, "sha256"), "NOT-A-HASH"),
        (("references", 0, "content_type"), "video/mp4"),
        (("references", 0, "content_type"), "image/svg+xml"),
        (("references", 0, "role"), "selfie"),
        (("references", 0, "width"), -1),
        (("references", 0, "width"), True),
        (("references", 0, "role"), KeyError),
        (("references", 1, "sha256"), SHA_A),
        (("cover_sha256",), SHA_C),
        (("cover_sha256",), None),
        (("variants", 0, "kind"), "character"),
        (("variants", 0, "variants"), []),
        (("variants", 0, "attributes"), {"real_person": True}),
        (("variants", 0, "cover_sha256"), SHA_A),
    ],
)
def test_不合格的分享包(path: tuple, value) -> None:
    with pytest.raises(AssetBundleError):
        validate_bundle(_broken(path, value))


def test_变体可以没有参考图_没有封面() -> None:
    summary = validate_bundle(bundle(variants=[{"name": "少年时期", "references": [], "cover_sha256": None}]))
    assert summary.variant_count == 1 and summary.reference_count == 2


def test_真人要有本人或已获同意的声明() -> None:
    real = validate_bundle(bundle(attributes={"real_person": True}))
    assert check_consent(real, "self") == "self"
    assert check_consent(real, "authorized") == "authorized"
    for bad in (None, "", "fictional", "pending_local_confirmation"):
        with pytest.raises(AssetBundleError) as caught:
            check_consent(real, bad)
        assert caught.value.key == "assetBundleErr_consentRequired"

    fictional = validate_bundle(bundle())
    assert check_consent(fictional, None) == "" and check_consent(fictional, "") == ""
    with pytest.raises(AssetBundleError) as caught:
        check_consent(fictional, "self")
    assert caught.value.key == "assetBundleErr_consentNotApplicable"


def test_报错按此刻的语言说() -> None:
    top = bundle()
    top["voice_id"] = "v1"
    with pytest.raises(AssetBundleError) as caught:
        validate_bundle(top)
    token = i18n.CURRENT_LOCALE.set("en")
    try:
        assert "can't carry “voice_id”" in str(caught.value)
    finally:
        i18n.CURRENT_LOCALE.reset(token)
    assert "不能带「voice_id」" in str(caught.value)
