"""火山引擎的大模型 TTS。"""

from __future__ import annotations

import base64
import json
import uuid
from pathlib import Path

import httpx

from app.core.http_retry import RetryingClient

from app.ai.providers.adapters.bytedance.volcano.speakers import VolcOpenAPIError, list_all_speakers
from app.ai.providers.contracts.speech import (
    SPEECH_REQUEST_TIMEOUT_SECONDS,
    SpeechCatalogError,
    SpeechSynthesisError,
    SpeechSynthesisRequest,
    VoiceCatalogContext,
    VoiceOption,
)


class VolcanoSpeechAdapter:
    """火山引擎(豆包)大模型语音合成 — the v3 synchronous endpoint.

    Best Chinese voices of the engines here, at the cost of a fiddlier contract than OpenAI's:

    * X-Api-Resource-Id must match the voice's family or the call fails with code 55000000, and
      the family is only discoverable from the voice id itself — see _resource_id.
    * The response is a chunked stream of JSON lines, each carrying a base64 audio fragment;
      code 20000000 is the end-of-stream marker, not an error.
    * Speed is `speech_rate`, an int in [-50, 100] where 0 is natural — not a multiplier. The
      linear map below is what makes SpeechSynthesisRequest.speed mean the same thing across engines,
      which is what dubbing depends on.
    """

    engine_id = "volcano"
    label_key = "ttsProvider_volcano"
    supports_parallel_synthesis = True
    free_of_charge = False
    needs_key = True
    supports_speed = True
    #: 音色清单随账号变,但总是一张清单:现拉的(配了 AK/SK)或内置的,面板给下拉而不是让人填一串看不懂的 id。
    needs_voice_id = False
    note_key = "ttsProviderNote_volcano"

    @classmethod
    def voices(cls, context: VoiceCatalogContext) -> list[VoiceOption]:
        """配了 AK/SK 就按账号现拉(OpenAPI,ak/sk 在连接的附加字段里),没配或账号里一个都没有就给内置那张表。

        现拉的每一项把资源族放进 `extra["resource_id"]`:合成时请求头要和它对上,而只有这份清单知道它
        (见 `_resource_id`)。拉失败抛 `SpeechCatalogError`,由调用方退回内置清单。
        """
        extra = context.connection_extra
        ak, sk = str(extra.get("ak") or ""), str(extra.get("sk") or "")
        if not (ak and sk):
            return list(VOLCANO_BUILTIN_VOICES)
        try:
            live = list_all_speakers(ak, sk)
        except VolcOpenAPIError as exc:
            raise SpeechCatalogError("speechErr_accountVoicesUnavailable", detail=str(exc)) from exc
        account = [
            VoiceOption(
                speaker["VoiceType"], speaker.get("Name") or speaker["VoiceType"], source="account",
                languages=_languages_of(speaker["VoiceType"]),
                extra={"resource_id": speaker.get("ResourceID", "")} if speaker.get("ResourceID") else {},
            )
            for speaker in live
            if speaker.get("VoiceType")
        ]
        return account or list(VOLCANO_BUILTIN_VOICES)

    def __init__(self, api_key: str, voice: str = "", model: str = "", base_url: str = "") -> None:
        if not api_key:
            raise SpeechSynthesisError("providerErr_volcanoTtsKeyMissing")
        self._key = api_key
        self._model = model
        self._base = (base_url or "https://openspeech.bytedance.com").rstrip("/")
        self._default_voice = voice

    def _resource_id(self, request: SpeechSynthesisRequest, voice: str) -> str:
        """The voice family, which the header must agree with.

        The account voice list knows it and puts it in `VoiceOption.extra["resource_id"]`; the voice choice carries that
        back here (`request.extra`, ADR 0087). An explicit seed-* model is next; the built-in voices are inferred from the id.
        """
        if request.extra.get("resource_id"):
            return request.extra["resource_id"]
        if self._model.startswith("seed-"):
            return self._model
        if voice.startswith("S_"):
            return "seed-icl-2.0"  # 复刻音色
        if "_uranus_" in voice or voice.startswith("saturn_"):
            return "seed-tts-2.0"
        return "seed-tts-1.0"

    def synthesize(self, request: SpeechSynthesisRequest, out_path: Path) -> None:
        voice = request.voice or self._default_voice
        if not voice:
            raise SpeechSynthesisError("providerErr_volcanoTtsVoiceMissing", example="zh_male_..._bigtts")
        speed = max(0.2, min(3.0, request.speed))
        payload = {
            "req_params": {
                "text": request.text,
                "speaker": voice,
                "audio_params": {
                    "format": "mp3",
                    "sample_rate": 24000,
                    "speech_rate": max(-50, min(100, round((speed - 1.0) * 100))),
                },
            }
        }
        headers = {
            "X-Api-Key": self._key,
            "X-Api-Resource-Id": self._resource_id(request, voice),
            "X-Api-Request-Id": uuid.uuid4().hex,
            "Content-Type": "application/json",
        }
        chunks: list[bytes] = []
        try:
            with RetryingClient(timeout=SPEECH_REQUEST_TIMEOUT_SECONDS) as client:
                with client.stream(
                    "POST", f"{self._base}/api/v3/tts/unidirectional", headers=headers, json=payload
                ) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        line = (line or "").strip()
                        if not line:
                            continue
                        try:
                            frame = json.loads(line)
                        except ValueError:
                            continue  # heartbeat / separator, not a frame
                        code = int(frame.get("code", 0))
                        if code == 20000000:  # documented end-of-stream, not a failure
                            break
                        if code != 0:
                            raise SpeechSynthesisError(
                                "providerErr_volcanoTtsFailed",
                                detail=f"code={code} {frame.get('message') or ''}".strip(),
                            )
                        data = frame.get("data")
                        if data:
                            chunks.append(base64.b64decode(data))
        except httpx.HTTPError as exc:
            raise SpeechSynthesisError("providerErr_volcanoTtsRequestFailed", detail=str(exc)) from exc
        if not chunks:
            raise SpeechSynthesisError("providerErr_volcanoTtsEmptyAudio")
        out_path.write_bytes(b"".join(chunks))


