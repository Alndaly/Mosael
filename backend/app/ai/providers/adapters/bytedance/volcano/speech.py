"""火山引擎的大模型 TTS。"""

from __future__ import annotations

import base64
import json
import uuid
from pathlib import Path

import httpx

from app.core.http_retry import RetryingClient

from app.ai.providers.contracts.speech import SPEECH_REQUEST_TIMEOUT_SECONDS, SpeechSynthesisRequest, SpeechSynthesisError


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

    def __init__(self, api_key: str, voice: str = "", model: str = "", base_url: str = "") -> None:
        if not api_key:
            raise SpeechSynthesisError("火山引擎语音合成需要新版控制台的 API Key")
        self._key = api_key
        self._model = model
        self._base = (base_url or "https://openspeech.bytedance.com").rstrip("/")
        self._default_voice = voice

    def _resource_id(self, voice: str) -> str:
        """The voice family, which the header must agree with. An explicit seed-* model wins."""
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
            raise SpeechSynthesisError("火山引擎语音合成需要音色 id(如 zh_male_..._bigtts)")
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
            "X-Api-Resource-Id": self._resource_id(voice),
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
                                f"火山 TTS 失败: code={code} {frame.get('message') or ''}".strip()
                            )
                        data = frame.get("data")
                        if data:
                            chunks.append(base64.b64decode(data))
        except httpx.HTTPError as exc:
            raise SpeechSynthesisError(f"火山 TTS 请求失败: {exc}") from exc
        if not chunks:
            raise SpeechSynthesisError("火山 TTS 返回空音频")
        out_path.write_bytes(b"".join(chunks))


#: The voices to offer when the account's AK/SK are not configured, so synthesis is usable
#: without them. Deliberately excludes the emo_v2 multi-emotion voices: their resource family
#: cannot be inferred from the id, and guessing produces an opaque 55000000 at synthesis time.
VOLCANO_BUILTIN_VOICES: tuple[tuple[str, str], ...] = (
    ("zh_female_cancan_mars_bigtts", "灿灿(女·活泼)"),
    ("zh_female_shuangkuaisisi_moon_bigtts", "爽快思思(女)"),
    ("zh_female_vv_uranus_bigtts", "Vivi 薇薇(女·2.0)"),
    ("zh_female_wanwanxiaohe_moon_bigtts", "湾湾小何(女·台腔)"),
    ("zh_female_xiaomei_mars_bigtts", "小美(女)"),
    ("zh_female_qingxinnvsheng_mars_bigtts", "清新女声(女)"),
    ("zh_female_zhixingnvsheng_mars_bigtts", "知性女声(女)"),
    ("zh_male_liufei_uranus_bigtts", "刘飞(男·2.0)"),
    ("zh_male_m191_uranus_bigtts", "云舟(男·2.0)"),
    ("zh_male_wennuanahu_moon_bigtts", "温暖阿虎(男)"),
    ("zh_male_shaonianzixin_moon_bigtts", "少年梓辛(男)"),
    ("zh_male_jingqiangkanye_moon_bigtts", "京腔侃爷(男·北京)"),
    ("zh_male_yangguangqingnian_moon_bigtts", "阳光青年(男)"),
    ("zh_male_sunwukong_mars_bigtts", "孙悟空(角色)"),
    ("en_female_anna_mars_bigtts", "Anna(英·女)"),
    ("en_male_adam_mars_bigtts", "Adam(英·男)"),
)

#: 播客 voices. These only work on the podcast WebSocket, not the v3 single-voice endpoint,
#: and read best paired within a series (大义+咪仔 / 刘飞+潇磊).
PODCAST_SPEAKERS: tuple[tuple[str, str], ...] = (
    ("zh_male_dayixiansheng_v2_saturn_bigtts", "大义(男)"),
    ("zh_female_mizaitongxue_v2_saturn_bigtts", "咪仔(女)"),
    ("zh_male_liufei_v2_saturn_bigtts", "刘飞(男)"),
    ("zh_male_xiaolei_v2_saturn_bigtts", "潇磊(男)"),
)


#: Engines a user can pick, in the order the UI offers them. "clone" is handled separately —
#: it is the local reference-driven path and needs a Voice row, not an engine voice id.
