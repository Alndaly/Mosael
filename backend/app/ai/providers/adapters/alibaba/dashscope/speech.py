"""阿里云百炼:qwen-tts 与 CosyVoice —— 同一把 Key 下的两套 API。"""

from __future__ import annotations

from pathlib import Path

import httpx

from app.core.http_retry import RetryingClient

from app.ai.providers.contracts.speech import SPEECH_REQUEST_TIMEOUT_SECONDS, SpeechSynthesisRequest, SpeechSynthesisError


class BailianSpeechAdapter:
    """阿里云百炼(DashScope)的 qwen-tts。

    走的是多模态生成端点,**同步返回一个音频地址**,再下载 —— 不是异步任务,所以这里没有轮询
    (同一家的视频生成才需要,见 ``adapters/alibaba/dashscope/video.py``)。

    **speed 这一档它不接**。百炼的 qwen-tts 没有语速参数,而配音要的正是"把一句话塞进原来那段
    时长里"。这不影响功能:时间线在渲染时用 atempo 变速兜底(见 README 里「缩放到段落长度」)。
    但引擎自己念得快慢更自然,所以需要精确控时的配音,选 openai / volcano / 本地克隆更合适 ——
    这句话写进 note 里给用户看,而不是让他试完才发现。

    音色是模型自带的固定几个(不像火山那样按账号变),所以直接列在这儿,不用另开一个拉取接口。

    真机验证(2026-08-24):四个音色各合成一句,均返回 24kHz 单声道 16bit PCM 的 WAV。
    """

    engine_id = "alibaba"
    label_key = "ttsProvider_bailian"
    supports_parallel_synthesis = True
    #: 这一支只认 qwen-tts 家族。CosyVoice 是同一把 Key 下的**另一套 API**,单独一个引擎
    #: (见 CosyVoiceSpeechAdapter)—— 端点、请求体、音色、支不支持语速全都不一样,合成一条会让面板
    #: 上的音色和语速跟着"当前恰好配了哪个模型"无声地变。
    MODEL_PREFIXES = ("qwen-tts", "qwen3-tts")
    DEFAULT_MODEL = "qwen-tts"
    #: CosyVoice 走**另一个端点**,请求体也不同 —— 见 _request_for。
    COSYVOICE_PATH = "/api/v1/services/audio/tts/SpeechSynthesizer"
    #: 音色**按模型族**给,不是全引擎一份 —— 真机验证过 qwen3-tts-flash 有 qwen-tts 没有的
    #: 音色(Ryan/Katerina/Elias)。键按前缀匹配:带日期的快照沿用同族音色
    #: (实测 qwen3-tts-flash-2025-11-27 + Ryan、qwen-tts-2025-05-22 + Chelsie 都通)。
    #:
    #: **这几张表是"已知可用",不是"全部"。** 百炼的 TTS 模型是开放集合(还有 instruct /
    #: vd / vc 变体和一串日期快照),而它没有列音色的接口 —— 穷举只会得到一张很快过期的表。
    #: 所以列不出来的模型退回让用户填音色 id(needs_voice_id),而不是给他一个空下拉。
    VOICES_BY_MODEL = {
        # 四个都真机验证过(2026-08-24,各合成一句均返回可播放 WAV)。
        "qwen-tts": ("Cherry", "Serena", "Ethan", "Chelsie"),
        "qwen3-tts-flash": ("Cherry", "Serena", "Ethan", "Chelsie", "Ryan", "Katerina", "Elias"),
        # CosyVoice 的音色 id 是 `<名字>_v<主版本>`,**跨版本不通用**(v2 的 id 发给 v3 会得到
        # `Engine return error code: 418`)。下面两张表逐个真机验证过(2026-08-24),
        # 没有一个是照文档抄的:v3-flash 比 v2 多出 8 个,少了 longyue 之外的几个也确实探不通。
        "cosyvoice-v2": (
            "longxiaochun_v2", "longwan_v2", "longcheng_v2", "longhua_v2", "longshu_v2",
            "longjielidou_v2", "longxiaoxia_v2", "longshuo_v2", "loongtomoka_v2", "loongdavid_v2",
            "longshao_v2", "longyan_v2", "longyuan_v2", "longyue_v2",
        ),
        "cosyvoice-v3-flash": (
            "longxiaochun_v3", "longwan_v3", "longcheng_v3", "longhua_v3", "longshu_v3",
            "longdaiyu_v3", "longhuhu_v3", "longjielidou_v3", "longanxuan_v3", "longxiaoxia_v3",
            "longyingtao_v3", "longshuo_v3", "longanli_v3", "loongtomoka_v3", "longsanshu_v3",
            "loongdavid_v3", "longwanjun_v3", "longyan_v3", "longyuan_v3", "longyingxiao_v3",
            "longyue_v3", "longyichen_v3",
        ),
        # 探过但**接不进来**的,记在这儿省得下次再试一遍:
        #   cosyvoice-v1      → "current user api does not support http call"(它是 WebSocket-only)
        #   cosyvoice-v3-plus / v3.5-plus / v3.5-flash → 即使用 _v3 音色也回 418,多半是账号未开通
        # 这几个落到"认不出"分支,由用户自己填音色 id —— 而不是给一张猜出来的表。
    }

    #: 支持语速的模型族。CosyVoice 收 `rate`(实测真变速);qwen-tts 家族没有这个参数。
    SPEED_PREFIXES = ("cosyvoice",)

    @classmethod
    def supports_speed_for(cls, model: str) -> bool:
        return (model or "").strip().lower().startswith(cls.SPEED_PREFIXES)
    #: 取不到模型时的兜底:两族的交集,哪个模型都认。
    VOICES = ("Cherry", "Serena", "Ethan", "Chelsie")

    @classmethod
    def voices_for(cls, model: str) -> tuple[str, ...]:
        """这个模型能用哪些音色。认不出来就回空 —— 由调用方退回"自己填 id"。"""
        name = (model or "").strip()
        if not name:
            return cls.VOICES
        # 最长前缀优先:qwen3-tts-flash 要先于 qwen-tts 命中,否则带 3 的那族会落到旧表上。
        for prefix in sorted(cls.VOICES_BY_MODEL, key=len, reverse=True):
            if name.startswith(prefix):
                return cls.VOICES_BY_MODEL[prefix]
        return ()
    PATH = "/api/v1/services/aigc/multimodal-generation/generation"

    # 签名要收 `voice`:build_speech_adapter 的兜底分支是
    # `cls(api_key=…, voice=…, model=…, base_url=…)`,少一个参数就是 TypeError。
    def __init__(self, api_key: str, voice: str = "", model: str = "", base_url: str = "") -> None:
        if not api_key:
            raise SpeechSynthesisError("百炼语音合成需要 DashScope API Key,请在设置里配置")
        self._key = api_key
        self._model = model or "qwen-tts"
        self._base = resolve_dashscope_native_base(base_url)
        self._default_voice = voice

    def _request_for(self, request: SpeechSynthesisRequest) -> tuple[dict, str]:
        """百炼的语音有**两套 API**,按模型分派。

        · qwen-tts 家族 → 多模态生成端点,音色在 `input.voice`,**没有语速参数**;
        · CosyVoice   → `/api/v1/services/audio/tts/SpeechSynthesizer`,音色在
          `parameters.voice`,而且**支持语速**(实测 rate=1.5 把 2.25 秒的句子变成 1.50 秒,
          正好 1.5 倍 —— 是真变速,不是被忽略)。

        两套的回包形状一样(`output.audio.url`),所以只有请求这一半要分。
        """
        voice = request.voice or self._default_voice
        if is_cosyvoice(self._model):
            parameters: dict = {"voice": voice or "longxiaochun_v2", "format": "wav", "sample_rate": 22050}
            if abs(request.speed - 1.0) > 0.01:
                # 配音要的正是"塞进原时长" —— 引擎自己变速比事后拉伸波形自然。
                parameters["rate"] = max(0.5, min(2.0, request.speed))
            return {"model": self._model, "input": {"text": request.text}, "parameters": parameters}, self.COSYVOICE_PATH
        return (
            {"model": self._model, "input": {"text": request.text, "voice": voice or self.VOICES[0]}},
            self.PATH,
        )

    def synthesize(self, request: SpeechSynthesisRequest, out_path: Path) -> None:
        payload, path = self._request_for(request)
        try:
            with RetryingClient(timeout=SPEECH_REQUEST_TIMEOUT_SECONDS) as client:
                response = client.post(
                    f"{self._base}{path}",
                    headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                    json=payload,
                )
                response.raise_for_status()
            url = extract_bailian_audio_url(response.json())
            if not url:
                raise SpeechSynthesisError("百炼语音合成没有返回音频地址")
            # 结果是一个预签名 OSS 地址。**另起一个干净的 client** —— 带上 Authorization 会让
            # OSS 的签名校验走另一条分支(与 image/qwen.py 里那条注释同一个坑)。
            with RetryingClient(timeout=SPEECH_REQUEST_TIMEOUT_SECONDS) as fetcher:
                audio = fetcher.get(url)
                audio.raise_for_status()
        except httpx.HTTPError as exc:
            raise SpeechSynthesisError(f"百炼语音合成失败: {exc}") from exc
        out_path.write_bytes(audio.content)


