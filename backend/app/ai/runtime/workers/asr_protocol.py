"""识别 worker 与宿主之间的行协议。

帧格式住在 ``line_protocol``(合成走同一套)。这里只声明识别这一侧不同的东西:前缀,
以及 ``done`` 的形状 —— 识别的 done 给的是语言与分段,不是产出文件。

**这取代了原来的"结果写进临时文件"。** 那个做法是为了绕开 stdout 上的进度条噪声,而前缀
把同一个问题解得更直接:带前缀的才是给我们的,别的原样当日志。文件那条路还有两个走不通的
地方 —— 带不了进度,而且常驻进程每次请求都得另约一个路径。

和 workers/ 下别的文件一样:stdlib-only,不许 import ``app.*``(见 workers/__init__.py)。
"""

from __future__ import annotations

from typing import Any

if __package__:
    from .line_protocol import LineProtocol, WorkerProtocolError, text_field
else:
    # Executed directly by the ASR interpreter; its sys.path only contains this
    # directory, not the application package.
    from line_protocol import LineProtocol, WorkerProtocolError, text_field

_WHAT = "ASR worker"


def _validate_done(event: dict[str, Any]) -> None:
    """识别的产出:语言 + 分段。

    `language` 允许为空 —— 引擎不一定报得出来(whisperx 指定了语言时就不再检测),
    而"没检测到语言"和"识别失败"是两回事,不能因为前者把整次结果判失败。

    `segments` 必须是数组,但**允许为空**:一段静音的正确结果就是零段。
    """
    text_field(event, "language", what=_WHAT, allow_empty=True)
    segments = event.get("segments")
    if not isinstance(segments, list):
        raise WorkerProtocolError(f"{_WHAT} event field 'segments' must be a list")


_PROTOCOL = LineProtocol(prefix="@@MOSAEL-ASR ", what=_WHAT, validate_done=_validate_done)

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
