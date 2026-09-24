"""生成、发布、浏览器、素材这几块的报错按请求方的语言说。

此前它们是写死的中文句子:英文界面里提交一个不合规的生成、发一条标题超长的视频、在智能体里
操作一个已关掉的浏览器会话,弹出来的都是中文。现在领域里只说「是哪一种」和参数(文案 key),
变成文字时才按读的人的语言翻(见 core/i18n.LocalizedError)。

几条要点各钉一条:
  ・生成校验里**拼进去的那半句**(素材角色的名字、清单的连接号、「或」)也跟着语言走,
    否则英文句子里还夹着「参考图、参考视频」;
  ・跨层转包(解析错误 → 生成错误、上传失败 → 生成错误)传的是 key + 参数,不是冻住的那句话;
  ・原来的 except 兼容保留(ValueError / RuntimeError / GenerationAdapterError / PluginDomainError);
  ・后台任务的失败原因经 `jobs.blame` 记下 key,读的时候再翻。
"""

from __future__ import annotations

import re
from unittest.mock import patch

import pytest

from app.core.i18n import MESSAGES, set_current_locale, t
from tests.util import fresh_client

CJK = re.compile(r"[一-鿿]")


@pytest.fixture
def english():
    set_current_locale("en")
    try:
        yield
    finally:
        set_current_locale("zh")


def test_生成校验_拼进去的角色名和连接号也是英文(english) -> None:
    from app.domain.generation.operations import GenerationDomainError, validate_against_capabilities

    with pytest.raises(GenerationDomainError) as info:
        validate_against_capabilities(
            "evolink", "seedance-2.0-reference-to-video", "video", {},
            [{"asset_id": "a", "role": "reference_audio"}],
        )
    assert info.value.key == "genErr_companionRequired"
    assert str(info.value) == (
        "For evolink/seedance-2.0-reference-to-video, the reference audio can't be used alone; "
        "add a reference image or reference video as well."
    )


def test_生成校验_中文照旧() -> None:
    """缺省语言下原句不变 —— 既有的 `match="参考音频.*参考图.*参考视频"` 之类断言靠的就是它。"""
    from app.domain.generation.operations import GenerationDomainError, validate_against_capabilities

    with pytest.raises(GenerationDomainError) as info:
        validate_against_capabilities(
            "evolink", "seedance-2.0-reference-to-video", "video", {},
            [{"asset_id": "a", "role": "reference_audio"}],
        )
    assert str(info.value) == (
        "evolink/seedance-2.0-reference-to-video 的参考音频不能单独使用,要搭配参考图或参考视频一起给"
    )


def test_不认的参数_可用清单按英文的逗号连起来(english) -> None:
    from app.domain.generation.operations import GenerationDomainError, validate_against_capabilities

    with pytest.raises(GenerationDomainError) as info:
        validate_against_capabilities("alibaba", "qwen-image", "image", {"nope": 1}, [])
    text = str(info.value)
    assert text.startswith("alibaba/qwen-image doesn't support these parameters: nope. Supported: ")
    assert "、" not in text and not CJK.search(text)


def test_角色名的文案和目录里的中文名是同一份() -> None:
    """名字的产地是 catalog.SOURCE_ROLE_LABELS;文案 `genRole_*` 的 zh 必须和它一字不差,
    每个角色都得有 —— 漏一个,报错里就会冒出 `reference_audio` 这种内部名字。"""
    from app.domain.generation.catalog import SOURCE_ROLE_LABELS

    for role, label in SOURCE_ROLE_LABELS.items():
        key = f"genRole_{role}"
        assert key in MESSAGES, key
        assert MESSAGES[key]["zh"] == label, role


def test_解析错误转包成生成错误时带着_key_走() -> None:
    """`GenerationDomainError(str(exc))` 会把那句话冻成转包那一刻的语言。"""
    from app.domain.generation.operations import GenerationDomainError
    from app.domain.generation.resolution import GenerationResolutionError

    inner = GenerationResolutionError("genErr_unknownKind", kind="audio")
    outer = GenerationDomainError(inner.key, **inner.params)
    assert isinstance(inner, ValueError) and isinstance(outer, ValueError)
    assert t(outer.key, "en", **outer.params) == "Unknown generation type: audio"