#: 百炼原生 API 的根。语音走的是它,不是对话那个 compatible-mode。
DASHSCOPE_NATIVE_BASE = "https://dashscope.aliyuncs.com"


def resolve_dashscope_native_base(base_url: str) -> str:
    """把档案里的 base_url 归一到**原生** API 根。

    同一个百炼档案的 base_url 往往填的是对话用的
    `https://dashscope.aliyuncs.com/compatible-mode/v1` —— 那是 OpenAI 兼容端点。语音走的是
    原生路径 `/api/v1/services/aigc/...`,直接往后拼会得到
    `…/compatible-mode/v1/api/v1/services/…`,一个必然 404 的地址。

    同一个坑图像那边已经踩过并解决(见同目录 ``image.resolve_qwen_edit_base``),
    这里用同一条判据:认得出 compatible-mode 就剥掉它,自定义代理原样放行。
    """
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return DASHSCOPE_NATIVE_BASE
    if base.endswith("/compatible-mode/v1"):
        return base.removesuffix("/compatible-mode/v1")
    return base


def is_cosyvoice(model: str) -> bool:
    return (model or "").strip().lower().startswith("cosyvoice")


def extract_bailian_audio_url(payload: dict) -> str:
    """从 qwen-tts 的回包里取音频地址。

    单独成函数是为了能被纯 payload 测试盯住:这个适配器真正容易错的就是这一步(回包是
    `output.audio.url`,而同家的图像走的是 `output.results[].url`),而它在真跑一次之前
    看不出来。
    """
    output = payload.get("output") or {}
    audio = output.get("audio")
    if isinstance(audio, dict) and audio.get("url"):
        return str(audio["url"])
    # 少数模型把音频放进 choices 的 content 数组里,与 qwen-image 的编辑模式同形。
    for choice in output.get("choices") or []:
        message = choice.get("message") if isinstance(choice, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("audio"), dict) and item["audio"].get("url"):
                    return str(item["audio"]["url"])
    return ""


