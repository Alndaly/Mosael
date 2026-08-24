"""阿里云百炼:万相视频 与 qwen-tts 语音。

**纯 payload 断言,不打网络** —— 和 test_minimax_video 同一套理由:这两个适配器的风险全在
"把内部请求翻成百炼的形状"和"从回包里把地址捞出来"这两步,而这类错误在真跑一次之前完全
看不出来。

顺带钉住一件容易做错的事:轮询时**不认识的状态要当作"还没结束"**,不能当失败。百炼后来加的
中间态若被判成失败,用户看到的是一次本来会成功的生成被判死。
"""

from __future__ import annotations

import pytest

from app.ai.providers.base import GenerationRequest, ProviderContext, ProviderError
from app.ai.providers.wan_video import build_submit_payload, extract_video_url
from app.audio.tts_providers import BailianTTS, extract_bailian_audio_url


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


def test_图生视频走同一个端点_只多一个首帧(tmp_path) -> None:
    """和火山 / MiniMax 不同:那两家图生视频有独立路径或独立 content 数组,这家只是 input 多一项。"""
    png = tmp_path / "first.png"
    png.write_bytes(bytes.fromhex("89504e470d0a1a0a"))
    payload = build_submit_payload(_req(source_files=[png]))
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
    with pytest.raises(ProviderError) as err:
        extract_video_url({"output": {"task_status": "FAILED", "message": "内容审核未通过"}})
    assert "内容审核未通过" in str(err.value), "把失败原因丢了,用户只看到一个状态码"


def test_成功却没有地址要抛_而不是静静返回空() -> None:
    with pytest.raises(ProviderError):
        extract_video_url({"output": {"task_status": "SUCCEEDED"}})


# ---------------- qwen-tts ----------------


def test_语音回包取的是audio_url() -> None:
    """同一家:图像走 output.results[].url,语音走 output.audio.url —— 别串了。"""
    assert extract_bailian_audio_url({"output": {"audio": {"url": "https://oss/a.wav"}}}) == "https://oss/a.wav"


def test_语音也认choices那种形状() -> None:
    payload = {"output": {"choices": [{"message": {"content": [{"audio": {"url": "https://oss/a.wav"}}]}}]}}
    assert extract_bailian_audio_url(payload) == "https://oss/a.wav"


def test_没有地址就是空串_由调用方报错() -> None:
    assert extract_bailian_audio_url({"output": {}}) == ""


def test_没有key直接拒绝_而不是发一个必然失败的请求() -> None:
    with pytest.raises(Exception) as err:
        BailianTTS(api_key="")
    assert "Key" in str(err.value)


def test_引擎id就是vendor_id() -> None:
    """audio/voices.py 拿 engine 去 resolve_profile,对不上就找不到那份凭据。"""
    from app.domain.provider_presets import VENDOR_PRESETS

    assert BailianTTS.id in VENDOR_PRESETS
    assert "tts" in VENDOR_PRESETS[BailianTTS.id]["capability_ids"]
