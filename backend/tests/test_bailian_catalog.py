"""阿里云百炼的模型在生成目录与设置里:原生端点的模型要看得到,能力按模型推而不是套 vendor 全集。"""

from __future__ import annotations


def test_万相在生成目录里_视频模型不在兼容目录中() -> None:
    """必须写进内置目录:兼容模式的 /models 只列 OpenAI 兼容的模型,视频走百炼原生端点 ——
    真机实测那个接口对百炼只返回两个 wan 图像模型,一个视频模型都没有。不写的话用户在界面上
    一个也选不到。"""
    from app.domain.generation.catalog import BUILTIN_MODELS

    #: 数字人那两个(说话照片、改口型,ADR 0028)不是万相的出片模型:不按尺寸 / 清晰度出片,另有测试钉着。
    talking = {"speech-to-video", "video-lipsync"}
    videos = [m for m in BUILTIN_MODELS if m["provider"] == "alibaba" and m["kind"] == "video"
              and not talking & set(m["capabilities"].get("modes") or ())]
    assert len(videos) >= 5, "万相视频模型没进目录"
    assert all(m["model"].startswith("wan") for m in videos)
    # 两代模型两份契约:2.6 及更早按百炼收的**像素对**给尺寸(不是 480p 这种档位名),
    # 2.7 起改成按**清晰度档**出片,连 size 字段都不再收(真机核过,见能力棘轮里的 Test万相27)。
    for m in videos:
        capabilities = m["capabilities"]
        if capabilities.get("payload_shape") == "media":
            assert set(capabilities["resolutions"]) == {"720P", "1080P"}
            assert "sizes" not in capabilities
        else:
            assert all("*" in s for s in capabilities["sizes"])


# ---------------- 模型要能被看见、能力要标对 ----------------


def test_原生端点的模型必须能在设置里看到() -> None:
    """真机症状:生成页的模型下拉里,百炼那一家整个是空的。

    链条是这样的 —— 生成页列的是「档案 × 已配置模型」,而要配模型得先在设置里看得见;
    设置那份列表原本只合并「已配置的行 + 实时目录」,而实时目录读的是 OpenAI 兼容的
    /models,**视频走原生端点、根本不在那份清单里**(真机:那个接口对百炼只返回两个 wan
    图像模型)。于是用户看不到、加不进来,而他并不知道为什么。
    """
    from app.domain.generation import builtin_models_for

    videos = builtin_models_for("alibaba", "video")
    assert len(videos) >= 5, "内置目录里没有万相视频模型"
    assert all(m.startswith("wan") for m in videos if m != "videoretalk")
    assert {"wan2.2-s2v", "videoretalk"} <= set(videos), "数字人那两个也要在设置里看得到"


def test_能力按模型推_不套用vendor全集() -> None:
    """百炼有四种能力,回落 vendor 全集会让每个模型都声称四样都行。

    后果是具体的:从目录里加一个 qwen-tts,它会被声明成"也能做视频",随即出现在视频生成的
    下拉里 —— 选了必然失败,而用户只会以为是自己配错了。
    """
    from app.domain.providers.models import infer_capabilities

    assert infer_capabilities("alibaba", "wan2.7-i2v") == ["video"]
    assert infer_capabilities("alibaba", "wan2.2-t2v-plus") == ["video"]
    assert infer_capabilities("alibaba", "qwen-tts") == ["tts"]
    assert infer_capabilities("alibaba", "cosyvoice-v2") == ["tts"]
    assert infer_capabilities("alibaba", "qwen-image") == ["image"]
    # 图像那条不能把视频抢走:wan2.7-i2v 里没有 image,但顺序错了迟早会出这类事。
    assert infer_capabilities("alibaba", "wan2.7-image") == ["image"]


def test_推不出来的回空_由调用方回落() -> None:
    """对话模型的名字没有可靠线索,硬推只会推错。推不出来就回空,让 vendor 兜底 ——
    行为和以前一样,不是收紧。"""
    from app.domain.providers.models import infer_capabilities

    assert infer_capabilities("alibaba", "qwen-max") == []
    assert infer_capabilities("alibaba", "") == []
    # 没有线索表、也不在内置目录里的,回空。
    assert infer_capabilities("openai", "gpt-4o") == []
    # 但**内置目录是验证过的事实**,对任何 vendor 都该生效 —— 不只百炼。
    assert infer_capabilities("openai", "gpt-image-2") == ["image"]


def test_内置目录里的模型不该被标成已不存在() -> None:
    """真机截图:刚加的 wan2.7-i2v 挂着「目录中已不存在」。

    那个提示的本意是**预警** —— 曾经能用的模型从供应商目录里消失了(下架、改名),再点下去
    会失败。但判据原本只有"在不在实时目录里",而万相**从来就不在**那份清单里(它走原生端点)。
    于是每一个从内置目录加进来的模型都挂着这个警告,而它明明刚验证过能用。

    一个永远为真的警告等于没有警告 —— 更糟的是它会让用户去删一个好模型。
    """
    from app.api.routes.settings.provider_models import _is_known_model

    # 实时目录里没有,内置目录里有 → 认得
    assert _is_known_model("alibaba", "wan2.7-i2v", {}) is True
    assert _is_known_model("alibaba", "wan2.2-t2v-plus", {}) is True
    # 实时目录里有 → 认得(老路径不变)
    assert _is_known_model("alibaba", "qwen-max", {"qwen-max": {}}) is True
    # 两处都没有 → 这才是真正的"已不存在",警告要留着
    assert _is_known_model("alibaba", "wan-something-removed", {}) is False