def probe_connection(profile) -> str:
    """健康探针:往合成端点发一次最小请求,只看钥匙收不收(空文本,服务在鉴权那一步就回话,
    不产生音频、不计费)。

    回 "ok"(钥匙被收下)/ "credential_rejected"(401/403);网络层的失败上抛,由 health 记成离线。
    实测(2026-10):错的 X-Api-Key 回来的是 401 + code 45000010 "Invalid X-Api-Key"。
    """
    url = f"{(profile.base_url or 'https://openspeech.bytedance.com').rstrip('/')}/api/v3/tts/unidirectional"
    headers = {
        "X-Api-Key": profile.api_key,
        "X-Api-Resource-Id": "seed-tts-2.0",
        "X-Api-Request-Id": uuid.uuid4().hex,
        "Content-Type": "application/json",
    }
    body = {"req_params": {"text": "", "speaker": "zh_female_vv_uranus_bigtts", "audio_params": {"format": "mp3"}}}
    with RetryingClient(timeout=6, max_retries=0) as client:
        response = client.post(url, headers=headers, json=body)
    return "credential_rejected" if response.status_code in (401, 403) else "ok"


#: 火山音色 id 的命名约定:以语言开头(`zh_female_…`、`en_male_…`、`ja_…`)。这是火山自己的规则,所以由这里
#: 翻成目录上的语言;白名单而不是「任意两个字母」—— 账号里自建的 `my_voice_42` 不该被认成某种语言。
_ID_LANGUAGES = frozenset({"zh", "en", "ja", "ko", "es", "fr", "de", "ru", "pt", "it", "ar", "hi", "th", "vi", "id"})


def _languages_of(voice_type: str) -> tuple[str, ...]:
    head = voice_type.split("_", 1)[0]
    return (head,) if "_" in voice_type and head in _ID_LANGUAGES else ()


#: The voices to offer when the account's AK/SK are not configured, so synthesis is usable
#: without them. Deliberately excludes the emo_v2 multi-emotion voices: their resource family
#: cannot be inferred from the id, and guessing produces an opaque 55000000 at synthesis time.
VOLCANO_BUILTIN_VOICES: tuple[VoiceOption, ...] = (
    VoiceOption("zh_female_cancan_mars_bigtts", "灿灿(女·活泼)", languages=("zh",), gender="female"),
    VoiceOption("zh_female_shuangkuaisisi_moon_bigtts", "爽快思思(女)", languages=("zh",), gender="female"),
    VoiceOption("zh_female_vv_uranus_bigtts", "Vivi 薇薇(女·2.0)", languages=("zh",), gender="female"),
    VoiceOption("zh_female_wanwanxiaohe_moon_bigtts", "湾湾小何(女·台腔)", languages=("zh",), gender="female"),
    VoiceOption("zh_female_xiaomei_mars_bigtts", "小美(女)", languages=("zh",), gender="female"),
    VoiceOption("zh_female_qingxinnvsheng_mars_bigtts", "清新女声(女)", languages=("zh",), gender="female"),
    VoiceOption("zh_female_zhixingnvsheng_mars_bigtts", "知性女声(女)", languages=("zh",), gender="female"),
    VoiceOption("zh_male_liufei_uranus_bigtts", "刘飞(男·2.0)", languages=("zh",), gender="male"),
    VoiceOption("zh_male_m191_uranus_bigtts", "云舟(男·2.0)", languages=("zh",), gender="male"),
    VoiceOption("zh_male_wennuanahu_moon_bigtts", "温暖阿虎(男)", languages=("zh",), gender="male"),
    VoiceOption("zh_male_shaonianzixin_moon_bigtts", "少年梓辛(男)", languages=("zh",), gender="male"),
    VoiceOption("zh_male_jingqiangkanye_moon_bigtts", "京腔侃爷(男·北京)", languages=("zh",), gender="male"),
    VoiceOption("zh_male_yangguangqingnian_moon_bigtts", "阳光青年(男)", languages=("zh",), gender="male"),
    VoiceOption("zh_male_sunwukong_mars_bigtts", "孙悟空(角色)", languages=("zh",), gender="male"),
    VoiceOption("en_female_anna_mars_bigtts", "Anna(英·女)", languages=("en",), gender="female"),
    VoiceOption("en_male_adam_mars_bigtts", "Adam(英·男)", languages=("en",), gender="male"),
)

#: 播客 voices. These only work on the podcast WebSocket, not the v3 single-voice endpoint,
#: and read best paired within a series (大义+咪仔 / 刘飞+潇磊).
PODCAST_SPEAKERS: tuple[VoiceOption, ...] = (
    VoiceOption("zh_male_dayixiansheng_v2_saturn_bigtts", "大义(男)", languages=("zh",), gender="male"),
    VoiceOption("zh_female_mizaitongxue_v2_saturn_bigtts", "咪仔(女)", languages=("zh",), gender="female"),
    VoiceOption("zh_male_liufei_v2_saturn_bigtts", "刘飞(男)", languages=("zh",), gender="male"),
    VoiceOption("zh_male_xiaolei_v2_saturn_bigtts", "潇磊(男)", languages=("zh",), gender="male"),
)


#: Engines a user can pick, in the order the UI offers them. "clone" is handled separately —
#: it is the local reference-driven path and needs a Voice row, not an engine voice id.
