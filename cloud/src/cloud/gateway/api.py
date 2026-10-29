"""网关的 HTTP 入口(ADR 0088 §3)。**鉴权只认设备令牌**(`gateway/deps`)。

- `GET /gateway/me`:这枚令牌是谁(桌面端「测试连接」用);
- `GET /gateway/account`:这个用户的积分(按批次、先到期的在前)、下一批何时发、套餐;
- `GET /gateway/v1/models` 与 `POST /gateway/v1/chat/completions`:**标准的 OpenAI 兼容端点**。桌面端把 Mosael Cloud
  当成一条 OpenAI 兼容连接(base_url = `…/gateway/v1`、Bearer = 设备令牌),直连对话、智能体、画板、工作流都不用另写一套。

  - 目录里每个模型带 `name`、`max_output_tokens` 和 `pricing`(OpenRouter 的形状:每 token 的价,字符串),
    `pricing.currency` 是 `CREDITS` —— 价是积分,不是美元;
  - 流照上游转回,每一块的 `model` 换成网关的 id(不把上游叫什么漏出去);**最后那块 usage**(`choices: []`)由网关结算后
    给出:`usage` 是结算用的 token 数,多一格 `mosael`(这次扣了多少积分、还剩多少)。非流式回包同样多一格 `mosael`。
    积分不够是 402(`details` 里有差多少、下一批何时发)。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, Literal

import httpx2
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from cloud.api.deps import CurrentConfig, DbSession
from cloud.domain import catalog, credits
from cloud.domain.device_tokens import device_token_view
from cloud.domain.identity import account_user
from cloud.gateway import chat
from cloud.gateway.deps import CurrentDevice
from cloud.gateway.upstream import generated_chars, new_client, usage_of
from cloud.models import now

router = APIRouter(prefix="/gateway", tags=["gateway"])


@router.get("/me")
def whoami(device: CurrentDevice) -> dict[str, object]:
    return {"user": account_user(device.user), "device": device_token_view(device.token)}


@router.get("/account")
def get_account(device: CurrentDevice, db: DbSession) -> dict[str, object]:
    at = now()
    current = credits.balance(db, device.user.id, at=at)
    # 读余额会把到期的月度批次 / 过期清零补记下来:这是账,要落库。
    db.commit()
    return {
        "credits": current.total,
        "batches": [
            {"remaining": one.remaining, "expires_at": one.expires_at.isoformat(), "source": one.source}
            for one in current.batches
        ],
        "next_grant_at": current.next_grant_at.isoformat() if current.next_grant_at else None,
        "plan": current.plan_name,
    }


#: 目录里的价是积分,不是钱。桌面端的用量账本按币种各算各的,积分是单独的一种(不和人民币、美元相加)。
CREDITS = "CREDITS"


@router.get("/v1/models")
def list_models(device: CurrentDevice, db: DbSession) -> dict[str, object]:
    """OpenAI 的 `/models` 形状。单价换成**每 token**(OpenRouter 的写法),字符串,免得浮点在 JSON 里变形。"""
    return {
        "object": "list",
        "data": [
            {
                "id": one.model.id,
                "object": "model",
                "owned_by": "mosael",
                "name": one.model.label,
                "max_output_tokens": one.model.max_output_tokens,
                "pricing": {
                    "prompt": _per_token(one.price.input_per_1k),
                    "completion": _per_token(one.price.output_per_1k),
                    "currency": CREDITS,
                },
            }
            for one in catalog.listed_models(db, at=now())
        ],
    }


def _per_token(per_1k: int) -> str:
    return f"{per_1k / 1000:.6f}".rstrip("0").rstrip(".") or "0"


class ChatMessage(BaseModel):
    #: 消息上的其余字段(`name`、`tool_call_id`、`tool_calls` …)原样转给上游。
    model_config = ConfigDict(extra="allow")

    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str | list[Any] | None = None


class ChatIn(BaseModel):
    model: str = Field(min_length=1, max_length=64)
    messages: list[ChatMessage] = Field(min_length=1)
    max_tokens: int | None = Field(default=None, ge=1)
    #: 和 OpenAI 一样**缺省不流式**:桌面端的直连对话(起标题、翻译、结构化抽取)不带这一格,等的是一整个 JSON。
    stream: bool = False
    temperature: float | None = None
    top_p: float | None = None
    stop: str | list[str] | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any = None
    response_format: dict[str, Any] | None = None


@router.post("/v1/chat/completions")
def chat_completions(body: ChatIn, request: Request, device: CurrentDevice, db: DbSession, config: CurrentConfig):
    at = now()
    messages = [one.model_dump(exclude_none=True) for one in body.messages]
    begun = chat.begin(
        db,
        config,
        user_id=device.user.id,
        device_token_id=device.token.id,
        model_id=body.model,
        max_tokens=body.max_tokens,
        input_chars=chat.prompt_chars(messages, body.tools),
        at=at,
    )
    payload = body.model_dump(exclude_none=True, exclude={"model", "messages", "max_tokens"})
    payload.update(messages=messages, max_tokens=begun.max_tokens)
    if body.stream:
        payload["stream_options"] = {"include_usage": True}
    client = new_client(request.app.state.upstream_transport)
    try:
        _channel, response = chat.connect(db, config, client, begun, body=payload, at=at)
    except BaseException:
        client.close()
        raise
    call_id = begun.call.id
    database = request.app.state.db
    if not body.stream:
        try:
            raw = response.read()
        finally:
            response.close()
            client.close()
        try:
            reply = json.loads(raw)
        except ValueError:
            reply = None
        settled = chat.finish(
            database,
            call_id=call_id,
            rate=begun.rate,
            usage=usage_of(reply),
            input_chars=begun.input_chars,
            output_chars=generated_chars(reply),
            at=now(),
        )
        out = reply if isinstance(reply, dict) else {}
        out["model"] = body.model
        out["mosael"] = _settled_view(settled)
        return JSONResponse(out, headers={"X-Mosael-Call-Id": call_id})
    return StreamingResponse(
        _relay(database, client, response, begun, call_id, model_id=body.model),
        media_type="text/event-stream",
        headers={"X-Mosael-Call-Id": call_id, "Cache-Control": "no-store"},
    )


def _relay(
    database, client: httpx2.Client, response: httpx2.Response, begun: chat.Begun, call_id: str, *, model_id: str
) -> Iterator[str]:
    """把上游的 SSE 一块块转回,边转边记用量;最后那块 usage 由网关结算后给出。结束(或被掐断)时结算。"""
    usage = None
    output_chars = 0
    upstream_done = False
    #: 上游最后那块 usage 的样子(id、created …):网关照它给出自己的那块;上游没给就照最后一块内容的样子拼一块。
    last_chunk: dict[str, Any] = {}
    #: 结算只试一次:正常读完时在这里结,掐断时在 finally 里结,结算本身出错也不再重来。
    settling_started = False

    def settle() -> chat.Settled:
        nonlocal settling_started
        settling_started = True
        return chat.finish(
            database, call_id=call_id, rate=begun.rate, usage=usage,
            input_chars=begun.input_chars, output_chars=output_chars, at=now(),
        )

    try:
        for line in response.iter_lines():
            if not line.startswith("data:"):
                yield f"{line}\n"
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                upstream_done = True
                continue
            try:
                parsed = json.loads(data)
            except ValueError:
                yield f"{line}\n"
                continue
            if not isinstance(parsed, dict):
                yield f"{line}\n"
                continue
            usage = usage_of(parsed) or usage
            output_chars += generated_chars(parsed)
            last_chunk = {key: parsed[key] for key in ("id", "object", "created", "system_fingerprint") if key in parsed}
            #: 用量由网关结算后在最后一块里给;上游这一块里的 usage 拿掉,只剩用量的那块整个不转。
            parsed.pop("usage", None)
            if not parsed.get("choices"):
                continue
            parsed["model"] = model_id
            yield f"data: {json.dumps(parsed, ensure_ascii=False)}\n"
        settled = settle()
        final = {"object": "chat.completion.chunk", **last_chunk, "model": model_id, "choices": []}
        final["usage"] = {
            "prompt_tokens": settled.input_tokens,
            "completion_tokens": settled.output_tokens,
            "total_tokens": settled.input_tokens + settled.output_tokens,
        }
        final["mosael"] = _settled_view(settled)
        yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n"
        if upstream_done:
            yield "data: [DONE]\n\n"
    finally:
        response.close()
        client.close()
        #: 桌面端中途断开(或上游流断了):按已经生成的结算 —— 上游那部分已经算钱了,没生成的预占退回。
        if not settling_started:
            settle()


def _settled_view(settled: chat.Settled) -> dict[str, object]:
    return {
        "call_id": settled.call_id,
        "charged": settled.charged,
        "input_tokens": settled.input_tokens,
        "output_tokens": settled.output_tokens,
        "usage_reported": settled.usage_reported,
        "credits_left": settled.credits_left,
    }
