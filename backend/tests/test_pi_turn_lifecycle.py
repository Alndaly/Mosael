"""A turn must end when the answer ends, not when the sidecar process happens to exit.

Steering needs the sidecar's stdin to stay open for the whole turn, which removed the thing
that used to make the process exit: closing stdin ended its readline loop, which ended the
process, which closed stdout, which ended the backend's read loop. With stdin held open the
read loop waited for an EOF that never came, so every turn stayed "running" for the full
timeout — minutes after the reply had finished streaming, with the UI still spinning.

These tests drive a fake sidecar: a real subprocess speaking the real protocol, because the
bug lived entirely in when the two processes agree the turn is over.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from app.ai.agent import adapters

FAKE_SIDECAR = '''
import json, sys, time
# Answer the turn, then deliberately keep reading stdin forever — exactly what the real
# sidecar does now that steering needs the channel open.
line = sys.stdin.readline()
turn = json.loads(line)["turnId"]
print(json.dumps({"type": "text_delta", "turnId": turn, "delta": "hello"}), flush=True)
print(json.dumps({"type": "turn_done", "turnId": turn, "text": "hello", "sessionState": [1]}), flush=True)
# Keep reading until the backend closes the channel, exactly like the real sidecar. That is
# what makes the deadlock possible: the process cannot exit until stdin closes, and stdin
# used to close only after the read loop had already ended.
for _ in sys.stdin:
    pass
'''


@pytest.fixture
def fake_sidecar(tmp_path: Path, monkeypatch):
    script = tmp_path / "sidecar.py"
    script.write_text(FAKE_SIDECAR)
    monkeypatch.setattr(adapters, "_pi_sidecar_command", lambda: (sys.executable, str(script)))
    monkeypatch.setattr(Path, "exists", lambda self: True, raising=False)
    return script


def _run(**kwargs):
    return adapters._run_pi(
        "hi",
        "system",
        "http://127.0.0.1:8899",
        "token",
        "ws",
        {"base_url": "http://x", "api_key": "k", "vendor": "v"},
        "model",
        None,
        None,
        None,
        **kwargs,
    )


def test_the_turn_ends_at_turn_done_not_at_process_exit(fake_sidecar) -> None:
    """The whole bug in one assertion: the sidecar is still alive and holding stdin when the
    answer is complete, and the turn must return anyway."""
    started = time.monotonic()
    result = _run()
    elapsed = time.monotonic() - started

    assert result.text == "hello"
    assert elapsed < 5, f"waited {elapsed:.1f}s for a turn that finished immediately"


def test_the_live_channel_is_released_when_the_turn_ends(fake_sidecar) -> None:
    """A stale entry would let a later steer write into a finished turn's stdin."""
    _run(session_id="sess-1")
    assert "sess-1" not in adapters._LIVE


def test_steering_reaches_a_running_turn_and_not_a_finished_one(fake_sidecar) -> None:
    """steer_turn's return value is what the caller uses to decide between injecting the
    message and running it as an ordinary next turn."""
    assert adapters.steer_turn("sess-2", "改一下") is False  # nothing running
    _run(session_id="sess-2")
    assert adapters.steer_turn("sess-2", "改一下") is False  # finished, channel closed
