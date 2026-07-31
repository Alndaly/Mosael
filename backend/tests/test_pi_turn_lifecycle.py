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

#: Answers the turn, then reports every control frame it receives back through stderr, so a
#: test can assert on what the backend actually wrote — the steering channel is otherwise
#: invisible from the Python side.
ECHO_SIDECAR = '''
import json, os, sys
log = open(os.environ["FRAME_LOG"], "a")
line = sys.stdin.readline()
turn = json.loads(line)["turnId"]
print(json.dumps({"type": "text_delta", "turnId": turn, "delta": "hi"}), flush=True)
for raw in sys.stdin:
    raw = raw.strip()
    if not raw:
        continue
    log.write(raw + "\\n")
    log.flush()
    if json.loads(raw).get("type") == "abort":
        break
print(json.dumps({"type": "turn_done", "turnId": turn, "text": "hi", "sessionState": None}), flush=True)
'''

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
    monkeypatch.setattr(adapters, "pi_sidecar_command", lambda: (sys.executable, str(script)))
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


@pytest.fixture
def echo_sidecar(tmp_path: Path, monkeypatch):
    script = tmp_path / "echo.py"
    script.write_text(ECHO_SIDECAR)
    log = tmp_path / "frames.jsonl"
    monkeypatch.setenv("FRAME_LOG", str(log))
    monkeypatch.setattr(adapters, "pi_sidecar_command", lambda: (sys.executable, str(script)))
    monkeypatch.setattr(Path, "exists", lambda self: True, raising=False)
    return log


def _frames(log: Path) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


class TestControlFrames:
    """What the backend actually writes into a running turn.

    Everything above this point mocks the channel out, so the frames themselves — the format
    the sidecar parses — were never exercised. A typo in a key name would fail silently: the
    sidecar ignores what it does not recognise, and the turn would look normal while the
    steer went nowhere.
    """

    @staticmethod
    def _run_with(session_id: str, act, capture: dict) -> None:
        import threading

        def drive():
            # The turn is blocking, so the control frames are written from another thread —
            # the same shape as an API request arriving mid-turn.
            time.sleep(0.4)
            act()
            time.sleep(0.2)
            adapters.abort_turn(session_id)

        thread = threading.Thread(target=drive, daemon=True)
        thread.start()
        capture["result"] = adapters._run_pi(
            "hi", "system", "http://x", "token", "ws",
            {"base_url": "http://x", "api_key": "k", "vendor": "v"},
            "model", None, None, None, session_id=session_id,
        )
        thread.join(5)

    def test_a_steer_reaches_the_sidecar_in_the_shape_it_parses(self, echo_sidecar) -> None:
        capture: dict = {}
        self._run_with("s-steer", lambda: adapters.steer_turn("s-steer", "改成竖屏"), capture)
        frames = _frames(echo_sidecar)

        steer = next(f for f in frames if f["type"] == "steer")
        assert steer["prompt"] == "改成竖屏"
        assert steer["mode"] == "steer"
        assert steer["turnId"], "the sidecar routes by turnId; an empty one lands nowhere"

    def test_declaring_a_queue_sends_the_whole_list(self, echo_sidecar) -> None:
        """Per-message cancel depends on this: pi can only clear its queue, so the client
        declares what should remain rather than what to remove."""
        capture: dict = {}
        self._run_with("s-queue", lambda: adapters.set_turn_queue("s-queue", ["二", "三"]), capture)
        frames = _frames(echo_sidecar)

        queue = next(f for f in frames if f["type"] == "queue")
        assert queue["prompts"] == ["二", "三"]

    def test_an_empty_queue_is_sent_as_an_empty_list_not_skipped(self, echo_sidecar) -> None:
        """Withdrawing the only queued message must actually clear pi's queue."""
        capture: dict = {}
        self._run_with("s-empty", lambda: adapters.set_turn_queue("s-empty", []), capture)
        frames = _frames(echo_sidecar)

        queue = next(f for f in frames if f["type"] == "queue")
        assert queue["prompts"] == []
