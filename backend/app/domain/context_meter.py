"""会话当前的上下文水位。

**为什么后端也要算一份**:sidecar 里那份(agent-sidecar/src/compaction.ts)是用来**决定压不压**
的,只在跑一轮时才有机会算。而界面上的水位要在"还没开口"时就能看 —— 打开一个旧会话、刚换过
模型、上一轮失败了,这些时候都没有新的一轮可以回报。挂在消息 payload 上等于"必须先成功跑一轮
才看得到",而想知道"还能聊多久"的时刻恰恰在那之前。

两份实现必须保持同一套锚点规则,所以这里逐条对齐 compaction.ts,改一处就要改另一处:

  1. 以最近一条带 usage 的 assistant 消息为锚,取它的 input+output —— 那是供应商上次
     **实际看到**的量,比我们估算准得多;
  2. 只估算锚之后新增的消息;
  3. 一条 usage 都没有就整段估算。

不合并成一份的原因是它们跨运行时:压缩发生在 Node 侧的 pi 循环里,展示发生在 Python 侧的
HTTP 响应里,中间隔着一次进程边界。
"""

from __future__ import annotations

import json
import math
from typing import Any

#: 与 compaction.ts 的 CHARS_PER_TOKEN 一致。中英混排的粗略经验值。
CHARS_PER_TOKEN = 3.5


def _text_of(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                if isinstance(part.get("text"), str):
                    parts.append(part["text"])
                else:
                    # 工具参数与结果往往是最占地方的那部分,不能漏算。
                    payload = part.get("input") or part.get("output") or part.get("result") or ""
                    parts.append(json.dumps(payload, ensure_ascii=False) if payload else "")
        return " ".join(parts)
    return "" if content is None else json.dumps(content, ensure_ascii=False)


def estimate_tokens(message: Any) -> int:
    """向上取整,与 compaction.ts 的 Math.ceil 对齐。"""
    return math.ceil(len(_text_of(message)) / CHARS_PER_TOKEN)


def context_tokens(messages: Any) -> int:
    """当前上下文占了多少 token。messages 是 pi 的消息数组(session.adapter_state)。"""
    if not isinstance(messages, list) or not messages:
        return 0
    anchor = -1
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        usage = message.get("usage")
        if isinstance(usage, dict) and (usage.get("input") or usage.get("output")):
            anchor = index
            break
    if anchor < 0:
        return sum(estimate_tokens(message) for message in messages)
    usage = messages[anchor]["usage"]
    total = int(usage.get("input") or 0) + int(usage.get("output") or 0)
    for index in range(anchor + 1, len(messages)):
        total += estimate_tokens(messages[index])
    return total
