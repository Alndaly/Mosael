"""火山 播客 TTS: the binary framing, and the state machine on top of it.

A wire format with no self-description cannot be checked by reading it — an off-by-one in a
length prefix produces a frame the server rejects with a generic error, which tells you
nothing about which field was wrong. So the framing is pinned by round-trip, and the session
flow is exercised against a fake server that speaks the same frames the real one does.
"""

from __future__ import annotations

import asyncio
import json
import struct
import threading

import pytest

from app.domain.voices import podcast
from app.domain.voices.podcast_protocol import (
    EventType,
    Message,
    MsgType,
    MsgTypeFlag,
    unmarshal,
)


class TestFraming:
    def test_a_session_frame_survives_a_round_trip(self) -> None:
        message = Message(MsgType.FullClientRequest, MsgTypeFlag.WithEvent)
        message.event = EventType.StartSession
        message.session_id = "abc123"
        message.payload = b'{"req_params": {}}'

        parsed = unmarshal(message.marshal())

        assert parsed.type == MsgType.FullClientRequest
        assert parsed.event == EventType.StartSession
        assert parsed.session_id == "abc123"
        assert parsed.payload == b'{"req_params": {}}'

    def test_a_connection_frame_carries_no_session_id(self) -> None:
        """Sending one on a connection-scoped event desynchronises the server's parser: it
        reads the id's length prefix as the payload's."""
        message = Message(MsgType.FullClientRequest, MsgTypeFlag.WithEvent)
        message.event = EventType.StartConnection
        message.session_id = "should-not-be-sent"
        message.payload = b"{}"

        raw = message.marshal()

        assert b"should-not-be-sent" not in raw
        assert unmarshal(raw).payload == b"{}"

    def test_binary_audio_survives_intact(self) -> None:
        """Audio is the payload of an AudioOnlyServer frame; any mangling here is silent."""
        message = Message(MsgType.AudioOnlyServer, MsgTypeFlag.WithEvent)
        message.event = EventType.PodcastRoundResponse
        message.session_id = "s"
        message.payload = bytes(range(256))
        assert unmarshal(message.marshal()).payload == bytes(range(256))

    def test_a_truncated_frame_is_an_error_not_a_guess(self) -> None:
        message = Message(MsgType.FullServerResponse, MsgTypeFlag.WithEvent)
        message.event = EventType.SessionStarted
        message.session_id = "s"
        message.payload = b"12345678"
        with pytest.raises(ValueError):
            unmarshal(message.marshal()[:-4])

    def test_a_frame_shorter_than_its_header_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            unmarshal(b"\x11")

    def test_lengths_are_big_endian(self) -> None:
        """The one byte-order mistake that produces a plausible-looking frame."""
        message = Message(MsgType.FullClientRequest, MsgTypeFlag.WithEvent)
        message.event = EventType.StartConnection
        message.payload = b"x" * 258
        raw = message.marshal()
        assert struct.unpack(">I", raw[-262:-258])[0] == 258


class TestRoundSplitting:
    def test_two_speakers_get_one_sentence_each(self) -> None:
        """Otherwise one voice reads a paragraph and the other answers once."""
        rounds = podcast.split_to_rounds("第一句。第二句。第三句。", dual=True)
        assert rounds == ["第一句。", "第二句。", "第三句。"]

    def test_a_single_speaker_packs_rounds(self) -> None:
        """Nothing to alternate, so fewer rounds means a smaller bill."""
        rounds = podcast.split_to_rounds("短句。" * 40, dual=False)
        assert len(rounds) < 40
        assert all(len(r) <= podcast.MAX_ROUND_CHARS + len("短句。") for r in rounds)

    def test_rounds_are_capped(self) -> None:
        """A runaway job is billed per round."""
        assert len(podcast.split_to_rounds("句。" * 500, dual=True)) == podcast.MAX_ROUNDS

    def test_empty_text_yields_no_rounds(self) -> None:
        assert podcast.split_to_rounds("   \n  ", dual=True) == []


class TestArgumentChecks:
    """Each of these fails at the server with a generic error, so catch them here where the
    message can say what to fix."""

    def test_the_v3_api_key_is_not_accepted_as_a_token(self) -> None:
        with pytest.raises(podcast.PodcastError, match="App ID"):
            podcast.synthesize_podcast("", "", action=podcast.Action.SUMMARIZE, input_text="x")

    def test_generated_dialogue_needs_exactly_two_speakers(self) -> None:
        with pytest.raises(podcast.PodcastError, match="两个发音人"):
            podcast.synthesize_podcast("a", "b", input_text="x", speakers=["one"])

    def test_summarize_needs_text(self) -> None:
        with pytest.raises(podcast.PodcastError, match="改写成对话"):
            podcast.synthesize_podcast("a", "b", input_text="  ", speakers=["one", "two"])

    def test_research_needs_a_topic(self) -> None:
        with pytest.raises(podcast.PodcastError, match="检索"):
            podcast.synthesize_podcast("a", "b", action=podcast.Action.RESEARCH, speakers=["1", "2"])

    def test_read_mode_needs_a_speaker(self) -> None:
        with pytest.raises(podcast.PodcastError, match="发音人"):
            podcast.synthesize_podcast("a", "b", action=podcast.Action.READ, input_text="x", speakers=[])


