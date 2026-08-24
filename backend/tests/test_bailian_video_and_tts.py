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


def test_档案填的是对话端点时_语音要归一到原生根() -> None:
    """真机踩到的:百炼档案的 base_url 往往填的是对话用的 compatible-mode 端点。

    直接往后拼会得到 `…/compatible-mode/v1/api/v1/services/…` —— 一个必然 404 的地址。
    图像那边早就解决过同一个坑(qwen_image.resolve_qwen_edit_base),语音沿用同一条判据。
    """
    from app.audio.tts_providers import DASHSCOPE_NATIVE_BASE, resolve_dashscope_native_base

    assert resolve_dashscope_native_base("https://dashscope.aliyuncs.com/compatible-mode/v1") == DASHSCOPE_NATIVE_BASE
    assert resolve_dashscope_native_base("") == DASHSCOPE_NATIVE_BASE
    # 自定义代理原样放行 —— 剥后缀是为了认出那一种已知形状,不是去猜别人的地址。
    assert resolve_dashscope_native_base("https://my-proxy.internal/dashscope") == "https://my-proxy.internal/dashscope"


def test_构造签名要收voice() -> None:
    """build_remote_provider 的兜底分支是 cls(api_key=…, voice=…, model=…, base_url=…),
    少收一个参数就是 TypeError —— 而那条路径只有真去合成时才会走到。"""
    from app.audio.tts_providers import build_remote_provider

    engine = build_remote_provider("alibaba", api_key="k", voice="Serena")
    assert isinstance(engine, BailianTTS)
    assert engine._default_voice == "Serena"


def test_音色跟着模型族走_日期快照沿用() -> None:
    """百炼的音色不是全引擎一份:qwen3-tts-flash 有 qwen-tts 没有的几个(真机验证)。

    键按前缀匹配,所以带日期的快照沿用同族音色 —— 实测 qwen3-tts-flash-2025-11-27 + Ryan、
    qwen-tts-2025-05-22 + Chelsie 都能合成。
    """
    assert "Ryan" in BailianTTS.voices_for("qwen3-tts-flash")
    assert "Ryan" not in BailianTTS.voices_for("qwen-tts")
    assert BailianTTS.voices_for("qwen3-tts-flash-2025-11-27") == BailianTTS.voices_for("qwen3-tts-flash")
    assert BailianTTS.voices_for("qwen-tts-2025-05-22") == BailianTTS.voices_for("qwen-tts")


def test_最长前缀优先_别让带3的那族落到旧表上() -> None:
    """`qwen3-tts-flash` 和 `qwen-tts` 都不是对方的前缀,但顺序一乱就会出这类错 ——
    钉住它,免得以后加 `qwen-tts-pro` 这种键时把匹配顺序改坏。"""
    assert BailianTTS.voices_for("qwen3-tts-flash") != BailianTTS.voices_for("qwen-tts")


def test_认不出的模型回空_由界面退回填id() -> None:
    """模型是开放集合(instruct / vd / vc 变体),而百炼没有列音色的接口。

    回空 → 前端那条 `voiceChoices.length === 0 && needs_voice_id` 分支渲染输入框。
    给一个**猜出来的**下拉比让用户自己填更糟:选项看着像是对的,发出去才知道不存在。
    """
    assert BailianTTS.voices_for("qwen3-tts-vd-2026-01-26") == ()
    # v3-plus / v3.5-* 即使用 _v3 音色也回 418(多半账号未开通);v1 明确说"不支持 http call"。
    from app.audio.tts_providers import CosyVoiceTTS

    for model in ("cosyvoice-v1", "cosyvoice-v3-plus", "cosyvoice-v3.5-flash"):
        assert CosyVoiceTTS.voices_for(model) == (), model


def test_引擎目录声明了要能填音色id() -> None:
    from app.audio.tts_providers import describe_engines

    entry = next(e for e in describe_engines() if e["id"] == "alibaba")
    assert entry["needs_voice_id"] is True, "认不出的模型会得到一个空下拉,而不是输入框"
    assert entry["supports_speed"] is False


