"""阿里云百炼 · 万相视频:提交体与轮询回包。

**纯 payload 断言,不打网络** —— 风险全在"把内部请求翻成百炼的形状"和"从回包里把地址捞出来"
这两步,这类错误在真跑一次之前完全看不出来。

顺带钉住一件容易做错的事:轮询时**不认识的状态要当作"还没结束"**,不能当失败。百炼后来加的
中间态若被判成失败,用户看到的是一次本来会成功的生成被判死。
"""

from __future__ import annotations

import pytest

from app.ai.providers.contracts.generation import FIRST_FRAME, GenerationAdapterError, GenerationRequest, SourceAsset
from app.ai.providers.adapters.alibaba.dashscope.video import build_submit_payload, extract_video_url


def _req(**kw) -> GenerationRequest:
    kw.setdefault("kind", "video")
    kw.setdefault("model", "wan2.5-t2v-preview")
    kw.setdefault("prompt", "海边黄昏")
    kw.setdefault("parameters", {})
    return GenerationRequest(**kw)


# ---------------- 万相视频:提交体 ----------------


def test_文生视频只带提示词() -> None:
    payload = build_submit_payload(_req())
    assert payload["model"] == "wan2.5-t2v-preview"
    assert payload["input"] == {"prompt": "海边黄昏"}
    assert "parameters" not in payload, "没有参数时不该塞一个空 parameters"


def test_尺寸用星号不是x() -> None:
    """百炼和 qwen-image 一样收 `宽*高`,而界面上到处写的是 `1280x720`。"""
    payload = build_submit_payload(_req(parameters={"size": "1280x720"}))
    assert payload["parameters"]["size"] == "1280*720"


def test_时长与种子透传() -> None:
    payload = build_submit_payload(_req(parameters={"duration_seconds": 5, "seed": 42}))
    assert payload["parameters"]["duration"] == 5
    assert payload["parameters"]["seed"] == 42


def test_万相27的比例字段叫ratio而不是aspect_ratio() -> None:
    """2.7 官方请求体在 parameters 下收 `ratio`；发成 `aspect_ratio` 会被忽略或拒绝。"""
    payload = build_submit_payload(
        _req(
            model="wan2.7-t2v",
            parameters={"duration_seconds": 8, "resolution": "1080P", "aspect_ratio": "9:16"},
        )
    )
    assert payload["parameters"]["ratio"] == "9:16"
    assert "aspect_ratio" not in payload["parameters"]


def test_图生视频走同一个端点_只多一个首帧(tmp_path) -> None:
    """和火山 / MiniMax 不同:那两家图生视频有独立路径或独立 content 数组,这家只是 input 多一项。"""
    png = tmp_path / "first.png"
    png.write_bytes(bytes.fromhex("89504e470d0a1a0a"))
    payload = build_submit_payload(_req(sources=tuple(SourceAsset(role=FIRST_FRAME, path=p) for p in [png])))
    assert payload["input"]["prompt"] == "海边黄昏"
    assert payload["input"]["img_url"].startswith("data:image/"), "首帧没转成 data URL"


# ---------------- 万相视频:回包 ----------------


def test_成功时取出视频地址() -> None:
    got = extract_video_url({"output": {"task_status": "SUCCEEDED", "video_url": "https://oss/v.mp4"}})
    assert got == "https://oss/v.mp4"


def test_结果放在数组里也认() -> None:
    got = extract_video_url({"output": {"task_status": "SUCCEEDED", "results": [{"url": "https://oss/v.mp4"}]}})
    assert got == "https://oss/v.mp4"


def test_运行中返回None继续轮询() -> None:
    for status in ("PENDING", "RUNNING"):
        assert extract_video_url({"output": {"task_status": status}}) is None


def test_不认识的状态当作还没结束_而不是失败() -> None:
    """百炼后来加的中间态若被判成失败,一次本来会成功的生成会被判死。"""
    assert extract_video_url({"output": {"task_status": "QUEUING_SOMETHING_NEW"}}) is None


def test_失败要抛_并且带上原因() -> None:
    with pytest.raises(GenerationAdapterError) as err:
        extract_video_url({"output": {"task_status": "FAILED", "message": "内容审核未通过"}})
    assert "内容审核未通过" in str(err.value), "把失败原因丢了,用户只看到一个状态码"