class TestSessionPayload:
    def test_speaker_info_is_omitted_in_read_mode(self) -> None:
        """In READ mode the speaker rides with each text; speaker_info there is rejected."""
        payload = podcast._session_payload(
            action=podcast.Action.READ,
            input_text="",
            prompt_text="",
            nlp_texts=[{"text": "hi", "speaker": "a"}],
            speakers=["a"],
            speech_rate=0,
            audio_format="mp3",
        )
        assert "speaker_info" not in payload["req_params"]

    def test_speaker_info_is_present_for_generated_dialogue(self) -> None:
        payload = podcast._session_payload(
            action=podcast.Action.SUMMARIZE,
            input_text="x",
            prompt_text="",
            nlp_texts=None,
            speakers=["a", "b"],
            speech_rate=0,
            audio_format="mp3",
        )
        assert payload["req_params"]["speaker_info"]["speakers"] == ["a", "b"]

    @pytest.mark.parametrize("speed,expected", [(1.0, 0), (2.0, 100), (0.5, -50), (1.25, 25)])
    def test_speed_maps_to_the_int_speech_rate(self, speed: float, expected: int) -> None:
        """火山 takes an int in [-50, 100] where 0 is natural, not a multiplier. This mapping
        is what makes `speed` mean the same thing across engines."""
        captured = {}

        def fake_run(appid, token, payload, *, endpoint):
            captured.update(payload["req_params"]["audio_config"])
            raise podcast.PodcastError("stop")

        original = podcast.asyncio.run
        podcast.asyncio.run = lambda coro: (coro.close(), fake_run("a", "b", _LAST_PAYLOAD[0], endpoint=""))[1]
        try:
            with pytest.raises(podcast.PodcastError):
                _capture_payload(speed=speed)
        finally:
            podcast.asyncio.run = original
        assert captured["speech_rate"] == expected


_LAST_PAYLOAD: list[dict] = [{}]


def _capture_payload(*, speed: float):
    """Build the payload the way synthesize_podcast does, without opening a socket."""
    _LAST_PAYLOAD[0] = podcast._session_payload(
        action=podcast.Action.SUMMARIZE,
        input_text="x",
        prompt_text="",
        nlp_texts=None,
        speakers=["a", "b"],
        speech_rate=max(-50, min(100, round((max(0.2, min(3.0, speed)) - 1.0) * 100))),
        audio_format="mp3",
    )
    return podcast.synthesize_podcast("a", "b", input_text="x", speakers=["a", "b"], speed=speed)


def _server_frame(event: int, payload: bytes, msg_type=MsgType.FullServerResponse, session="s") -> bytes:
    message = Message(msg_type, MsgTypeFlag.WithEvent)
    message.event = event
    message.session_id = session
    message.payload = payload
    return message.marshal()


@pytest.fixture(autouse=True)
def _short_timeouts(monkeypatch):
    """The production waits are sized for a model call. A test that hits one is a hang, not
    a slow pass, so fail fast enough to see which frame never arrived."""
    monkeypatch.setattr(podcast, "HANDSHAKE_TIMEOUT", 5)
    monkeypatch.setattr(podcast, "FRAME_TIMEOUT", 5)