class CosyVoiceSpeechAdapter(BailianSpeechAdapter):
    """百炼的 CosyVoice。**和 qwen-tts 同一把 Key,但是另一套 API。**

    单独成一个引擎而不是塞进 BailianSpeechAdapter 里选模型 —— 理由和火山把 TTS 与播客分开一样:
    面板上要显示的东西不同(CosyVoice 有语速、音色 id 完全不同),而"显示什么"不该取决于
    用户当前恰好在这条连接下配了哪个模型。

    与火山那两条的差别是**钥匙**:火山的 TTS 和播客来自两个控制台、发两把不同的 Key,所以
    它们是两个 vendor;百炼这两套共用一把 DashScope Key,拆 vendor 会让用户把同一把钥匙填
    两遍(bytedance 当年就是这么拆的,后来合了)。所以只拆**引擎**,凭据仍指向 alibaba ——
    见 connection_vendor_for_speech_engine。
    """

    engine_id = "alibaba-cosyvoice"
    label_key = "ttsProvider_cosyvoice"
    MODEL_PREFIXES = ("cosyvoice",)
    DEFAULT_MODEL = "cosyvoice-v2"

    def __init__(self, api_key: str, voice: str = "", model: str = "", base_url: str = "") -> None:
        super().__init__(api_key=api_key, voice=voice, model=model or self.DEFAULT_MODEL, base_url=base_url)


#: 引擎 id → 取凭据时用的 vendor。**默认是它自己**(约定见 OpenAISpeechAdapter.engine_id 上面那段);
#: 只有百炼这一处例外:两个引擎共用一条连接、一把 Key。
