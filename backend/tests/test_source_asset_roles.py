"""输入素材带**角色**,不靠位置。

此前 `source_files` 是一个扁平的 Path 元组,谁是首帧靠「第 0 个」这条约定。于是尾帧、
参考图、参考视频都没地方放 —— 而各家接口本来就是带 role 的(Seedance / MiniMax 的
content 数组、可灵的 image / image_tail),是我们这一层把它抹平了。

再加一个位置约定(「第 1 个是尾帧」)的代价不是难写,是**记错了不会报错**:适配器照样发出
一个合法请求,只是把尾帧当成了首帧,生成出另一段视频。所以这里钉的是「角色真的走到了
请求体里对的位置」,而不是「传了几个文件」。
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from app.ai.providers.contracts.generation import (
    FIRST_FRAME,
    LAST_FRAME,
    REFERENCE_IMAGE,
    GenerationRequest,
    SourceAsset,
    source_value,
)


@pytest.fixture
def images(tmp_path: Path) -> dict[str, Path]:
    made = {}
    for name in ("head", "tail", "ref"):
        path = tmp_path / f"{name}.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + name.encode())
        made[name] = path
    return made


def _video_request(images: dict[str, Path], *roles: str, model: str, **parameters) -> GenerationRequest:
    by_role = {FIRST_FRAME: images["head"], LAST_FRAME: images["tail"], REFERENCE_IMAGE: images["ref"]}
    return GenerationRequest(
        kind="video",
        model=model,
        prompt="海边黄昏",
        parameters=parameters,
        sources=tuple(SourceAsset(role=role, path=by_role[role]) for role in roles),
    )


class Test按角色取素材:
    def test_取到的是那个角色的文件_不是第一个(self, images) -> None:
        request = _video_request(images, FIRST_FRAME, LAST_FRAME, model="x")
        assert request.source_for(LAST_FRAME) == images["tail"]
        assert request.source_for(FIRST_FRAME) == images["head"]

    def test_没有这个角色就是_None(self, images) -> None:
        request = _video_request(images, FIRST_FRAME, model="x")
        assert request.source_for(LAST_FRAME) is None

    def test_参考图可以给多张(self, images) -> None:
        request = GenerationRequest(
            kind="image",
            model="x",
            prompt="p",
            sources=(
                SourceAsset(role=REFERENCE_IMAGE, path=images["head"]),
                SourceAsset(role=REFERENCE_IMAGE, path=images["ref"]),
            ),
        )
        assert request.sources_for(REFERENCE_IMAGE) == (images["head"], images["ref"])

    def test_参数里的_url_优先于上传的文件(self, images) -> None:
        """界面既可以选素材库里的图,也可以粘外链。两条路进来的是同一样东西,在 base 里合流。"""
        request = _video_request(images, LAST_FRAME, model="x", last_frame_url="https://example.com/tail.png")
        assert source_value(request, LAST_FRAME) == "https://example.com/tail.png"

    def test_每个角色有自己的_url_参数名(self, images) -> None:
        """共用一个 image_url 的话,给了首帧就没法再给尾帧。"""
        request = GenerationRequest(
            kind="video",
            model="x",
            prompt="p",
            parameters={"first_frame_url": "https://e/h.png", "last_frame_url": "https://e/t.png"},
        )
        assert source_value(request, FIRST_FRAME) == "https://e/h.png"
        assert source_value(request, LAST_FRAME) == "https://e/t.png"


class TestSeedance:
    def test_首尾帧各自带着_role_进_content(self, images) -> None:
        from app.ai.providers.adapters.bytedance.ark.video import build_submit_payload

        payload = build_submit_payload(_video_request(images, FIRST_FRAME, LAST_FRAME, model="seedance-2-0-260128"))
        images_in_content = [item for item in payload["content"] if item["type"] == "image_url"]
        assert [item["role"] for item in images_in_content] == [FIRST_FRAME, LAST_FRAME]

    def test_seedance1_不认_role_只发首帧(self, images) -> None:
        """老版本的 content 没有 role 字段:多发一张图,它只会当成又一张参考,而不是尾帧。"""
        from app.ai.providers.adapters.bytedance.ark.video import build_submit_payload

        payload = build_submit_payload(_video_request(images, FIRST_FRAME, LAST_FRAME, model="seedance-1-0-lite"))
        images_in_content = [item for item in payload["content"] if item["type"] == "image_url"]
        assert len(images_in_content) == 1
        assert "role" not in images_in_content[0]


class TestKling:
    def test_尾帧走_image_tail(self, images) -> None:
        from app.ai.providers.adapters.kuaishou.kling.video import build_submit_payload

        payload = build_submit_payload(_video_request(images, FIRST_FRAME, LAST_FRAME, model="kling"))
        assert payload["image"] and payload["image_tail"]
        assert payload["image"] != payload["image_tail"], "首尾帧发成了同一张图"

    def test_只给尾帧不成立(self, images) -> None:
        """那条接口是 image2video,首帧是它的必填项 —— 光有尾帧发过去只会拿回一个 400。"""
        from app.ai.providers.adapters.kuaishou.kling.video import build_submit_payload

        payload = build_submit_payload(_video_request(images, LAST_FRAME, model="kling"))
        assert "image_tail" not in payload


class TestMiniMax:
    def test_三种角色都进_content(self, images) -> None:
        from app.ai.providers.adapters.minimax.video import build_submit_payload
        from app.ai.providers.contracts.generation import GenerationAdapterContext

        context = GenerationAdapterContext(connection_id=None, vendor_id="minimax", api_key="k")
        payload = build_submit_payload(
            _video_request(images, FIRST_FRAME, LAST_FRAME, REFERENCE_IMAGE, model="MiniMax-H3"), context
        )
        roles = [item["role"] for item in payload["content"] if item["type"] == "image_url"]
        assert roles == [FIRST_FRAME, LAST_FRAME, REFERENCE_IMAGE]

    def test_有首帧时比例恒为_adaptive(self, images) -> None:
        from app.ai.providers.adapters.minimax.video import build_submit_payload
        from app.ai.providers.contracts.generation import GenerationAdapterContext

        context = GenerationAdapterContext(connection_id=None, vendor_id="minimax", api_key="k")
        payload = build_submit_payload(
            _video_request(images, FIRST_FRAME, model="MiniMax-H3", aspect_ratio="16:9"), context
        )
        assert payload["ratio"] == "adaptive"


class Test描述符声明了这些角色:
    def test_支持尾帧的模型在目录里说得出来(self) -> None:
        """界面按描述符渲染控件,智能体按描述符知道能给什么 —— 适配器认得而目录不说,
        等于这个能力只有读代码的人知道。"""
        from app.domain.generation.catalog import BUILTIN_MODELS

        by_id = {item["id"]: item for item in BUILTIN_MODELS}
        for model_id in ("minimax:MiniMax-H3:video", "kuaishou:kling:video"):
            keys = by_id[model_id]["capabilities"]["parameter_keys"]
            assert LAST_FRAME in keys, f"{model_id} 适配器支持尾帧,目录却没声明"


def test_互斥素材给用户领域错误而不是内部_NameError() -> None:
    """首帧与参考图混用是请求错误；错误文案路径本身不能再引用已删除的说明常量。"""
    from app.domain.generation.operations import GenerationDomainError, _check_source_counts

    with pytest.raises(GenerationDomainError, match="不同的生成模式"):
        _check_source_counts(
            "bytedance",
            "seedance",
            {"exclusive_source_groups": [[FIRST_FRAME], [REFERENCE_IMAGE]]},
            Counter({FIRST_FRAME: 1, REFERENCE_IMAGE: 1}),
        )