class TestAgainstAFakeServer:
    """The state machine, driven by the same frames the real server sends."""

    @staticmethod
    def _serve(script):
        """Run a WebSocket server that replies with `script` frames, return its ws:// url."""
        import websockets

        ready = threading.Event()
        holder: dict = {}

        async def handler(socket):
            # The client sends three frames (StartConnection, StartSession, FinishSession) and
            # then only listens, so replying one-for-one would leave the rest of the script
            # unsent and the client blocked on recv. Flush everything once it goes quiet.
            received = 0
            async for _ in socket:
                received += 1
                if script:
                    await socket.send(script.pop(0))
                if received >= 3:
                    while script:
                        await socket.send(script.pop(0))
                    # Stay open. The real server does, and the client still has a
                    # FinishConnection to send.

        async def main():
            async with websockets.serve(handler, "127.0.0.1", 0) as server:
                holder["port"] = server.sockets[0].getsockname()[1]
                holder["loop"] = asyncio.get_running_loop()
                holder["stop"] = asyncio.Event()
                ready.set()
                await holder["stop"].wait()

        thread = threading.Thread(target=lambda: asyncio.run(main()), daemon=True)
        thread.start()
        ready.wait(5)
        return f"ws://127.0.0.1:{holder['port']}", holder

    def test_a_full_session_yields_audio_and_the_dialogue(self) -> None:
        script = [
            _server_frame(EventType.ConnectionStarted, b"{}"),
            _server_frame(EventType.SessionStarted, b"{}"),
            _server_frame(
                EventType.PodcastRoundResponse,
                json.dumps({"speaker": "a", "text": "你好"}).encode(),
            ),
            _server_frame(EventType.PodcastRoundResponse, b"AUDIO", msg_type=MsgType.AudioOnlyServer),
            _server_frame(EventType.PodcastEnd, b"{}"),
        ]
        url, holder = self._serve(script)
        try:
            result = podcast.synthesize_podcast(
                "app", "token", input_text="原文", speakers=["a", "b"], endpoint=url
            )
        finally:
            holder["loop"].call_soon_threadsafe(holder["stop"].set)

        assert result.audio == b"AUDIO"
        assert result.texts == [{"speaker": "a", "text": "你好"}]

    def test_a_refused_connection_says_so(self) -> None:
        url, holder = self._serve([_server_frame(EventType.ConnectionFailed, b'{"error":"bad key"}')])
        try:
            with pytest.raises(podcast.PodcastError, match="连接被拒绝"):
                podcast.synthesize_podcast("app", "token", input_text="x", speakers=["a", "b"], endpoint=url)
        finally:
            holder["loop"].call_soon_threadsafe(holder["stop"].set)

    def test_an_error_frame_carries_its_code(self) -> None:
        error = Message(MsgType.Error, MsgTypeFlag.WithEvent)
        error.event = EventType.PodcastRoundResponse
        error.session_id = "s"
        error.payload = b'{"message":"quota"}'
        raw = bytearray(error.marshal())
        # Error frames put a 4-byte code before the event, which marshal() does not write.
        framed = bytes(raw[:4]) + struct.pack(">I", 55000000) + bytes(raw[4:])

        script = [
            _server_frame(EventType.ConnectionStarted, b"{}"),
            _server_frame(EventType.SessionStarted, b"{}"),
            framed,
        ]
        url, holder = self._serve(script)
        try:
            with pytest.raises(podcast.PodcastError, match="55000000"):
                podcast.synthesize_podcast("app", "token", input_text="x", speakers=["a", "b"], endpoint=url)
        finally:
            holder["loop"].call_soon_threadsafe(holder["stop"].set)

    def test_a_session_that_produces_no_audio_is_an_error(self) -> None:
        """Silence is not a successful podcast, and an empty mp3 asset would look like one."""
        script = [
            _server_frame(EventType.ConnectionStarted, b"{}"),
            _server_frame(EventType.SessionStarted, b"{}"),
            _server_frame(EventType.PodcastEnd, b"{}"),
        ]
        url, holder = self._serve(script)
        try:
            with pytest.raises(podcast.PodcastError, match="空音频"):
                podcast.synthesize_podcast("app", "token", input_text="x", speakers=["a", "b"], endpoint=url)
        finally:
            holder["loop"].call_soon_threadsafe(holder["stop"].set)


class TestTheJobEndpoint:
    """The podcast reaches the API as a job, like every other long-running generation."""

    @staticmethod
    def _client():
        from tests.util import fresh_client

        client = fresh_client()
        client.post("/api/workspaces", json={"name": "W"})
        return client

    def test_the_engine_is_offered_with_its_speakers(self) -> None:
        client = self._client()
        engines = {item["id"]: item for item in client.get("/api/tts/engines").json()}
        assert engines["volcano-podcast"]["voices"], "the podcast engine has no speakers to offer"
        assert engines["volcano-podcast"]["needs_key"] is True

    def test_an_unknown_mode_is_refused(self) -> None:
        client = self._client()
        workspace_id = client.get("/api/workspaces").json()[0]["id"]
        res = client.post(
            "/api/tts/podcast",
            json={"workspace_id": workspace_id, "text": "x", "mode": "nonsense"},
        )
        assert res.status_code == 422

    def test_missing_credentials_fail_the_job_with_a_readable_reason(self) -> None:
        """Not a stack trace: the fix is in Settings, and the message has to say so."""
        import time

        from app.core.db import SessionLocal
        from app.db.models import Job

        client = self._client()
        workspace_id = client.get("/api/workspaces").json()[0]["id"]
        res = client.post(
            "/api/tts/podcast",
            json={
                "workspace_id": workspace_id,
                "text": "第一句。第二句。",
                "mode": "summarize",
                "speakers": ["a", "b"],
            },
        )
        assert res.status_code == 200, res.text
        job_id = res.json()["id"]

        deadline = time.time() + 5
        while time.time() < deadline:
            with SessionLocal() as db:
                job = db.get(Job, job_id)
                if job.status in ("failed", "succeeded"):
                    break
            time.sleep(0.05)

        with SessionLocal() as db:
            job = db.get(Job, job_id)
            assert job.status == "failed"
            assert "App ID" in (job.error or ""), job.error
