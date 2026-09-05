"""Worker ↔ host 之间那条行协议的**帧格式**。合成与识别共用。

为什么要有前缀:引擎自己会往 stdout 打 tqdm 进度条和 loguru 日志,通道里本来就有噪声。
约定一个前缀、只认带前缀的行,比"假设子进程只说我们要的话"结实得多 —— 后者会在上游某次
多打一行日志时安静地坏掉。识别那边此前是绕开这个问题的:结果写进一个临时文件,因为
"funasr 和模型下载会把进度条直接打到 stdout"。同一个问题,两种解法,而文件那种带不了进度、
也没法给常驻进程用(每次请求都要另约一个路径)。

这个文件只放**框架**:前缀、JSON 编解码、以及 `progress` / `error` 这两种两边都一样的事件。
`done` 的形状各不相同(合成给的是引擎名与产出路径,识别给的是语言与分段),所以它由各自的
协议模块声明 —— 一个能同时接受两种形状的 `done` 校验,等于什么都没校验。

**它和 workers/ 下别的文件一样是 stdlib-only、不许 import app.***:同一份代码要在应用解释器
和引擎自己那个隔离解释器里各跑一遍,后者的 sys.path 上没有本仓库
(见 workers/__init__.py 与 tests/test_workers_run_under_another_interpreter.py)。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

#: 两边都一样的那两种事件。`done` 由绑定层追加。
COMMON_KINDS = ("progress", "error")


class WorkerProtocolError(RuntimeError):
    pass


def text_field(event: Mapping[str, Any], key: str, *, what: str, allow_empty: bool = False) -> str:
    """取一个字符串字段,顺便把"它该是什么"说清楚 —— 这条报错是给改协议的人看的。"""
    value = event.get(key)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        qualifier = "a string" if allow_empty else "a non-empty string"
        raise WorkerProtocolError(f"{what} event field {key!r} must be {qualifier}")
    return value


class LineProtocol:
    """一种 worker 的行协议。

    `validate_done` 是绑定层给的:它只管 `done` 那一种事件,别的两种在这里统一校。
    """

    def __init__(
        self,
        *,
        prefix: str,
        what: str,
        validate_done: Callable[[dict[str, Any]], None],
    ) -> None:
        self.prefix = prefix
        self.what = what
        self.kinds = (*COMMON_KINDS, "done")
        self._validate_done = validate_done

    def validate(self, value: object) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise WorkerProtocolError(f"{self.what} event must be an object")
        event = dict(value)
        kind = event.get("event")
        if kind not in self.kinds:
            raise WorkerProtocolError(f"unknown {self.what} event: {kind!r}")
        if kind == "progress":
            text_field(event, "phase", what=self.what)
            fraction = event.get("fraction")
            if isinstance(fraction, bool) or not isinstance(fraction, (int, float)) or not 0 <= fraction <= 1:
                raise WorkerProtocolError(f"{self.what} progress fraction must be between 0 and 1")
            text_field(event, "message", what=self.what, allow_empty=True)
        elif kind == "done":
            self._validate_done(event)
        else:
            text_field(event, "message", what=self.what)
        return event

    def encode(self, event: Mapping[str, Any]) -> str:
        return self.prefix + json.dumps(self.validate(event), ensure_ascii=False) + "\n"

    def decode(self, line: str) -> dict[str, Any] | None:
        """不带前缀的行**不是错误** —— 那是子进程自己的日志,原样让调用方去记。"""
        if not line.startswith(self.prefix):
            return None
        try:
            value = json.loads(line[len(self.prefix) :])
        except (TypeError, ValueError) as exc:
            raise WorkerProtocolError(f"{self.what} emitted malformed JSON") from exc
        return self.validate(value)