def test_成功却没有地址要抛_而不是静静返回空() -> None:
    with pytest.raises(GenerationAdapterError):
        extract_video_url({"output": {"task_status": "SUCCEEDED"}})


# ---------------- 万相视频:真机跑过之后补的 ----------------


def test_已经是星号的尺寸不会被改坏() -> None:
    """目录里给的档位本来就是 `832*480`(百炼收的就是像素对),而界面别处写的是 `1280x720`。
    两种都要接得住,且已经是星号的不能被二次替换弄坏。"""
    assert build_submit_payload(_req(parameters={"size": "832*480"}))["parameters"]["size"] == "832*480"
    assert build_submit_payload(_req(parameters={"size": "1280x720"}))["parameters"]["size"] == "1280*720"


def test_真机失败回包能读出原因() -> None:
    """百炼把失败原因放在 output.message。丢掉它的话,用户只看到一个 FAILED ——
    而这条真机回包里写着 `size is not supported`,那正是他需要知道的。"""
    real = {
        "request_id": "a9592167",
        "output": {
            "task_id": "e2f18bea", "task_status": "FAILED",
            "code": "InvalidParameter", "message": "size is not supported",
        },
    }
    with pytest.raises(GenerationAdapterError) as err:
        extract_video_url(real)
    assert "size is not supported" in str(err.value)


def test_真机成功回包能取出地址() -> None:
    """这是 wan2.2-t2v-plus 真实成功时的形状(2026-08-24):video_url 直接挂在 output 上,
    而同一家的图像走的是 output.results[].url —— 别串了。"""
    real = {
        "output": {
            "task_id": "7b26e27a", "task_status": "SUCCEEDED",
            "orig_prompt": "海边日落", "actual_prompt": "海边日落,金色光线",
            "video_url": "https://dashscope-7c2c.oss-cn-shanghai.aliyuncs.com/1d/f2/x.mp4",
        },
        "usage": {"video_duration": 5, "video_ratio": "832*480", "video_count": 1},
    }
    assert extract_video_url(real).endswith("x.mp4")


def test_档位名要映射成像素对() -> None:
    """生成面板的**视频**分支发的是 `resolution`(720p 这种档位名)——那是按火山/可灵定的形状。
    万相收的是像素对,把 "720p" 原样当尺寸发过去会被百炼拒掉。"""
    from app.ai.providers.adapters.alibaba.dashscope.video import resolve_size

    assert resolve_size({"resolution": "720p"}) == "1280*720"
    assert resolve_size({"resolution": "480p"}) == "832*480"
    # 显式 size 优先,且 1280x720 这种写法也接得住。
    assert resolve_size({"size": "1280x720", "resolution": "480p"}) == "1280*720"
    # 都没给就**不发这个字段**,让百炼用自己的默认,而不是我们替它猜一个。
    assert resolve_size({}) == ""


def test_首帧走仓库既有约定_而不是只看上传文件(tmp_path) -> None:
    """生成面板发的是 `first_frame_url`(seedance / kling 都这么取)。只读 source_files 的话,
    界面上填的首帧会被静默忽略 —— 图生视频退化成文生视频,而用户看不出发生了什么。"""
    payload = build_submit_payload(_req(parameters={"first_frame_url": "https://x/a.png"}))
    assert payload["input"]["img_url"] == "https://x/a.png"

    png = tmp_path / "f.png"
    png.write_bytes(bytes.fromhex("89504e470d0a1a0a"))
    payload = build_submit_payload(_req(sources=tuple(SourceAsset(role=FIRST_FRAME, path=p) for p in [png])))
    assert payload["input"]["img_url"].startswith("data:image/"), "上传的文件也要能当首帧"


def test_共享约定住在能力契约里_不住在某一家() -> None:
    """first_frame_value 此前定义在 Kling 实现里:Wan 得反过来 import 那一家,Seedance 抄了
    一遍。一个三家共用的约定住在某个供应商的文件里,读的人只会以为它是那家特有的。"""
    from app.ai.providers.contracts import generation
    from app.ai.providers.adapters.alibaba.dashscope import video as wan
    from app.ai.providers.adapters.kuaishou.kling import video as kling

    assert hasattr(generation, "first_frame_value")
    assert kling.first_frame_value is generation.first_frame_value
    assert wan.first_frame_value is generation.first_frame_value