def test_执行时的素材错误仍是适配器错误_失败原因记下_key() -> None:
    """runner 只 except GenerationAdapterError —— 新的错误类得还是它,否则会走「意外异常」那条路。"""
    from app.ai.providers import GenerationAdapterError
    from app.domain.generation.runner import GenerationRunError, _role_label
    from app.domain.jobs import blame

    exc = GenerationRunError("genErr_sourceFileMissing", label=_role_label("last_frame"))
    assert isinstance(exc, GenerationAdapterError)
    fields = blame(exc)
    assert fields["error_key"] == "genErr_sourceFileMissing"
    assert fields["error"] == "尾帧素材文件不存在"
    assert t(fields["error_key"], "en", label="last frame") == "The last frame asset's file is missing."


def test_自定义参数组的报错是英文(english) -> None:
    from app.domain.generation.custom_profiles import CapabilityProfileError, validate_capabilities

    with pytest.raises(CapabilityProfileError) as info:
        validate_capabilities({"sizes": "1024x1024"}, "image")
    assert isinstance(info.value, ValueError)
    assert str(info.value) == "sizes must be a list of non-empty strings."


def test_本地素材没有可用的上传插件_英文说清下一步() -> None:
    from app.domain.generation.public_links import NoUploader

    exc = NoUploader("genErr_noUploader", asset="clip.mp4")
    assert isinstance(exc, RuntimeError)
    text = t(exc.key, "en", **exc.params)
    assert text.startswith("“clip.mp4” is a local asset, but this model only accepts a public link here.")
    assert not CJK.search(text)


def test_发布选项的报错是英文(english) -> None:
    from app.domain.publish import PublishDomainError, normalize_options

    with pytest.raises(PublishDomainError) as info:
        normalize_options("youtube", {"nope": True})
    assert str(info.value) == (
        "youtube doesn't support the publish option 'nope' (supported: visibility, made_for_kids)"
    )


def test_浏览器回报被拒_仍是_ValueError_且按语言翻(english) -> None:
    from app.core.db import SessionLocal
    from app.domain.browser import BrowserDomainError, report_action

    fresh_client()
    with SessionLocal() as db, pytest.raises(ValueError) as info:
        report_action(db, "nope", status="bogus")
    assert isinstance(info.value, BrowserDomainError)
    assert str(info.value) == "Invalid action status."


def test_浏览器动作的后端原因存_key_执行器原话放进句子里() -> None:
    """租约到期、重启这些是后端自己记的原因,存 key 才能按读的人的语言翻;执行器给的是它自己的话。"""
    assert t("browserErr_executorLost", "en") == "Lost contact with the executor (its lease expired)."
    assert (
        t("browserErr_actionFailedDetail", "en", detail="element not found")
        == "The browser action failed: element not found"
    )


def test_视频转_GIF_接口按请求语言回报错() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "GIF"}).json()["id"]
    image = client.post(
        "/api/assets/import",
        data={"workspace_id": ws},
        files={"file": ("still.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    ).json()
    with patch("app.domain.jobs.threading.Thread"):
        english = client.post(
            f"/api/assets/{image['id']}/convert-gif", json={}, headers={"Accept-Language": "en"}
        )
        chinese = client.post(f"/api/assets/{image['id']}/convert-gif", json={})
    assert english.status_code == 422
    assert english.json()["detail"] == "Only video assets can be converted to GIF."
    assert chinese.json()["detail"] == "只有视频素材可以转换为 GIF"


def test_从链接导入_一次太多条_英文(english) -> None:
    from app.domain.assets.from_url import MAX_ITEMS, UrlImportError, start_url_import

    items = [{"url": f"https://e.test/{n}"} for n in range(MAX_ITEMS + 1)]
    with pytest.raises(UrlImportError) as info:
        start_url_import(None, workspace_id="w", project_id=None, items=items, kind="video", created_by=None)
    assert str(info.value) == f"You can download at most {MAX_ITEMS} items at a time. Split them into several batches."


def test_插件取素材被拒_仍是插件域错误() -> None:
    from app.domain.assets.plugin_bridge import AssetBridgeError
    from app.domain.plugins.errors import PluginDomainError

    exc = AssetBridgeError("assetErr_noFileYet", name="cat.png")
    assert isinstance(exc, PluginDomainError)
    assert t(exc.key, "en", **exc.params) == "Asset cat.png has no file yet (it may still be generating)."
