"""火山 播客 TTS wire format — a binary framing layer, not JSON over WebSocket.

Every message is a 4-byte header, then optional fields whose presence the header's flags
decide, then a length-prefixed payload. All integers are big-endian. Nothing here talks to
the network; keeping the framing separate is what makes it testable, and an encode/parse
round-trip is the only way to catch an off-by-one in a format with no self-description.

Header bytes:
  0: protocol version (high nibble) | header size in 4-byte words (low nibble)
  1: message type (high nibble) | message-type flags (low nibble)
  2: serialization (high nibble) | compression (low nibble)
  3: reserved
"""

from __future__ import annotations

import enum
import struct

PROTOCOL_VERSION = 0b0001
DEFAULT_HEADER_SIZE = 0b0001  # one 4-byte word


class MessageType(enum.IntEnum):
    FullClientRequest = 0b0001
    AudioOnlyClient = 0b0010
    FullServerResponse = 0b1001
    AudioOnlyServer = 0b1011
    FrontEndResultServer = 0b1100
    Error = 0b1111


class MessageFlags(enum.IntEnum):
    NoSeq = 0
    PositiveSeq = 0b1
    LastNoSeq = 0b10
    NegativeSeq = 0b11
    WithEvent = 0b100


class Serialization(enum.IntEnum):
    Raw = 0
    JSON = 0b1


class Compression(enum.IntEnum):
    Nothing = 0
    Gzip = 0b1


class EventType(enum.IntEnum):
    Nothing = 0

    StartConnection = 1
    FinishConnection = 2
    ConnectionStarted = 50
    ConnectionFailed = 51
    ConnectionFinished = 52

    StartSession = 100
    FinishSession = 102
    SessionStarted = 150
    SessionCanceled = 151
    SessionFinished = 152
    SessionFailed = 153

    # Podcast-specific. A round is one speaker's turn.
    PodcastRoundStart = 360
    PodcastRoundResponse = 361
    PodcastRoundEnd = 362
    PodcastEnd = 363


#: Which id, if any, follows the event field. to_bytes and parse_message MUST agree: the field is
#: length-prefixed but not tagged, so a disagreement makes the reader take the id's length as
#: the payload's and every later field shifts. That shows up as a generic "bad frame" from the
#: server with nothing pointing at the cause.
_CONNECTION_ID_EVENTS = (EventType.ConnectionStarted, EventType.ConnectionFailed)
_NO_ID_EVENTS = (EventType.StartConnection, EventType.FinishConnection, EventType.ConnectionFinished)


def _identifier_field(event: int) -> str | None:
    if event in _CONNECTION_ID_EVENTS:
        return "connect_id"
    if event in _NO_ID_EVENTS:
        return None
    return "session_id"


def _event_identifier(event: int, session_id: str, connect_id: str) -> str | None:
    field_name = _identifier_field(event)
    if field_name is None:
        return None
    return connect_id if field_name == "connect_id" else session_id


class PodcastProtocolMessage:
    """One framed message, in either direction."""

    def __init__(
        self,
        msg_type: MessageType,
        flag: MessageFlags = MessageFlags.NoSeq,
        serialization: Serialization = Serialization.JSON,
        compression: Compression = Compression.Nothing,
    ) -> None:
        self.type = msg_type
        self.flag = flag
        self.serialization = serialization
        self.compression = compression
        self.event: int = EventType.Nothing
        self.session_id: str = ""
        self.connect_id: str = ""
        self.sequence: int = 0
        self.error_code: int = 0
        self.payload: bytes = b""

    def to_bytes(self) -> bytes:
        out = bytearray(
            [
                (PROTOCOL_VERSION << 4) | DEFAULT_HEADER_SIZE,
                (int(self.type) << 4) | int(self.flag),
                (int(self.serialization) << 4) | int(self.compression),
                0,
            ]
        )
        if self.flag & MessageFlags.WithEvent:
            out += struct.pack(">i", int(self.event))
            identifier = _event_identifier(int(self.event), self.session_id, self.connect_id)
            if identifier is not None:
                encoded = identifier.encode("utf-8")
                out += struct.pack(">I", len(encoded)) + encoded
        out += struct.pack(">I", len(self.payload)) + self.payload
        return bytes(out)


def parse_message(data: bytes) -> PodcastProtocolMessage:
    """Parse a server frame. Raises ValueError on anything malformed rather than guessing."""
    if len(data) < 4:
        raise ValueError("frame shorter than its header")

    header_size = (data[0] & 0x0F) * 4
    msg_type = MessageType((data[1] >> 4) & 0x0F)
    flag = MessageFlags(data[1] & 0x0F)
    message = PodcastProtocolMessage(
        msg_type,
        flag,
        Serialization((data[2] >> 4) & 0x0F),
        Compression(data[2] & 0x0F),
    )

    offset = header_size

    def take(count: int) -> bytes:
        nonlocal offset
        if offset + count > len(data):
            raise ValueError("frame truncated")
        chunk = data[offset : offset + count]
        offset += count
        return chunk

    if msg_type == MessageType.Error:
        message.error_code = struct.unpack(">I", take(4))[0]
    if flag & MessageFlags.WithEvent:
        message.event = struct.unpack(">i", take(4))[0]
        field_name = _identifier_field(message.event)
        if field_name is not None:
            value = take(struct.unpack(">I", take(4))[0]).decode("utf-8", "replace")
            setattr(message, field_name, value)

    message.payload = take(struct.unpack(">I", take(4))[0])
    return message
