"""向上游模型服务说 OpenAI 兼容的话(ADR 0088 §4)。

只做两件事:把请求发出去、把失败分成两种 ——

- **可以换一条通道再试**(`retryable`):连不上、超时、429、5xx。这些发生在上游开始生成之前,还没开始计费;
- **上游明确拒绝**:其余 4xx(参数不对、内容被拒、模型名不认)。换通道也是同样的结果,原样告诉调用方。

流怎么读、用量怎么取在 `gateway/chat.py`;这里不碰积分。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx2

from cloud.models import CloudUpstreamProvider

#: 连接上游的等待上限;读的上限按「一个 token 都没来」算,长回答本身不受它限制(流是一段段来的)。
CONNECT_TIMEOUT_SECONDS = 10.0
READ_TIMEOUT_SECONDS = 120.0
#: 上游错误回包只取这么多字给人看:别把一整页 HTML 或一份调试堆栈转给用户。
DETAIL_MAX_CHARS = 300


class UpstreamFailure(Exception):
    def __init__(self, *, retryable: bool, status: int, detail: str) -> None:
        self.retryable = retryable
        self.status = status
        self.detail = detail
        super().__init__(f"{status}: {detail}")


@dataclass(frozen=True)
class UpstreamUsage:
    input_tokens: int
    output_tokens: int


def new_client(transport: httpx2.BaseTransport | None = None) -> httpx2.Client:
    timeout = httpx2.Timeout(READ_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS)
    return httpx2.Client(transport=transport, timeout=timeout)


def open_chat(
    client: httpx2.Client, provider: CloudUpstreamProvider, *, upstream_model: str, api_key: str, body: dict[str, object]
) -> httpx2.Response:
    """发出一次 `/chat/completions`,成功(200)就把还没读的响应交回去(流式或整包都由调用方读)。"""
    request = client.build_request(
        "POST",
        f"{provider.base_url}/chat/completions",
        json={**body, "model": upstream_model},
        headers={"Authorization": f"Bearer {api_key}", "Accept": "text/event-stream, application/json"},
    )
    try:
        response = client.send(request, stream=True)
    except httpx2.TimeoutException as exc:
        raise UpstreamFailure(retryable=True, status=504, detail="timeout") from exc
    except httpx2.TransportError as exc:
        raise UpstreamFailure(retryable=True, status=502, detail=type(exc).__name__) from exc
    if response.status_code == 200:
        return response
    try:
        raw = response.read()
    finally:
        response.close()
    status = response.status_code
    raise UpstreamFailure(
        retryable=status == 429 or status >= 500,
        status=status,
        detail=_detail(raw, api_key),
    )


def _detail(raw: bytes, api_key: str) -> str:
    """上游错误里给人看的那句:OpenAI 形状的 `error.message`,不是就取开头一段。Key 万一被回显,先抹掉。"""
    text = raw.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            text = error["message"]
        elif isinstance(error, str):
            text = error
    if api_key:
        text = text.replace(api_key, "***")
    return " ".join(text.split())[:DETAIL_MAX_CHARS]


def usage_of(payload: object) -> UpstreamUsage | None:
    """OpenAI 形状的 `usage`;没有或不是数就是 None(调用方按字数估)。"""
    if not isinstance(payload, dict):
        return None
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if not isinstance(prompt, int) or not isinstance(completion, int):
        return None
    return UpstreamUsage(input_tokens=max(0, prompt), output_tokens=max(0, completion))


def generated_chars(payload: object) -> int:
    """一段回包里生成了多少字(正文 + 思考 + 工具调用参数)—— 上游没报用量时拿它估输出 token。"""
    if not isinstance(payload, dict):
        return 0
    total = 0
    for choice in payload.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        part = choice.get("delta") if isinstance(choice.get("delta"), dict) else choice.get("message")
        if not isinstance(part, dict):
            continue
        #: 思考过程各家叫法不同:DeepSeek 是 `reasoning_content`,Ollama / OpenRouter 是 `reasoning`。都是生成出来、要算钱的。
        for key in ("content", "reasoning_content", "reasoning"):
            if isinstance(part.get(key), str):
                total += len(part[key])
        for call in part.get("tool_calls") or []:
            function = call.get("function") if isinstance(call, dict) else None
            if isinstance(function, dict) and isinstance(function.get("arguments"), str):
                total += len(function["arguments"])
    return total
