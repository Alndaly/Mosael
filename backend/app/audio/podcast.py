"""火山 播客 TTS — two voices reading a dialogue, over a WebSocket.

This is a different product from the v3 speech endpoint, not a mode of it, and the difference
that bites first is the credential: the podcast socket authenticates with an appid and an
access token from the speech console and rejects the v3 API Key outright. Mixing the two is
the single most common way to get an unexplained handshake failure, which is why they live
under separate vendors — see VENDOR_PRESETS.

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

from app.audio.podcast_protocol import EventType, Message, MsgType, MsgTypeFlag, unmarshal

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


class PodcastError(RuntimeError):
    """Raised when the podcast cannot be produced, carrying 火山's message where there is one."""


class Action:
    """What the server should do with the text it is given."""

    #: Summarise input_text into a dialogue. Requires exactly two speakers.
    SUMMARIZE = 0
    #: Read nlp_texts verbatim; the speaker follows the text, not speaker_info.
    READ = 3
    #: Research prompt_text on the web, then discuss it. Requires exactly two speakers.
    RESEARCH = 4


@dataclass
class PodcastResult:
    audio: bytes = b""
    #: One entry per spoken turn: {"speaker": ..., "text": ...}. This is what becomes the
    #: transcript, and for SUMMARIZE it is the only place the generated dialogue exists.
    texts: list[dict] = field(default_factory=list)


def split_to_rounds(text: str, *, dual: bool) -> list[str]:
    """Chop text into rounds.

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
        "input_id": "mibu",
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
    if action in (Action.SUMMARIZE, Action.RESEARCH):
        params["speaker_info"] = {"random_order": False, "speakers": list(speakers)}
    return {"req_params": params}


def _control(event: int, payload: bytes, session_id: str = "") -> bytes:
    message = Message(MsgType.FullClientRequest, MsgTypeFlag.WithEvent)
    message.event = event
    message.session_id = session_id
    message.payload = payload
    return message.marshal()


async def _run(
    appid: str,
    token: str,
    payload: dict,
    *,
    endpoint: str,
) -> PodcastResult:
    import websockets

    headers = {
        "X-Api-App-Id": appid,
        "X-Api-App-Key": APP_KEY,
        "X-Api-Access-Key": token,
        "X-Api-Resource-Id": RESOURCE_ID,
        "X-Api-Connect-Id": uuid.uuid4().hex,
    }
    result = PodcastResult()
    session_id = uuid.uuid4().hex

    async with websockets.connect(endpoint, additional_headers=headers, max_size=None) as socket:
        await socket.send(_control(EventType.StartConnection, b"{}"))
        started = unmarshal(await asyncio.wait_for(socket.recv(), HANDSHAKE_TIMEOUT))
        if started.event != EventType.ConnectionStarted:
            raise PodcastError(f"播客连接被拒绝:{started.payload.decode('utf-8', 'replace')[:200]}")

        await socket.send(
            _control(EventType.StartSession, json.dumps(payload).encode("utf-8"), session_id)
        )
        session = unmarshal(await asyncio.wait_for(socket.recv(), HANDSHAKE_TIMEOUT))
        if session.event != EventType.SessionStarted:
            raise PodcastError(f"播客会话启动失败:{session.payload.decode('utf-8', 'replace')[:200]}")

        await socket.send(_control(EventType.FinishSession, b"{}", session_id))

        while True:
            frame = unmarshal(await asyncio.wait_for(socket.recv(), FRAME_TIMEOUT))
            if frame.type == MsgType.Error:
                raise PodcastError(
                    f"播客生成失败(code={frame.error_code}):"
                    f"{frame.payload.decode('utf-8', 'replace')[:200]}"
                )
            if frame.type == MsgType.AudioOnlyServer:
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
                raise PodcastError(f"播客会话失败:{frame.payload.decode('utf-8', 'replace')[:200]}")

        try:
            await socket.send(_control(EventType.FinishConnection, b"{}"))
        except Exception:  # noqa: BLE001
            # A courtesy goodbye. The podcast is already complete in `result`, so a server
            # that hung up first must not cost us the audio we just received.
            logger.debug("podcast FinishConnection not delivered", exc_info=True)

    if not result.audio:
        raise PodcastError("播客返回了空音频")
    return result


def synthesize_podcast(
    appid: str,
    token: str,
    *,
    action: int = Action.SUMMARIZE,
    input_text: str = "",
    prompt_text: str = "",
    speakers: list[str] | None = None,
    speed: float = 1.0,
    out_path: Path | None = None,
    endpoint: str = "",
    audio_format: str = "mp3",
) -> PodcastResult:
    """Produce one podcast, blocking until it is complete.

    Synchronous on purpose: every caller is already a job thread, and handing them a coroutine
    would mean each of them running its own event loop anyway.
    """
    if not appid or not token:
        raise PodcastError("火山播客需要 App ID 和 Access Token(不是语音合成的 API Key)")
    chosen = [voice for voice in (speakers or []) if voice]
    if action in (Action.SUMMARIZE, Action.RESEARCH) and len(chosen) != 2:
        raise PodcastError("AI 生成对话需要正好两个发音人")
    if action == Action.SUMMARIZE and not input_text.strip():
        raise PodcastError("请提供要改写成对话的文本")
    if action == Action.RESEARCH and not prompt_text.strip():
        raise PodcastError("请提供要检索并讨论的主题")

    nlp_texts = None
    if action == Action.READ:
        if not chosen:
            raise PodcastError("朗读模式需要至少一个发音人")
        rounds = split_to_rounds(input_text, dual=len(chosen) > 1)
        if not rounds:
            raise PodcastError("请提供要朗读的文本")
        # Speakers alternate round by round, which is what makes a two-voice read sound like
        # a conversation rather than one voice with interruptions.
        nlp_texts = [
            {"text": text, "speaker": chosen[index % len(chosen)]} for index, text in enumerate(rounds)
        ]

    payload = _session_payload(
        action=action,
        input_text=input_text,
        prompt_text=prompt_text,
        nlp_texts=nlp_texts,
        speakers=chosen,
        speech_rate=max(-50, min(100, round((max(0.2, min(3.0, speed)) - 1.0) * 100))),
        audio_format=audio_format,
    )
    result = asyncio.run(_run(appid, token, payload, endpoint=endpoint or ENDPOINT))
    if out_path is not None:
        out_path.write_bytes(result.audio)
    return result
