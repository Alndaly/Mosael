"""常驻 TTS worker 与宿主共享一份可校验的行协议。"""

from __future__ import annotations

import pytest

from app.ai.runtime.workers.tts_protocol import (
    WorkerProtocolError,
    decode_event_line,
    encode_event_line,
)
from app.ai.runtime.workers import tts as worker


@pytest.mark.parametrize(
    "event",
    [
        {"event": "progress", "phase": "load", "fraction": 0.25, "message": "准备引擎"},
        {"event": "done", "engine": "f5-tts", "output": "/tmp/out.wav"},
        {"event": "error", "message": "weights missing"},
    ],
)
def test_event_round_trips_through_the_wire_contract(event: dict) -> None:
    assert decode_event_line(encode_event_line(event)) == event


def test_non_protocol_output_remains_a_log_line() -> None:
    assert decode_event_line("Downloading 42%\n") is None


@pytest.mark.parametrize(
    "line",
    [
        '@@MOSAEL-TTS {"event":"mystery"}\n',
        '@@MOSAEL-TTS {"event":"progress","phase":"load","fraction":2}\n',
        '@@MOSAEL-TTS {"event":"error","message":""}\n',
        "@@MOSAEL-TTS not-json\n",
    ],
)
def test_invalid_protocol_events_fail_with_a_protocol_error(line: str) -> None:
    with pytest.raises(WorkerProtocolError):
        decode_event_line(line)


def test_fetch_model_request_uses_the_same_dispatcher_in_daemon_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict] = []
    monkeypatch.setattr(worker, "fetch_named_model", lambda request: seen.append(request) or "f5-tts")

    engine, output = worker.execute_request({"action": "fetch_model", "checkpoint": "model.pt"})

    assert engine == "f5-tts"
    assert output == ""
    assert seen == [{"action": "fetch_model", "checkpoint": "model.pt"}]


def test_synthesis_request_requires_an_output_path() -> None:
    with pytest.raises(ValueError, match="output_path"):
        worker.execute_request({"action": "synthesize", "engine": "f5-tts"})
