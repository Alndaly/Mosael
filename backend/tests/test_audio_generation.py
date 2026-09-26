"""音频是生成的第三种(ADR 0022):描述符、提交前校验、执行器登记与计量、价目。

各家 Adapter 的协议翻译在 test_audio_generation_adapters.py;插件声明音频模型那一条在
test_plugin_generation_providers.py。这里钉的是**框架**:加一种介质之后,每个入口都认它,
规矩只写在一处。
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from app.ai.providers import get_generation_adapter, register_generation_adapter_source
from app.ai.providers.contracts.generation import (
    FIRST_CLIP,
    REFERENCE_AUDIO,
    SOURCE_VIDEO,
    GenerationAdapter,
    GenerationAdapterContext,
    GenerationRequest,
    GenerationResult,
    metering_from_request,
)
from app.core.db import SessionLocal
from app.db.models import Asset, GeneratedAsset, Job, ProviderUsageEvent
from app.domain import price_reference, provider_models
from app.domain.generation import catalog as C
from app.domain.generation.operations import (
    GenerationDomainError,
    validate_against_capabilities,
    validate_text_inputs,
)
from app.domain.generation.resolution import KINDS
from app.domain.generation.runner import expected_asset_kind
from app.domain.provider_defaults import DEFAULTABLE_CAPABILITIES
from app.domain.provider_presets import KNOWN_CAPABILITY_IDS
from app.domain.usage import PRICING_BILLING_UNITS, _quantity_for_unit
from sqlalchemy import select
from tests.util import add_provider, fresh_client, wait_status


# --- 一种介质,处处都认 ---------------------------------------------------------


def test_音频是生成的一种_各处读的是同一份() -> None:
    assert C.GENERATION_KINDS == ("image", "video", "audio")
    assert KINDS == C.GENERATION_KINDS
    assert "audio" in KNOWN_CAPABILITY_IDS and "audio" in DEFAULTABLE_CAPABILITIES


def test_每个内置音频模型都有能跑的Adapter_且描述符是自洽的() -> None:
    audio = [one for one in C.BUILTIN_MODELS if one["kind"] == "audio"]
    assert audio, "目录里一个音频模型都没有"
    for item in audio:
        caps = item["capabilities"]
        assert get_generation_adapter(item["provider"], "audio") is not None, item["id"]
        assert caps["modes"], item["id"]
        keys = set(caps["parameter_keys"])
        # 布尔参数、声明式参数、素材上限都得是这个模型真认的键
        assert set(caps.get("boolean_parameters") or ()) <= keys, item["id"]
        assert set(caps.get("parameter_schema") or {}) <= keys, item["id"]
        assert set(caps.get("source_limits") or {}) <= keys, item["id"]
        if "max_lyrics_chars" in caps:
            assert "lyrics" in keys, item["id"]
        if caps.get("default_instrumental") is not None:
            assert "instrumental" in keys, item["id"]


def test_音频模型从目录推得出能力_不被名字线索误判成语音合成() -> None:
    """`qwen-audio-3.1-tts-next` 名字里有 tts,而它在目录里是**音频生成** —— 目录是查证过的事实,先于名字线索。"""
    assert provider_models.infer_capabilities("alibaba", "qwen-audio-3.1-tts-next") == ["audio"]
    assert provider_models.infer_capabilities("google", "lyria-3.5") == ["audio"]
    assert provider_models.infer_capabilities("evolink", "suno-v5-beta") == ["audio"]


def test_每个素材角色都说了收哪种素材() -> None:
    """漏写的角色会在执行时 KeyError —— 加角色时这里先红。"""
    from app.ai.providers import SOURCE_ROLES
    from app.domain.generation.runner import ROLE_ASSET_KIND

    assert set(ROLE_ASSET_KIND) == set(SOURCE_ROLES)


def test_角色按生成种类收对的素材() -> None:
    assert expected_asset_kind(REFERENCE_AUDIO, "audio") == "audio"
    assert expected_asset_kind(SOURCE_VIDEO, "audio") == "video"
    # 续写:视频那边接一段视频,音频那边接一段音频 —— 语义一样,介质跟着产出走
    assert expected_asset_kind(FIRST_CLIP, "video") == "video"
    assert expected_asset_kind(FIRST_CLIP, "audio") == "audio"


# --- 提交前的文字规矩 -----------------------------------------------------------


def _text(kind: str, prompt: str, parameters: dict, capabilities: dict | None = None) -> None:
    validate_text_inputs("p", "m", kind, prompt, parameters, capabilities=capabilities)


def test_会唱歌词的模型可以只给歌词_什么都不给不行() -> None:
    caps = C.EVOLINK_SUNO_CAPABILITIES
    _text("audio", "", {"lyrics": "[Verse] 啦"}, caps)
    _text("audio", "城市流行", {}, caps)
    with pytest.raises(GenerationDomainError, match="描述和歌词至少要给一段"):
        _text("audio", "  ", {"lyrics": " "}, caps)


def test_给视频配声的模型什么字都可以不给() -> None:
    assert C.KLING_VIDEO_TO_AUDIO_CAPABILITIES["prompt"] == "optional"
    _text("audio", "", {}, C.KLING_VIDEO_TO_AUDIO_CAPABILITIES)


def test_不会唱歌词的模型照旧要提示词() -> None:
    with pytest.raises(GenerationDomainError, match="要写一段描述"):
        _text("audio", "", {}, C.KLING_TEXT_TO_AUDIO_CAPABILITIES)


def test_纯音乐不带歌词_而且要有描述() -> None:
    caps = C.GOOGLE_LYRIA_CAPABILITIES
    with pytest.raises(GenerationDomainError, match="二选一"):
        _text("audio", "钢琴", {"instrumental": True, "lyrics": "啦啦"}, caps)
    with pytest.raises(GenerationDomainError, match="纯音乐要写一段描述"):
        _text("audio", "", {"instrumental": True}, caps)
    _text("audio", "钢琴", {"instrumental": True}, caps)


def test_歌词按模型的上限拦() -> None:
    caps = C.EVOLINK_SUNO_CAPABILITIES
    _text("audio", "", {"lyrics": "啦" * 5000}, caps)
    with pytest.raises(GenerationDomainError, match="5000"):
        _text("audio", "", {"lyrics": "啦" * 5001}, caps)


def test_歌词和描述只收一段的模型_两段都给当场说() -> None:
    caps = C.VOLCANO_SONG_CAPABILITIES
    _text("audio", "", {"lyrics": "啦啦啦啦啦"}, caps)
    _text("audio", "欢快的流行", {}, caps)
    with pytest.raises(GenerationDomainError, match="只能给一段"):
        _text("audio", "欢快的流行", {"lyrics": "啦啦啦啦啦"}, caps)


def test_不会唱歌词的模型_给了歌词也不能代替描述() -> None:
    with pytest.raises(GenerationDomainError, match="要写一段描述"):
        _text("audio", "", {"lyrics": "只有歌词"}, C.KLING_TEXT_TO_AUDIO_CAPABILITIES)


def test_歌词必须是文字() -> None:
    with pytest.raises(GenerationDomainError):
        _text("audio", "x", {"lyrics": ["不是", "文字"]})


# --- 参数与素材按描述符 ---------------------------------------------------------


def test_音频的参数按描述符拦() -> None:
    caps = C.VOLCANO_SONG_CAPABILITIES
    validate_against_capabilities("volcano-music", "GenSongForTime", "audio", {"duration_seconds": 120}, [], capabilities=caps)
    with pytest.raises(GenerationDomainError):
        validate_against_capabilities("volcano-music", "GenSongForTime", "audio", {"duration_seconds": 20}, [], capabilities=caps)
    with pytest.raises(GenerationDomainError):
        validate_against_capabilities("volcano-music", "GenSongForTime", "audio", {"bpm": 120}, [], capabilities=caps)
    with pytest.raises(GenerationDomainError):
        validate_against_capabilities(
            "volcano-music", "GenSongForTime", "audio", {"model_version": "v9"}, [], capabilities=caps
        )
    # 纯音乐是布尔开关,字符串 "true" 不收
    with pytest.raises(GenerationDomainError):
        validate_against_capabilities(
            "google", "lyria-3.5", "audio", {"instrumental": "true"}, [], capabilities=C.GOOGLE_LYRIA_CAPABILITIES
        )
    # 人声性别按它自己的声明查可选值
    with pytest.raises(GenerationDomainError):
        validate_against_capabilities(
            "evolink", "suno-v5-beta", "audio", {"vocal_gender": "robot"}, [], capabilities=C.EVOLINK_SUNO_CAPABILITIES
        )


def test_视频配声必须挂那段视频_而且只收链接() -> None:
    caps = C.KLING_VIDEO_TO_AUDIO_CAPABILITIES
    with pytest.raises(GenerationDomainError):
        validate_against_capabilities("kuaishou", "kling-video-to-audio", "audio", {}, [], capabilities=caps)
    validate_against_capabilities(
        "kuaishou", "kling-video-to-audio", "audio", {"source_video_url": "https://x/v.mp4"}, [], capabilities=caps
    )
    assert caps["url_only_roles"] == ["source_video"]


# --- 计量与价目 -----------------------------------------------------------------


def test_音频的计量单位() -> None:
    units = metering_from_request(GenerationRequest(kind="audio", model="m", prompt="p", parameters={"lyrics": "啦啦"}))
    assert units["audios"] == 1 and units["lyrics_characters"] == 2
    # 请求里的时长只是期望,不记成计费秒数 —— 真实秒数由供应商回报或登记后探测
    requested = metering_from_request(
        GenerationRequest(kind="audio", model="m", prompt="p", parameters={"duration_seconds": 30})
    )
    assert "audio_seconds" not in requested
    assert "audio" in PRICING_BILLING_UNITS and "audio_second" in PRICING_BILLING_UNITS
    assert _quantity_for_unit({"audios": 2}, "audio") == 2
    assert _quantity_for_unit({"audio_seconds": 12.5}, "audio_second") == 12.5


def test_音频的挂牌价只收查证过的() -> None:
    [lyria] = price_reference.lookup("google", "lyria-3.5", region="global")
    assert (lyria.capability, lyria.billing_unit, lyria.currency, lyria.unit_amount_micros) == ("audio", "audio", "USD", 80_000)
    [clip] = price_reference.lookup("google", "lyria-3-clip-preview", region="global")
    assert clip.unit_amount_micros == 40_000
    [fun] = price_reference.lookup("alibaba", "fun-music-v1", region="cn")
    assert (fun.billing_unit, fun.currency, fun.unit_amount_micros) == ("audio_second", "CNY", 2_000)
    [song] = price_reference.lookup("volcano-music", "GenSongForTime", region="cn")
    assert (song.billing_unit, song.unit_amount_micros) == ("audio_second", 2_000)
    # 没查证到按次价的不收
    assert price_reference.lookup("kuaishou", "kling-text-to-audio", region="cn") == []
    assert price_reference.lookup_for_relay("suno-v5-beta") == []


# --- 端到端:普通的生成执行器跑一次音频 -----------------------------------------


def _silence(path: Path, seconds: float = 1.0) -> Path:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * int(8000 * seconds))
    return path


class _FakeAudioAdapter(GenerationAdapter):
    """一个不打网络的音频 Adapter:写一段一秒的静音,并**回报**供应商口中的计费秒数。"""

    vendor_id = "fake-audio"
    media_kind = "audio"
    seen: list[GenerationRequest] = []

    def requires_credentials(self) -> bool:
        return False

    def generate(self, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        type(self).seen.append(request)
        output_dir.mkdir(parents=True, exist_ok=True)
        first = _silence(output_dir / "take-1.wav")
        # 两首长短不同 —— 内容一样的两个文件在素材库里会被当成同一份
        second = _silence(output_dir / "take-2.wav", seconds=1.5)
        usage = {**metering_from_request(request), "audio_seconds": 42.0}
        return GenerationResult(output_paths=[first, second], usage=usage, raw_usage={"billed": 42})


def _fake_source(vendor: str, kind: str) -> GenerationAdapter | None:
    return _FakeAudioAdapter() if (vendor, kind) == ("fake-audio", "audio") else None


register_generation_adapter_source(_fake_source)


def test_一次音频生成走普通的执行器_每一首都登记成音频素材() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "音乐"}).json()["id"]
    with SessionLocal() as db:
        profile = add_provider(
            db, name="假音乐", vendor="fake-audio", base_url="", api_key="k",
            model="song-1", capability_ids=["audio"], make_default=False,
        )
        db.commit()
        profile_id = profile.id
    options = client.get("/api/generation/options?kind=audio").json()
    assert [(one["provider"], one["model"], one["adapter_available"]) for one in options] == [("fake-audio", "song-1", True)]

    _FakeAudioAdapter.seen.clear()
    response = client.post(
        "/api/generation/jobs",
        json={
            "workspace_id": workspace,
            "provider_profile_id": profile_id,
            "provider": "fake-audio",
            "model": "song-1",
            "kind": "audio",
            "prompt": "夏夜城市流行",
            "parameters": {"lyrics": "[Verse]\n晚风", "instrumental": False},
        },
    )
    assert response.status_code == 200, response.text
    job_id = response.json()["job"]["id"]
    assert wait_status(client, job_id, timeout=30) == "succeeded"
    [request] = _FakeAudioAdapter.seen
    assert request.kind == "audio" and request.parameters["lyrics"] == "[Verse]\n晚风"

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        asset_ids = job.result["asset_ids"]
        assert len(asset_ids) == 2, "一次交回两首,两首都要进素材库"
        for asset_id, seconds in zip(asset_ids, (1.0, 1.5)):
            asset = db.get(Asset, asset_id)
            assert asset.kind == "audio"
            assert asset.media_info["duration"] == pytest.approx(seconds, abs=0.05)
            assert db.get(GeneratedAsset, asset_id).model == "song-1"
        usage = db.scalars(select(ProviderUsageEvent).where(ProviderUsageEvent.job_id == job_id)).one()
        assert usage.capability == "audio"
        assert usage.units["audios"] == 2
        # 供应商回报的计费秒数优先于探测到的时长(两首合计探测是 2.5 秒)
        assert usage.units["audio_seconds"] == 42.0

    # 会话记录照样能回到生成历史里
    history = client.get(f"/api/generation/jobs?workspace_id={workspace}").json()
    [generation] = [one for one in history if one["job_id"] == job_id]
    assert generation["kind"] == "audio" and generation["result_asset_ids"] == asset_ids


def test_提交只给歌词的音频_接口不再要求提示词() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "音乐"}).json()["id"]
    with SessionLocal() as db:
        profile = add_provider(
            db, name="假音乐", vendor="fake-audio", base_url="", api_key="k",
            model="song-2", capability_ids=["audio"], make_default=False,
        )
        db.commit()
        profile_id = profile.id
    body = {
        "workspace_id": workspace, "provider_profile_id": profile_id, "provider": "fake-audio",
        "model": "song-2", "kind": "audio", "prompt": "",
    }
    rejected = client.post("/api/generation/jobs", json={**body, "parameters": {}})
    # 目录不认识的模型:不知道它收不收歌词,所以只给歌词放行;什么都不给时说的是「要写一段描述」。
    assert rejected.status_code == 422 and "要写一段描述" in rejected.json()["detail"]
    accepted = client.post("/api/generation/jobs", json={**body, "parameters": {"lyrics": "啦啦啦"}})
    assert accepted.status_code == 200, accepted.text
    assert wait_status(client, accepted.json()["job"]["id"], timeout=30) == "succeeded"
