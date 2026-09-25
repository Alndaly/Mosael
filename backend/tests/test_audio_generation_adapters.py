"""音频生成各家 Adapter 的协议翻译(ADR 0022)。**全部 HTTP 都是假的** —— 这些接口按次收钱。

每家钉四件事:请求体照官方文档翻(字段名、模式选择)、异步的那几家**先落回执再等**并能凭回执接着取、
用户取消时停下来、错误码翻成归了类的人话(密钥 / 余额 / 限流 / 审核 / 参数)。

文档出处写在各 Adapter 文件头;这里的回包形状照那几页上的示例写。
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest

from app.ai.providers.contracts.generation import (
    REFERENCE_AUDIO,
    REFERENCE_IMAGE,
    GenerationAdapterContext,
    GenerationAdapterError,
    GenerationRequest,
    RemoteTaskWatch,
    SourceAsset,
    watching_remote_tasks,
)
from app.core.http_retry import RetryingClient

Handler = Callable[[httpx.Request], httpx.Response]


def _json(body: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.ai.providers.contracts.generation.time.sleep", lambda _s: None)


@pytest.fixture
def downloads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """音频下载:不出网,写几个字节并报回一个 Content-Type。"""
    fetched: list[str] = []

    def fake_download(url: str, target: Path, **_kw: Any) -> str:
        fetched.append(url)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"ID3fake")
        return "audio/mpeg" if url.endswith(".mp3") else "audio/wav" if url.endswith(".wav") else "video/mp4"

    monkeypatch.setattr("app.ai.audio_files.download_to_path", fake_download)
    # Evolink 的结果下载和图像、视频共用它自己模块里那一处。
    monkeypatch.setattr("app.ai.providers.adapters.evolink.generation.download_to_path", fake_download)
    return fetched


def _route(monkeypatch: pytest.MonkeyPatch, module: str, handler: Handler) -> list[httpx.Request]:
    """把某个 Adapter 模块里的 RetryingClient 换成走 MockTransport 的那一个。"""
    seen: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def factory(*args: Any, **kwargs: Any) -> RetryingClient:
        kwargs.pop("transport", None)
        return RetryingClient(*args, transport=httpx.MockTransport(recording), max_retries=0, **{
            key: value for key, value in kwargs.items() if key != "max_retries"
        })

    monkeypatch.setattr(f"{module}.RetryingClient", factory)
    return seen


def _ctx(vendor: str, **options: Any) -> GenerationAdapterContext:
    return GenerationAdapterContext(
        connection_id="c1", vendor_id=vendor, api_key=options.pop("api_key", "secret-key"),
        base_url=options.pop("base_url", ""), options=options,
    )


def _watch(cancelled: bool = False) -> tuple[RemoteTaskWatch, list[str]]:
    receipts: list[str] = []
    return RemoteTaskWatch(remember=receipts.append, is_cancelled=lambda: cancelled), receipts


def _audio(model: str, prompt: str = "city pop", **parameters: Any) -> GenerationRequest:
    return GenerationRequest(kind="audio", model=model, prompt=prompt, parameters=parameters)


# ── Evolink · Suno ──────────────────────────────────────────────────────────────────────────

EVOLINK = "app.ai.providers.adapters.evolink.generation"


def test_suno_只有描述时走简单模式_其余字段一个都不发() -> None:
    from app.ai.providers.adapters.evolink.generation import build_audio_payload

    assert build_audio_payload(_audio("suno-v5-beta", "summer night city pop")) == {
        "model": "suno-v5-beta", "prompt": "summer night city pop",
    }


def test_suno_给了歌词就走自定义模式_描述进style_歌词进prompt() -> None:
    from app.ai.providers.adapters.evolink.generation import build_audio_payload

    request = GenerationRequest(
        kind="audio", model="suno-v5-beta", prompt="pop, female vocals\n120bpm", negative_prompt="metal",
        parameters={"lyrics": "[Verse]\n晚风", "vocal_gender": "female", "title": ""},
    )
    assert build_audio_payload(request) == {
        "model": "suno-v5-beta",
        "custom_mode": True,
        "style": "pop, female vocals\n120bpm",
        "title": "pop, female vocals",  # 没给曲名时取描述第一行(自定义模式必填)
        "prompt": "[Verse]\n晚风",
        "negative_tags": "metal",
        "vocal_gender": "f",
    }


def test_suno_纯音乐与时长也走自定义模式() -> None:
    from app.ai.providers.adapters.evolink.generation import build_audio_payload

    payload = build_audio_payload(_audio("suno-v5.5-beta", "lofi piano", instrumental=True, duration_seconds=90))
    assert payload["custom_mode"] is True and payload["instrumental"] is True
    assert payload["duration"] == 90 and "prompt" not in payload


def test_suno_提交_落回执_轮询_两首都下载(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, downloads: list[str]) -> None:
    from app.ai.providers.adapters.evolink.generation import EvolinkGenerationAdapter

    polls = iter([
        {"id": "task-1", "status": "processing", "progress": 40},
        {"id": "task-1", "status": "completed", "results": ["https://cdn/a.mp3", "https://cdn/b.mp3"],
         "usage": {"credits_used": 8}},
    ])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            assert request.url.path == "/v1/audios/generations"
            assert request.headers["Authorization"] == "Bearer secret-key"
            return _json({"id": "task-1", "status": "pending", "type": "audio"})
        assert request.url.path == "/v1/tasks/task-1"
        return _json(next(polls))

    _route(monkeypatch, EVOLINK, handler)
    watch, receipts = _watch()
    with watching_remote_tasks(watch):
        result = EvolinkGenerationAdapter("audio").generate(_audio("suno-v5-beta"), _ctx("evolink"), tmp_path)
    assert receipts == ["/tasks/task-1"]
    assert downloads == ["https://cdn/a.mp3", "https://cdn/b.mp3"]
    assert [path.suffix for path in result.output_paths] == [".mp3", ".mp3"]


def test_suno_凭回执接着取_不再提交(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, downloads: list[str]) -> None:
    from app.ai.providers.adapters.evolink.generation import EvolinkGenerationAdapter

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET", "接着取不能再提交一次(那是再付一次钱)"
        return _json({"status": "completed", "result_data": {"songs": [{"audio_url": "https://cdn/c.mp3"}]}})

    _route(monkeypatch, EVOLINK, handler)
    adapter = EvolinkGenerationAdapter("audio")
    assert adapter.supports_resume
    result = adapter.resume("/tasks/task-9", _audio("suno-v5-beta"), _ctx("evolink"), tmp_path)
    assert downloads == ["https://cdn/c.mp3"] and len(result.output_paths) == 1


def test_suno_失败按错误码归类(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.ai.providers.adapters.evolink.generation import EvolinkGenerationAdapter

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return _json({"id": "t"})
        return _json({"status": "failed", "error": {"code": "content_policy_violation", "message": "blocked"}})

    _route(monkeypatch, EVOLINK, handler)
    with pytest.raises(GenerationAdapterError) as err:
        EvolinkGenerationAdapter("audio").generate(_audio("suno-v5-beta"), _ctx("evolink"), tmp_path)
    assert err.value.key == "providerErr_upstreamContentBlocked" and "blocked" in str(err.value)


def test_suno_余额不足在提交时就说清(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.ai.providers.adapters.evolink.generation import EvolinkGenerationAdapter

    _route(monkeypatch, EVOLINK, lambda _r: _json({"error": {"code": "insufficient_quota"}}, 402))
    with pytest.raises(GenerationAdapterError) as err:
        EvolinkGenerationAdapter("audio").generate(_audio("suno-v5-beta"), _ctx("evolink"), tmp_path)
    assert err.value.key == "providerErr_upstreamBalance"
    assert "secret-key" not in str(err.value)


def test_suno_用户取消就停下(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.ai.providers.adapters.evolink.generation import EvolinkGenerationAdapter

    _route(monkeypatch, EVOLINK, lambda r: _json({"id": "t"}) if r.method == "POST" else _json({"status": "processing"}))
    watch, receipts = _watch(cancelled=True)
    with watching_remote_tasks(watch), pytest.raises(GenerationAdapterError) as err:
        EvolinkGenerationAdapter("audio").generate(_audio("suno-v5-beta"), _ctx("evolink"), tmp_path)
    assert err.value.key == "providerErr_cancelled"
    assert receipts == ["/tasks/t"], "取消之前回执已经落下 —— 花了钱的任务还找得回来"


# ── 可灵 · 文生音效 / 视频生音效 ─────────────────────────────────────────────────────────────

KLING = "app.ai.providers.adapters.kuaishou.kling.audio"


def test_可灵文生音效_请求体与轮询(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, downloads: list[str]) -> None:
    from app.ai.providers.adapters.kuaishou.kling.audio import KlingAudioAdapter

    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            assert request.url.path == "/v1/audio/text-to-audio"
            bodies.append(json.loads(request.content))
            return _json({"code": 0, "data": {"task_id": "k1", "task_status": "submitted"}})
        assert request.url.path == "/v1/audio/text-to-audio/k1"
        return _json({"code": 0, "data": {"task_id": "k1", "task_status": "succeed", "final_unit_deduction": "0.25",
                                         "task_result": {"audios": [{"id": "x", "url_mp3": "https://k/a.mp3",
                                                                     "url_wav": "https://k/a.wav"}]}}})

    _route(monkeypatch, KLING, handler)
    watch, receipts = _watch()
    with watching_remote_tasks(watch):
        result = KlingAudioAdapter().generate(
            _audio("kling-text-to-audio", "烟花声", duration_seconds=4), _ctx("kuaishou"), tmp_path
        )
    assert bodies == [{"prompt": "烟花声", "duration": 4.0}]
    assert receipts == ["/v1/audio/text-to-audio/k1"]
    # wav 优先(剪辑时是无损的那一份)
    assert downloads == ["https://k/a.wav"] and result.output_paths[0].suffix == ".wav"
    assert result.raw_usage["final_unit_deduction"] == "0.25"


def test_可灵视频生音效_只发链接_提示词可以不给(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ai.providers.adapters.kuaishou.kling.audio import build_payload

    payload = build_payload(GenerationRequest(
        kind="audio", model="kling-video-to-audio", prompt="",
        parameters={"source_video_url": "https://x/clip.mp4", "bgm_prompt": "轻快", "asmr_mode": True},
    ))
    assert payload == {"video_url": "https://x/clip.mp4", "bgm_prompt": "轻快", "asmr_mode": True}
    with pytest.raises(GenerationAdapterError):
        build_payload(GenerationRequest(kind="audio", model="kling-video-to-audio", prompt="x"))


def test_可灵接着取与错误码(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, downloads: list[str]) -> None:
    from app.ai.providers.adapters.kuaishou.kling.audio import KlingAudioAdapter

    _route(monkeypatch, KLING, lambda r: _json({"code": 0, "data": {"task_status": "succeed", "task_result": {
        "audios": [{"url_mp3": "https://k/b.mp3"}]}}}))
    KlingAudioAdapter().resume("/v1/audio/video-to-audio/k2", _audio("kling-video-to-audio"), _ctx("kuaishou"), tmp_path)
    assert downloads == ["https://k/b.mp3"]

    _route(monkeypatch, KLING, lambda r: _json({"code": 1102, "message": "resource pack exhausted"}, 429))
    with pytest.raises(GenerationAdapterError) as err:
        KlingAudioAdapter().generate(_audio("kling-text-to-audio"), _ctx("kuaishou"), tmp_path)
    assert err.value.key == "providerErr_upstreamBalance"

    _route(monkeypatch, KLING, lambda r: _json({"code": 0, "data": {"task_id": "k3"}}) if r.method == "POST"
           else _json({"code": 0, "data": {"task_status": "failed", "task_status_msg": "bad video"}}))
    with pytest.raises(GenerationAdapterError, match="bad video"):
        KlingAudioAdapter().generate(_audio("kling-text-to-audio"), _ctx("kuaishou"), tmp_path)


# ── 火山引擎 · AI 音乐生成 ──────────────────────────────────────────────────────────────────

VOLCANO = "app.ai.providers.adapters.bytedance.volcano.music"


def test_火山_人声歌曲_歌词和描述只发一段_每个请求都签名(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, downloads: list[str]) -> None:
    from app.ai.providers.adapters.bytedance.volcano.music import VolcanoMusicAdapter

    seen: list[tuple[str, dict[str, Any]]] = []
    polls = iter([{"Status": 1, "Progress": 50}, {"Status": 2, "SongDetail": {"AudioUrl": "https://v1-default.douyinvod.com/x.mp4", "Duration": 61.5}}])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.headers["Authorization"].startswith("HMAC-SHA256 Credential=AKID/")
        assert "/cn-beijing/imagination/request" in request.headers["Authorization"]
        action = request.url.params["Action"]
        body = json.loads(request.content)
        seen.append((action, body))
        if action == "GenSongForTime":
            return _json({"Code": 0, "Result": {"TaskID": "T1"}, "ResponseMetadata": {}})
        assert action == "QuerySong" and body == {"TaskID": "T1"}
        return _json({"Code": 0, "Result": {"TaskID": "T1", **next(polls)}, "ResponseMetadata": {}})

    _route(monkeypatch, VOLCANO, handler)
    watch, receipts = _watch()
    with watching_remote_tasks(watch):
        result = VolcanoMusicAdapter().generate(
            GenerationRequest(kind="audio", model="GenSongForTime", prompt="",
                              parameters={"lyrics": "[verse] 晚风", "duration_seconds": 60, "model_version": "v5.0"}),
            _ctx("volcano-music", api_key="AKID", sk="SECRET"), tmp_path,
        )
    assert seen[0] == ("GenSongForTime", {"Lyrics": "[verse] 晚风", "Duration": 60, "ModelVersion": "v5.0"})
    assert receipts == ["QuerySong/T1"]
    # 文档:地址可能是 mp4 容器 —— 进素材库时要是音频,不是视频
    assert result.output_paths[0].suffix == ".m4a"
    # 后付费按成功生成的秒数计,就是回包的 Duration
    assert result.usage["audio_seconds"] == 61.5


def test_火山_纯音乐只发描述() -> None:
    from app.ai.providers.adapters.bytedance.volcano.music import build_body

    assert build_body(_audio("GenBGMForTime", "轻松的咖啡馆爵士", duration_seconds=45)) == {"Text": "轻松的咖啡馆爵士", "Duration": 45}
    assert build_body(_audio("GenSongV4", "欢快的流行")) == {"Prompt": "欢快的流行"}


def test_火山_接着取_失败与错误码(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, downloads: list[str]) -> None:
    from app.ai.providers.adapters.bytedance.volcano.music import VolcanoMusicAdapter

    ctx = _ctx("volcano-music", api_key="AKID", sk="SECRET")
    _route(monkeypatch, VOLCANO, lambda r: _json({"Result": {"Status": 2, "SongDetail": {"AudioUrl": "https://v/y.wav"}}}))
    VolcanoMusicAdapter().resume("QuerySong/T2", _audio("GenBGMForTime"), ctx, tmp_path)
    assert downloads == ["https://v/y.wav"]

    _route(monkeypatch, VOLCANO, lambda r: _json({"Result": {"Status": 3, "FailureReason": {"Code": 300063, "Msg": "InputNotSafe"}}}))
    with pytest.raises(GenerationAdapterError) as err:
        VolcanoMusicAdapter().resume("QuerySong/T3", _audio("GenBGMForTime"), ctx, tmp_path)
    assert err.value.key == "providerErr_upstreamContentBlocked"

    _route(monkeypatch, VOLCANO, lambda r: _json({"ResponseMetadata": {"Error": {"CodeN": 200028, "Code": "APINoSource", "Message": "no pack"}}}, 400))
    with pytest.raises(GenerationAdapterError) as err:
        VolcanoMusicAdapter().generate(_audio("GenSongV4"), ctx, tmp_path)
    assert err.value.key == "providerErr_upstreamNotEntitled"
    assert "SECRET" not in str(err.value)


def test_火山_没有SK就说去补全连接(tmp_path: Path) -> None:
    from app.ai.providers.adapters.bytedance.volcano.music import VolcanoMusicAdapter

    with pytest.raises(GenerationAdapterError) as err:
        VolcanoMusicAdapter().generate(_audio("GenBGM"), _ctx("volcano-music", api_key="AKID"), tmp_path)
    assert err.value.key == "providerErr_volcanoMusicKeysMissing"


def test_火山签名和音色列表用的是同一个实现() -> None:
    import datetime as dt

    from app.ai.providers.adapters.bytedance.volcano.openapi_sign import signed_headers
    from app.integrations import volc_openapi

    moment = dt.datetime(2026, 9, 25, 12, 0, 0, tzinfo=dt.UTC)
    one = signed_headers("AK", "SK", "Action=QuerySong&Version=2024-08-12", b"{}", service="imagination", now=moment)
    two = signed_headers("AK", "SK", "Action=QuerySong&Version=2024-08-12", b"{}", service="speech_saas_prod", now=moment)
    assert one["X-Date"] == "20260925T120000Z"
    assert "20260925/cn-beijing/imagination/request" in one["Authorization"]
    assert one["Authorization"] != two["Authorization"], "服务名进签名范围"
    assert volc_openapi.SERVICE == "speech_saas_prod"


# ── MiniMax · 音乐生成(同步)──────────────────────────────────────────────────────────────

MINIMAX = "app.ai.providers.adapters.minimax.music"


def test_minimax_有人声没歌词_打开自动写词(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.ai.providers.adapters.minimax.music import MiniMaxMusicAdapter

    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/music_generation", "档案里填的 /v1 不能拼成 /v1/v1"
        bodies.append(json.loads(request.content))
        return _json({"data": {"audio": b"ID3music".hex(), "status": 2}, "extra_info": {"music_duration": 25364},
                      "base_resp": {"status_code": 0, "status_msg": "success"}})

    _route(monkeypatch, MINIMAX, handler)
    result = MiniMaxMusicAdapter().generate(
        _audio("music-3.0", "夏夜城市流行"), _ctx("minimax", base_url="https://api.minimaxi.com/v1"), tmp_path
    )
    assert bodies[0]["lyrics_optimizer"] is True and "is_instrumental" not in bodies[0]
    assert bodies[0]["output_format"] == "hex" and bodies[0]["model"] == "music-3.0"
    assert result.output_paths[0].read_bytes() == b"ID3music"
    # 单位没写明的 music_duration 不冒充秒数
    assert "audio_seconds" not in result.usage and result.raw_usage["extra_info"]["music_duration"] == 25364


def test_minimax_纯音乐与翻唱() -> None:
    from app.ai.providers.adapters.minimax.music import build_payload

    instrumental = build_payload(_audio("music-2.6", "lofi", instrumental=True))
    assert instrumental["is_instrumental"] is True and "lyrics_optimizer" not in instrumental
    cover = build_payload(_audio("music-cover", "换成爵士", reference_audio_url="https://x/song.mp3"))
    assert cover["audio_url"] == "https://x/song.mp3" and "lyrics_optimizer" not in cover


def test_minimax_翻唱的本地参考音频走base64(tmp_path: Path) -> None:
    from app.ai.providers.adapters.minimax.music import build_payload

    song = tmp_path / "song.mp3"
    song.write_bytes(b"ID3")
    payload = build_payload(GenerationRequest(
        kind="audio", model="music-cover", prompt="换成爵士", sources=(SourceAsset(role=REFERENCE_AUDIO, path=song),),
    ))
    assert payload["audio_base64"] == base64.b64encode(b"ID3").decode()


@pytest.mark.parametrize(
    "code, key",
    [(1004, "providerErr_upstreamAuth"), (1008, "providerErr_upstreamBalance"), (1002, "providerErr_upstreamRateLimited"),
     (1026, "providerErr_upstreamContentBlocked"), (2013, "providerErr_upstreamInvalidParams"), (9999, "providerErr_generationFailed")],
)
def test_minimax_错误以200返回_按base_resp归类(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, code: int, key: str) -> None:
    from app.ai.providers.adapters.minimax.music import MiniMaxMusicAdapter

    _route(monkeypatch, MINIMAX, lambda _r: _json({"base_resp": {"status_code": code, "status_msg": "nope"}}))
    with pytest.raises(GenerationAdapterError) as err:
        MiniMaxMusicAdapter().generate(_audio("music-3.0"), _ctx("minimax"), tmp_path)
    assert err.value.key == key


def test_minimax_同步付费请求不重试(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """读超时后重发 = 让对面再写一首、再收一次钱。"""
    from app.ai.providers.adapters.minimax import music

    captured: dict[str, Any] = {}

    class Spy:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

        def __enter__(self):
            raise httpx.ConnectError("offline")

        def __exit__(self, *_a: object) -> None:
            return None

    monkeypatch.setattr(music, "RetryingClient", Spy)
    with pytest.raises(GenerationAdapterError):
        music.MiniMaxMusicAdapter().generate(_audio("music-3.0"), _ctx("minimax"), tmp_path)
    assert captured["max_retries"] == 0


# ── Google · Lyria(同步)───────────────────────────────────────────────────────────────────

LYRIA = "app.ai.providers.adapters.google.lyria"


def test_lyria_纯音乐与歌词按文档拼进提示词_音频取inlineData(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.ai.providers.adapters.google.lyria import LyriaAdapter

    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1beta/models/lyria-3.5:generateContent"
        assert request.headers["x-goog-api-key"] == "secret-key"
        bodies.append(json.loads(request.content))
        return _json({"candidates": [{"content": {"parts": [
            {"text": "[Verse] lyrics text"},
            {"inlineData": {"mimeType": "audio/mpeg", "data": base64.b64encode(b"ID3lyria").decode()}},
        ]}}], "usageMetadata": {"promptTokenCount": 12}})

    _route(monkeypatch, LYRIA, handler)
    result = LyriaAdapter().generate(_audio("lyria-3.5", "ambient piano", instrumental=True), _ctx("google"), tmp_path)
    assert bodies[0] == {"contents": [{"parts": [{"text": "ambient piano\n\nInstrumental only, no vocals."}]}]}
    assert result.output_paths[0].suffix == ".mp3" and result.output_paths[0].read_bytes() == b"ID3lyria"
    assert result.raw_usage["text"] == "[Verse] lyrics text"
    assert "inlineData" not in json.dumps(result.raw_usage), "几兆的 base64 不进用量表"


def test_lyria_参考图作为inline_data附上(tmp_path: Path) -> None:
    from app.ai.providers.adapters.google.lyria import build_payload

    image = tmp_path / "cover.png"
    image.write_bytes(b"\x89PNG")
    payload = build_payload(GenerationRequest(
        kind="audio", model="lyria-3.5", prompt="match this", parameters={"lyrics": "[Chorus] la"},
        sources=(SourceAsset(role=REFERENCE_IMAGE, path=image),),
    ))
    parts = payload["contents"][0]["parts"]
    assert parts[0]["text"] == "match this\n\n[Chorus] la"
    assert parts[1]["inline_data"]["mime_type"] == "image/png"


def test_lyria_审核拦下与密钥错误(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.ai.providers.adapters.google.lyria import LyriaAdapter

    _route(monkeypatch, LYRIA, lambda _r: _json({"promptFeedback": {"blockReason": "SAFETY"}}))
    with pytest.raises(GenerationAdapterError) as err:
        LyriaAdapter().generate(_audio("lyria-3.5"), _ctx("google"), tmp_path)
    assert err.value.key == "providerErr_upstreamContentBlocked"

    _route(monkeypatch, LYRIA, lambda _r: _json({"error": {"message": "API key not valid"}}, 403))
    with pytest.raises(GenerationAdapterError) as err:
        LyriaAdapter().generate(_audio("lyria-3.5"), _ctx("google"), tmp_path)
    assert err.value.key == "providerErr_upstreamAuth"
    assert "secret-key" not in str(err.value)


# ── 百炼 · Fun-Music / AudioGen(同步)──────────────────────────────────────────────────────

DASHSCOPE = "app.ai.providers.adapters.alibaba.dashscope.audio"


def test_百炼音乐_请求体_下载_按秒计(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, downloads: list[str]) -> None:
    from app.ai.providers.adapters.alibaba.dashscope.audio import DashScopeAudioAdapter

    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        # 对话用的 compatible-mode 地址要归一回原生根
        assert request.url.path == "/api/v1/services/audio/music/generation"
        bodies.append(json.loads(request.content))
        return _json({"output": {"audio": {"url": "https://oss/x.mp3"}, "finish_reason": "stop"},
                      "usage": {"duration": 200}, "request_id": "r1"})

    _route(monkeypatch, DASHSCOPE, handler)
    result = DashScopeAudioAdapter().generate(
        _audio("fun-music-v1", "", lyrics="[verse] 你好", vocal_gender="male", output_format="mp3"),
        _ctx("alibaba", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"), tmp_path,
    )
    assert bodies[0] == {"model": "fun-music-v1", "input": {"lyrics": "[verse] 你好", "gender": "male", "format": "mp3"}}
    assert downloads == ["https://oss/x.mp3"] and result.usage["audio_seconds"] == 200.0


def test_百炼音效_参考音频按直链或data_uri() -> None:
    from app.ai.providers.adapters.alibaba.dashscope.audio import build_payload

    payload = build_payload(_audio("qwen-audio-3.1-tts-next", "雨打铁皮屋顶 @voice1", reference_audio_url="https://x/r.wav", seed=7))
    assert payload == {"model": "qwen-audio-3.1-tts-next", "input": {
        "text_prompt": "雨打铁皮屋顶 @voice1", "references": [{"audio_url": "https://x/r.wav"}], "seed": 7}}


def test_百炼错误码归类(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.ai.providers.adapters.alibaba.dashscope.audio import DashScopeAudioAdapter

    for code, status, key in (
        ("InvalidApiKey", 401, "providerErr_upstreamAuth"),
        ("Throttling.RateQuota", 429, "providerErr_upstreamRateLimited"),
        ("DataInspectionFailed", 400, "providerErr_upstreamContentBlocked"),
        ("AccessDenied", 403, "providerErr_upstreamNotEntitled"),
    ):
        _route(monkeypatch, DASHSCOPE, lambda _r, code=code, status=status: _json({"code": code, "message": "x"}, status))
        with pytest.raises(GenerationAdapterError) as err:
            DashScopeAudioAdapter().generate(_audio("fun-music-v1"), _ctx("alibaba"), tmp_path)
        assert err.value.key == key, code


# ── 共用:音频文件的扩展名 ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url, content_type, suffix",
    [("https://x/a.mp3", "", ".mp3"), ("https://x/a", "audio/wav", ".wav"), ("https://x/a.mp4", "", ".m4a"),
     ("https://x/a.bin", "video/mp4", ".m4a"), ("https://x/a", "", ".mp3")],
)
def test_音频扩展名按回包优先_mp4容器记成m4a(url: str, content_type: str, suffix: str) -> None:
    from app.ai.audio_files import audio_suffix
    from app.media.probe import guess_kind

    assert audio_suffix(url, content_type) == suffix
    assert guess_kind(Path(f"x{suffix}")) == "audio", "扩展名要让素材库把它认成音频"
