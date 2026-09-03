"""Dependency-free line protocol shared by the TTS worker and its host.

This file runs under both the application interpreter and the engine's isolated
interpreter.  It must therefore stay standard-library-only and must not import
``app.*``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

EVENT_PREFIX = "@@MOSAEL-TTS "
EVENT_KINDS = ("progress", "done", "error")


class WorkerProtocolError(RuntimeError):
    pass


def _text(event: Mapping[str, Any], key: str, *, allow_empty: bool = False) -> str:
    value = event.get(key)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        qualifier = "a string" if allow_empty else "a non-empty string"
        raise WorkerProtocolError(f"TTS worker event field {key!r} must be {qualifier}")
    return value


def validate_event(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkerProtocolError("TTS worker event must be an object")
    event = dict(value)
    kind = event.get("event")
    if kind not in EVENT_KINDS:
        raise WorkerProtocolError(f"unknown TTS worker event: {kind!r}")
    if kind == "progress":
        _text(event, "phase")
        fraction = event.get("fraction")
        if isinstance(fraction, bool) or not isinstance(fraction, (int, float)) or not 0 <= fraction <= 1:
            raise WorkerProtocolError("TTS worker progress fraction must be between 0 and 1")
        _text(event, "message", allow_empty=True)
    elif kind == "done":
        _text(event, "engine")
        _text(event, "output", allow_empty=True)
    else:
        _text(event, "message")
    return event


def encode_event_line(event: Mapping[str, Any]) -> str:
    return EVENT_PREFIX + json.dumps(validate_event(event), ensure_ascii=False) + "\n"


def decode_event_line(line: str) -> dict[str, Any] | None:
    if not line.startswith(EVENT_PREFIX):
        return None
    try:
        value = json.loads(line[len(EVENT_PREFIX) :])
    except (TypeError, ValueError) as exc:
        raise WorkerProtocolError("TTS worker emitted malformed JSON") from exc
    return validate_event(value)