# ---------------- CosyVoice:同一个引擎里的第二套 API ----------------


def test_cosyvoice走另一个端点和另一种请求体() -> None:
    """百炼的语音有两套 API,按模型分派 —— 混用会得到 `url error` 或 `task can not be null`。

    · qwen-tts → 多模态生成端点,音色在 input.voice
    · CosyVoice → /api/v1/services/audio/tts/SpeechSynthesizer,音色在 parameters.voice
    """
    from app.audio.tts_providers import SpeechRequest

    qwen_payload, qwen_path = BailianTTS(api_key="k", model="qwen-tts")._request_for(
        SpeechRequest(text="嗨", voice="Cherry")
    )
    assert qwen_path.endswith("/multimodal-generation/generation")
    assert qwen_payload["input"]["voice"] == "Cherry"
    assert "parameters" not in qwen_payload, "qwen-tts 没有 parameters,多塞会被拒"

    cosy_payload, cosy_path = BailianTTS(api_key="k", model="cosyvoice-v2")._request_for(
        SpeechRequest(text="嗨", voice="longwan_v2")
    )
    assert cosy_path.endswith("/audio/tts/SpeechSynthesizer")
    assert cosy_payload["parameters"]["voice"] == "longwan_v2", "CosyVoice 的音色在 parameters 里"
    assert "voice" not in cosy_payload["input"]


def test_语速只发给收得住的那一族() -> None:
    """真机实测:CosyVoice 的 rate=1.5 把 2.25 秒的句子变成 1.50 秒,正好 1.5 倍(真变速)。
    qwen-tts 没有这个参数,发过去只会被拒或忽略。"""
    from app.audio.tts_providers import SpeechRequest

    cosy, _ = BailianTTS(api_key="k", model="cosyvoice-v2")._request_for(SpeechRequest(text="嗨", speed=1.5))
    assert cosy["parameters"]["rate"] == 1.5

    qwen, _ = BailianTTS(api_key="k", model="qwen-tts")._request_for(SpeechRequest(text="嗨", speed=1.5))
    assert "parameters" not in qwen, "把语速发给了收不住它的那一族"


def test_语速是1时不发这个参数() -> None:
    """1.0 是"引擎自然语速"。显式发 1.0 和不发在语义上一样,但少一个字段就少一处能出错的地方。"""
    from app.audio.tts_providers import SpeechRequest

    cosy, _ = BailianTTS(api_key="k", model="cosyvoice-v2")._request_for(SpeechRequest(text="嗨", speed=1.0))
    assert "rate" not in cosy["parameters"]


def test_支持语速这件事按模型判_不是整个引擎() -> None:
    assert BailianTTS.supports_speed_for("cosyvoice-v2") is True
    assert BailianTTS.supports_speed_for("cosyvoice-v3-flash") is True
    assert BailianTTS.supports_speed_for("qwen-tts") is False
    assert BailianTTS.supports_speed_for("qwen3-tts-flash") is False
    assert BailianTTS.supports_speed_for("") is False, "取不到模型时按不支持处理(保守的那一侧)"


def test_cosyvoice音色按主版本分表_跨版本不通用() -> None:
    """id 是 `<名字>_v<主版本>`,把 v2 的 id 发给 v3 会得到 `Engine return error code: 418`。

    两张表逐个真机验证过(2026-08-24),不是照文档抄的 —— v3-flash 比 v2 多出 8 个。
    """
    from app.audio.tts_providers import CosyVoiceTTS

    v2 = CosyVoiceTTS.voices_for("cosyvoice-v2")
    v3 = CosyVoiceTTS.voices_for("cosyvoice-v3-flash")
    assert len(v2) == 14 and len(v3) == 22
    assert all(v.endswith("_v2") for v in v2), f"v2 表里混进了别的版本:{v2}"
    assert all(v.endswith("_v3") for v in v3), f"v3 表里混进了别的版本:{v3}"
    assert not set(v2) & set(v3), "两版的 id 不该有交集"
    # 日期快照沿用同族。
    assert CosyVoiceTTS.voices_for("cosyvoice-v3-flash-2025-09-01") == v3


