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
    REFERENCE_VIDEO,
    GenerationRequest,
    SourceAsset,
    source_value,
    source_values,
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


# ---------------------------------------------------------------------------
# 交付形式:内联字节 vs 一条链接 —— 哪一种可用是供应商按角色定的
# ---------------------------------------------------------------------------

#: 方舟 Seedance 2.0 在内置目录里的真实 model_id。写成常量而不是字面量:抄错一个日期后缀,
#: `capabilities_for` 会静默回落到一份只有 modes/parameter_keys 的空描述符 —— 于是校验什么
#: 都不拦,测试绿着,而被测的那条规矩根本没被走到。第一版就是这么写错的。
SEEDANCE_2 = "doubao-seedance-2-0-260128"


def test_有直链的素材_照常放行(tmp_path: Path) -> None:
    """**参考视频是支持的。** 不成立的只是"把本地文件编码进请求体"这一种交付方式。

    官方文档:`image_url` 收公网链接 / Base64 data URL / `asset://<ID>`;`video_url`
    只收前者和后者,**明确不收 Base64**。素材是从一条公网直链导入的,就有链接可用 ——
    这时功能完全可用,不该被拦。
    """
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    request = GenerationRequest(
        kind="video", model=SEEDANCE_2, prompt="照这个风格",
        sources=(SourceAsset(role=REFERENCE_VIDEO, path=clip,
                             public_url="https://cdn.example.com/clip.mp4"),),
    )
    assert source_values(request, REFERENCE_VIDEO) == ("https://cdn.example.com/clip.mp4",)


def test_没有直链就内联_而那是别家收的形式(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    request = GenerationRequest(
        kind="video", model="wan", prompt="照这个风格",
        sources=(SourceAsset(role=REFERENCE_VIDEO, path=clip),),
    )
    assert source_values(request, REFERENCE_VIDEO)[0].startswith("data:")


def test_图片仍然内联_哪怕有直链(tmp_path: Path) -> None:
    """base64 是各家都收的形式,而且不依赖对方能不能访问到我们给的地址。改它没有收益,只有风险。"""
    still = tmp_path / "a.png"
    still.write_bytes(b"\x89PNG\r\n\x1a\n")
    request = GenerationRequest(
        kind="video", model=SEEDANCE_2, prompt="x",
        sources=(SourceAsset(role=REFERENCE_IMAGE, path=still,
                             public_url="https://cdn.example.com/a.png"),),
    )
    assert source_values(request, REFERENCE_IMAGE)[0].startswith("data:")


def test_页面地址不算直链() -> None:
    """从 yt-dlp 导入的素材,`source_url` 记的是**播放页**地址。把它当直链发过去,
    对面下载到的是一坨 HTML —— 那种失败比一个明确的拦截更难查。"""
    from app.ai.providers.contracts.generation import direct_media_url

    assert direct_media_url("https://cdn.example.com/clip.mp4") == "https://cdn.example.com/clip.mp4"
    assert direct_media_url("https://cdn.example.com/clip.MP4?t=3") is not None
    assert direct_media_url("https://www.bilibili.com/video/BV1xx") is None
    assert direct_media_url("file:///Users/me/clip.mp4") is None
    assert direct_media_url("") is None
    assert direct_media_url(None) is None


def test_方舟的描述符声明了这条交付限制() -> None:
    """声明写在描述符上而不是适配器里的 if —— 否则 fast/mini 这些 `**` 继承来的变体会漏掉。"""
    from app.domain.generation.catalog import (
        SEEDANCE_2_SMALL_VIDEO_CAPABILITIES,
        SEEDANCE_2_VIDEO_CAPABILITIES,
    )

    for caps in (SEEDANCE_2_VIDEO_CAPABILITIES, SEEDANCE_2_SMALL_VIDEO_CAPABILITIES):
        assert caps.get("url_only_roles") == [REFERENCE_VIDEO]


def test_提交前就说清楚_而且只拦真没有链接的那一份() -> None:
    """走**完整提交链**(界面/智能体/工作流/定时任务四条路都汇到 `create_generation_job`)。

    用户挂一段**本地**参考视频跑 Seedance,最早拿到的是花钱之后才来的一句英文 400:

        The parameter `content` specified in the request is not valid:
        reference_video must be provided as a web url

    而挂一段**从链接导入**的素材,功能本来就是好的 —— 这一条钉住两者不能被一视同仁。

    **而且拦是最后一招**:装了对象存储插件的话,提交时会自动把本地素材传上去换一条直链
    (见 domain/generation/public_links)。这条测试跑在没装插件的环境里,所以走的是拦那一支 ——
    它断言的是**那句话说清了下一步**("装一个对象存储插件"),而不是"请自行上传"。
    """
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.db.models import Asset, ProviderProfile, User
    from app.domain import provider_models
    from app.domain.generation.operations import GenerationDomainError, create_generation_job
    from tests.util import fresh_client

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    pid = client.post(
        "/api/settings/providers",
        json={"vendor": "bytedance", "name": "方舟", "api_key": "sk-test",
              "base_url": "https://ark.cn-beijing.volces.com/api/v3"},
    ).json()["id"]
    client.put(f"/api/settings/providers/{pid}/credential", json={"api_key": "sk-test"})
    with SessionLocal() as db:
        provider_models.upsert(db, db.get(ProviderProfile, pid), SEEDANCE_2,
                               source="manual", capability_ids=["video"])
        db.commit()
        user_id = db.scalars(select(User).where(User.username == "tester")).first().id

    def _clip(name: str, source_url: str | None) -> str:
        with SessionLocal() as db:
            asset = Asset(
                workspace_id=ws, kind="video", name=name, original_filename=f"{name}.mp4",
                file_key=f"{ws}/{name}.mp4", source="imported",
                media_info={"source_url": source_url} if source_url else {},
            )
            db.add(asset)
            db.commit()
            return asset.id

    local, linked = _clip("本地片段", None), _clip("从链接导入的", "https://cdn.example.com/clip.mp4")

    def _submit(asset_id: str):
        with SessionLocal() as db:
            return create_generation_job(
                db, workspace_id=ws, session_id=None, project_id=None, created_by=user_id,
                provider="bytedance", provider_profile_id=pid, model=SEEDANCE_2, kind="video",
                prompt="照这个风格来", negative_prompt="",
                parameters={"duration_seconds": 5, "resolution": "720p"},
                source_assets=[{"role": REFERENCE_VIDEO, "asset_id": asset_id}],
            )

    # **没装对象存储插件时**才拦,而且要说清下一步是"装一个",不是"自己想办法"。
    with pytest.raises(GenerationDomainError, match="对象存储插件"):
        _submit(local)
    # 从链接导入的那一份:**拦不该落在它头上**。参考视频本身是支持的。
    _submit(linked)
