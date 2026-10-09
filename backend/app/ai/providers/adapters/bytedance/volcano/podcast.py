"""火山引擎播客 Adapter — two voices reading a dialogue, over a WebSocket.

This is a different product from the v3 speech endpoint, not a mode of it, and the difference
that bites first is the credential: the podcast socket authenticates with an appid and an
access token from the speech console and rejects the v3 API Key outright. Mixing the two is
the single most common way to get an unexplained handshake failure, which is why they remain
separate persisted vendor ids — see the ProviderDefinition registry.

The flow is a state machine, not a request: start the connection, wait for it to be accepted,
start a session carrying the whole job description, then read frames until the server says the
podcast ended. Audio arrives as a series of AudioOnlyServer frames and the dialogue text as
PodcastRoundResponse frames, so both are accumulated as they stream rather than returned at
the end.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app.core.i18n import LocalizedError
from app.ai.providers.adapters.bytedance.volcano.podcast_protocol import EventType, PodcastProtocolMessage, MessageType, MessageFlags, parse_message

logger = logging.getLogger(__name__)

ENDPOINT = "wss://openspeech.bytedance.com/api/v3/sami/podcasttts"
#: Fixed values the podcast API requires; they identify the product, not the account.
APP_KEY = "aGjiRDfUWi"
RESOURCE_ID = "volc.service_type.10050"

HANDSHAKE_TIMEOUT = 30
#: Generous because a round is a model call, not a lookup.
FRAME_TIMEOUT = 180
#: A hard stop on cost. A runaway job is billed per round, so this is a budget, not a limit
#: on what is reasonable to ask for.
MAX_ROUNDS = 60
MAX_ROUND_CHARS = 280


class PodcastSynthesisError(LocalizedError, RuntimeError):
    """Raised when the podcast cannot be produced, carrying 火山's message where there is one.

    带文案 key(`providerErr_podcast*`,见 core/i18n),按读的人的语言翻;火山回的原话放进 `detail`。"""


class PodcastAction:
    """What the server should do with the text it is given."""

    #: Summarise input_text into a dialogue. Requires exactly two speakers.
    SUMMARIZE = 0
    #: Read nlp_texts verbatim; the speaker follows the text, not speaker_info.
    READ = 3
    #: Research prompt_text on the web, then discuss it. Requires exactly two speakers.
    RESEARCH = 4


@dataclass
class PodcastSynthesisResult:
    audio: bytes = b""
    #: One entry per spoken turn: {"speaker": ..., "text": ...}. This is what becomes the
    #: transcript, and for SUMMARIZE it is the only place the generated dialogue exists.
    texts: list[dict] = field(default_factory=list)


def split_to_rounds(text: str, *, dual: bool) -> list[str]:
    """Chop a plain text into rounds for READ (callers that have prose, not a script — the agent's
    `generate_podcast` reading a passage; the script editor sends its own rounds).

    With two speakers a round is one sentence, so the voices actually alternate; packing
    several sentences into a round would have one speaker read a paragraph and the other
    answer once. With a single speaker there is nothing to alternate, so rounds are packed to
    MAX_ROUND_CHARS to keep the round count (and the bill) down.
    """
    sentences = [part.strip() for part in re.split(r"(?<=[。!?!?\n])", text) if part.strip()]
    if not sentences:
        return []
    if dual:
        return sentences[:MAX_ROUNDS]

    rounds: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > MAX_ROUND_CHARS:
            rounds.append(current)
            current = sentence
        else:
            current += sentence
    if current:
        rounds.append(current)
    return rounds[:MAX_ROUNDS]


def _session_payload(
    *,
    action: int,
    input_text: str,
    prompt_text: str,
    nlp_texts: list[dict] | None,
    speakers: list[str],
    speech_rate: int,
    audio_format: str,
) -> dict:
    params: dict = {
        # 调用方自取的请求标识(火山不校验其内容);改名一并跟上。
        "input_id": "mosael",
        "action": int(action),
        "input_text": input_text or "",
        "prompt_text": prompt_text or "",
        "nlp_texts": nlp_texts or None,
        "use_head_music": False,
        "use_tail_music": False,
        "audio_config": {"format": audio_format, "sample_rate": 24000, "speech_rate": int(speech_rate)},
    }
    # speaker_info only applies to the AI-generated modes; in READ mode the speaker rides
    # along with each nlp_text, and sending speaker_info there is rejected.
    if action in (PodcastAction.SUMMARIZE, PodcastAction.RESEARCH):
        params["speaker_info"] = {"random_order": False, "speakers": list(speakers)}
    return {"req_params": params}


def _control(event: int, payload: bytes, session_id: str = "") -> bytes:
    message = PodcastProtocolMessage(MessageType.FullClientRequest, MessageFlags.WithEvent)
    message.event = event
    message.session_id = session_id
    message.payload = payload
    return message.to_bytes()


async def _run(
    appid: str,
    token: str,
    payload: dict,
    *,
    endpoint: str,
    proxy: str,
) -> PodcastSynthesisResult:
    import websockets

    headers = {
        "X-Api-App-Id": appid,
        "X-Api-App-Key": APP_KEY,
        "X-Api-Access-Key": token,
        "X-Api-Resource-Id": RESOURCE_ID,
        "X-Api-Connect-Id": uuid.uuid4().hex,
    }
    result = PodcastSynthesisResult()
    session_id = uuid.uuid4().hex

    async with websockets.connect(endpoint, additional_headers=headers, max_size=None, proxy=proxy) as socket:
        await socket.send(_control(EventType.StartConnection, b"{}"))
        started = parse_message(await asyncio.wait_for(socket.recv(), HANDSHAKE_TIMEOUT))
        if started.event != EventType.ConnectionStarted:
            raise PodcastSynthesisError(
                "providerErr_podcastConnectRejected", detail=started.payload.decode('utf-8', 'replace')[:200]
            )

        await socket.send(
            _control(EventType.StartSession, json.dumps(payload).encode("utf-8"), session_id)
        )
        session = parse_message(await asyncio.wait_for(socket.recv(), HANDSHAKE_TIMEOUT))
        if session.event != EventType.SessionStarted:
            raise PodcastSynthesisError(
                "providerErr_podcastSessionStartFailed", detail=session.payload.decode('utf-8', 'replace')[:200]
            )

        await socket.send(_control(EventType.FinishSession, b"{}", session_id))

        while True:
            frame = parse_message(await asyncio.wait_for(socket.recv(), FRAME_TIMEOUT))
            if frame.type == MessageType.Error:
                raise PodcastSynthesisError(
                    "providerErr_podcastFailed",
                    code=frame.error_code,
                    detail=frame.payload.decode("utf-8", "replace")[:200],
                )
            if frame.type == MessageType.AudioOnlyServer:
                result.audio += frame.payload
            elif frame.event == EventType.PodcastRoundResponse:
                try:
                    round_payload = json.loads(frame.payload.decode("utf-8"))
                except ValueError:
                    round_payload = {}
                text = round_payload.get("text") or round_payload.get("nlp_text") or ""
                if text:
                    result.texts.append({"speaker": round_payload.get("speaker", ""), "text": text})
            if frame.event in (EventType.PodcastEnd, EventType.SessionFinished):
                break
            if frame.event == EventType.SessionFailed:
                raise PodcastSynthesisError(
                    "providerErr_podcastSessionFailed", detail=frame.payload.decode('utf-8', 'replace')[:200]
                )

        try:
            await socket.send(_control(EventType.FinishConnection, b"{}"))
        except Exception:  # noqa: BLE001
            # A courtesy goodbye. The podcast is already complete in `result`, so a server
            # that hung up first must not cost us the audio we just received.
            logger.debug("podcast FinishConnection not delivered", exc_info=True)

    if not result.audio:
        raise PodcastSynthesisError("providerErr_podcastEmptyAudio")
    return result


def probe_connection(profile) -> str:
    """健康探针:只握手,连上即断 —— 不发合成请求,不产生音频、不计费。

    回 "ok"(握手成了,或服务回了别的 HTTP 错但确实活着)/ "credential_rejected"(401/403);
    网络层的失败上抛,由 health 记成离线。合成同一条路:经出站守卫的代理连过去。
    """
    import websockets

    from app.core.outbound_guard import Origin
    from app.core.outbound_proxy import ticket

    headers = {
        "X-Api-App-Id": str(profile.extra.get("appid") or ""),
        "X-Api-App-Key": APP_KEY,
        "X-Api-Access-Key": profile.api_key,
        "X-Api-Resource-Id": RESOURCE_ID,
        "X-Api-Connect-Id": uuid.uuid4().hex,
    }

    async def _once(proxy: str) -> str:
        try:
            async with websockets.connect(ENDPOINT, additional_headers=headers, max_size=None, proxy=proxy, open_timeout=6):
                return "ok"
        except websockets.exceptions.InvalidStatus as exc:
            # 握手被 HTTP 拒:401/403 是钥匙的事;别的状态(400/426 等)说明端点活着。
            return "credential_rejected" if exc.response.status_code in (401, 403) else "ok"

    with ticket(Origin.CONFIGURED) as issued:
        return asyncio.run(_once(issued.url))


def synthesize_volcano_podcast(
    appid: str,
    token: str,
    *,
    action: int = PodcastAction.SUMMARIZE,
    input_text: str = "",
    prompt_text: str = "",
    turns: list[dict] | None = None,
    speakers: list[str] | None = None,
    speed: float = 1.0,
    out_path: Path | None = None,
    endpoint: str = "",
    audio_format: str = "mp3",
) -> PodcastSynthesisResult:
    """Produce one podcast, blocking until it is complete.

    Synchronous on purpose: every caller is already a job thread, and handing them a coroutine
    would mean each of them running its own event loop anyway.

    `turns` is the script for READ: `[{"speaker": <voice>, "text": ...}]`, one entry per round, sent as `nlp_texts`
    verbatim. Who reads which line is the caller's decision (the script editor in AI Studio, ADR 0055); a plain text is
    turned into alternating rounds by the caller with `split_to_rounds`, not here.
    """
    if not appid or not token:
        raise PodcastSynthesisError("providerErr_podcastCredentialsMissing")
    chosen = [voice for voice in (speakers or []) if voice]
    if action in (PodcastAction.SUMMARIZE, PodcastAction.RESEARCH) and len(chosen) != 2:
        raise PodcastSynthesisError("providerErr_podcastNeedsTwoSpeakers")
    if action == PodcastAction.SUMMARIZE and not input_text.strip():
        raise PodcastSynthesisError("providerErr_podcastNeedsInputText")
    if action == PodcastAction.RESEARCH and not prompt_text.strip():
        raise PodcastSynthesisError("providerErr_podcastNeedsTopic")

    nlp_texts = None
    if action == PodcastAction.READ:
        nlp_texts = [
            {"text": str(turn.get("text") or "").strip(), "speaker": str(turn.get("speaker") or "")}
            for turn in (turns or [])
        ]
        nlp_texts = [turn for turn in nlp_texts if turn["text"]]
        if not nlp_texts:
            raise PodcastSynthesisError("providerErr_podcastReadNeedsText")
        if not all(turn["speaker"] for turn in nlp_texts):
            raise PodcastSynthesisError("providerErr_podcastReadNeedsSpeaker")
        if len(nlp_texts) > MAX_ROUNDS:
            raise PodcastSynthesisError("providerErr_podcastTooManyTurns", limit=MAX_ROUNDS)
        if any(len(turn["text"]) > MAX_ROUND_CHARS for turn in nlp_texts):
            raise PodcastSynthesisError("providerErr_podcastTurnTooLong", limit=MAX_ROUND_CHARS)

    payload = _session_payload(
        action=action,
        input_text=input_text,
        prompt_text=prompt_text,
        nlp_texts=nlp_texts,
        speakers=chosen,
        speech_rate=max(-50, min(100, round((max(0.2, min(3.0, speed)) - 1.0) * 100))),
        audio_format=audio_format,
    )
    from app.core.outbound_guard import Origin
    from app.core.outbound_proxy import ticket

    #: websocket 也过出站检查:经守卫代理连过去(core/outbound_proxy)。地址是连接里填的(或内置的)。
    with ticket(Origin.CONFIGURED) as issued:
        try:
            result = asyncio.run(_run(appid, token, payload, endpoint=endpoint or ENDPOINT, proxy=issued.url))
        except Exception:
            if issued.refused is not None:
                raise issued.refused from None
            raise
    if out_path is not None:
        out_path.write_bytes(result.audio)
    return result