def test_v3plus不会误配到v3flash的表() -> None:
    """前缀匹配最怕这种:`cosyvoice-v3-plus` 和 `cosyvoice-v3-flash` 前 13 个字符一样。
    误配的话用户会拿到一张看着合法、发出去全是 418 的音色表。"""
    from app.audio.tts_providers import CosyVoiceTTS

    assert CosyVoiceTTS.voices_for("cosyvoice-v3-plus") == ()


def test_播客音色不能显示成原始id() -> None:
    """真机截图抓到的回归:固定音色改从 describe_engines() 出之后,标签丢了 ——
    engine 目录里的 voices 是纯 id,而 (id, 名字) 成对的表在别处。只查 edge 的话,
    播客那四个会显示成 `zh_male_dayixiansheng_v2_saturn_bigtts`。"""
    from app.audio.tts_providers import EDGE_BUILTIN_VOICES, PODCAST_SPEAKERS, VOLCANO_BUILTIN_VOICES

    labels = {**dict(EDGE_BUILTIN_VOICES), **dict(PODCAST_SPEAKERS), **dict(VOLCANO_BUILTIN_VOICES)}
    for voice, expected in PODCAST_SPEAKERS:
        assert labels.get(voice) == expected != voice, f"{voice} 会显示成原始 id"


# ---------------- 两个引擎、一条连接、一把钥匙 ----------------


def test_两个引擎共用同一条连接的凭据() -> None:
    """和火山那两条的差别在**钥匙**:火山 TTS 与播客来自两个控制台、两把 Key,所以是两个
    vendor;百炼这两套共用一把 DashScope Key,拆 vendor 会让用户把同一把钥匙填两遍
    (bytedance 当年就是这么拆的,后来合了)。所以只拆引擎,凭据仍指向 alibaba。"""
    from app.audio.tts_providers import CosyVoiceTTS, vendor_for_engine

    assert vendor_for_engine(CosyVoiceTTS.id) == "alibaba"
    assert vendor_for_engine("alibaba") == "alibaba"
    # 别的引擎照旧:引擎 id 就是 vendor id。
    assert vendor_for_engine("volcano") == "volcano"
    assert vendor_for_engine("openai") == "openai"


def test_模型按族筛_免得把qwen的模型发去cosyvoice() -> None:
    """一条连接下可以同时挂 qwen-tts 和 cosyvoice-v2。不筛的话切到 CosyVoice 引擎会把
    qwen 的模型名发去 CosyVoice 的端点,得到一句看不懂的 `url error`。"""
    from app.audio.tts_providers import BailianTTS as B, CosyVoiceTTS as C

    assert B.MODEL_PREFIXES == ("qwen-tts", "qwen3-tts")
    assert C.MODEL_PREFIXES == ("cosyvoice",)
    # 两族不重叠 —— 重叠的话筛选就形同虚设。
    for prefix in C.MODEL_PREFIXES:
        assert not prefix.startswith(B.MODEL_PREFIXES)


def test_两个引擎各自的音色和语速() -> None:
    """面板上显示什么,不该取决于用户在这条连接下当前恰好配了哪个模型 —— 这正是分开列的理由。"""
    from app.audio.tts_providers import CosyVoiceTTS, describe_engines

    entries = {e["id"]: e for e in describe_engines()}
    assert entries["alibaba"]["supports_speed"] is False
    assert entries[CosyVoiceTTS.id]["supports_speed"] is True
    # 音色两边完全不同,混用会被拒。
    assert not set(entries["alibaba"]["voices"]) & set(entries[CosyVoiceTTS.id]["voices"])


def test_cosyvoice引擎默认就是能用的模型() -> None:
    """这条连接还没配任何 cosyvoice 模型时,引擎也该能跑 —— 回落到 DEFAULT_MODEL,
    而不是把空模型名发出去。"""
    from app.audio.tts_providers import CosyVoiceTTS

    assert CosyVoiceTTS(api_key="k")._model == "cosyvoice-v2"
    assert CosyVoiceTTS.voices_for(CosyVoiceTTS.DEFAULT_MODEL), "默认模型没有音色"
