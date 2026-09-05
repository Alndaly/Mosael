"""Dependency-free line protocol shared by the TTS worker and its host.

This file runs under both the application interpreter and the engine's isolated
interpreter.  It must therefore stay standard-library-only and must not import
``app.*``.

帧格式住在 ``line_protocol``(识别那边走同一套)。这里只声明 TTS 这一侧不同的东西:
前缀,以及 ``done`` 的形状 —— 合成的 done 给的是"哪个引擎跑的、产出在哪"。
"""

from __future__ import annotations

from typing import Any

if __package__:
    from .line_protocol import LineProtocol, WorkerProtocolError, text_field
else:
    # Executed directly by the engine's isolated interpreter; its sys.path only
    # contains this directory, not the application package.
    from line_protocol import LineProtocol, WorkerProtocolError, text_field

_WHAT = "TTS worker"


def _validate_done(event: dict[str, Any]) -> None:
    text_field(event, "engine", what=_WHAT)
    text_field(event, "output", what=_WHAT, allow_empty=True)


_PROTOCOL = LineProtocol(prefix="@@MOSAEL-TTS ", what=_WHAT, validate_done=_validate_done)

EVENT_PREFIX = _PROTOCOL.prefix
EVENT_KINDS = _PROTOCOL.kinds
validate_event = _PROTOCOL.validate
encode_event_line = _PROTOCOL.encode
decode_event_line = _PROTOCOL.decode

__all__ = [
    "EVENT_KINDS",
    "EVENT_PREFIX",
    "WorkerProtocolError",
    "decode_event_line",
    "encode_event_line",
    "validate_event",
]
