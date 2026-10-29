"""网关的 HTTP 入口(ADR 0088 §3)。**鉴权只认设备令牌**(`gateway/deps`)。

- `GET /gateway/me`:这枚令牌是谁(桌面端「测试连接」用);
- `GET /gateway/catalog`:此刻能用的模型和积分单价,加上这个用户的积分余额(按批次、先到期的在前)与下一批何时发;
- `POST /gateway/chat`:对话。请求体是 OpenAI 的形状(`model` 是网关目录里的 id),`stream` 缺省为真:

  流照上游原样转回(SSE);在上游的 `data: [DONE]` 之前多一个 `event: mosael.usage`,带这次扣了多少积分、还剩多少。
  非流式时回包里多一格 `mosael`,内容相同。积分不够是 402(`details` 里有差多少、下一批何时发)。
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


@router.get("/catalog")
def get_catalog(device: CurrentDevice, db: DbSession) -> dict[str, object]:
    at = now()
    listed = catalog.listed_models(db, at=at)
    current = credits.balance(db, device.user.id, at=at)
    # 读余额会把到期的月度批次 / 过期清零补记下来:这是账,要落库。
    db.commit()
    return {
        "models": [
            {
                "id": one.model.id,
                "label": one.model.label,
                "kind": one.model.kind,
                "max_output_tokens": one.model.max_output_tokens,
                "price": {"input_per_1k": one.price.input_per_1k, "output_per_1k": one.price.output_per_1k},
            }
            for one in listed
        ],
        "credits": {
            "total": current.total,
            "batches": [
                {"remaining": one.remaining, "expires_at": one.expires_at.isoformat(), "source": one.source}
                for one in current.batches
            ],
            "next_grant_at": current.next_grant_at.isoformat() if current.next_grant_at else None,
            "plan": current.plan_name,
        },
    }


class ChatMessage(BaseModel):
    #: 消息上的其余字段(`name`、`tool_call_id`、`tool_calls` …)原样转给上游。
    model_config = ConfigDict(extra="allow")

    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str | list[Any] | None = None


class ChatIn(BaseModel):
    model: str = Field(min_length=1, max_length=64)
    messages: list[ChatMessage] = Field(min_length=1)
    max_tokens: int | None = Field(default=None, ge=1)
    stream: bool = True
    temperature: float | None = None
    top_p: float | None = None
    stop: str | list[str] | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any = None
    response_format: dict[str, Any] | None = None


@router.post("/chat")
def post_chat(body: ChatIn, request: Request, device: CurrentDevice, db: DbSession, config: CurrentConfig):
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
        out["mosael"] = _settled_view(settled)
        return JSONResponse(out, headers={"X-Mosael-Call-Id": call_id})
    return StreamingResponse(
        _relay(database, client, response, begun, call_id),
        media_type="text/event-stream",
        headers={"X-Mosael-Call-Id": call_id, "Cache-Control": "no-store"},
    )


def _relay(database, client: httpx2.Client, response: httpx2.Response, begun: chat.Begun, call_id: str) -> Iterator[str]:
    """把上游的 SSE 一行行原样转回,边转边记用量;结束(或被掐断)时结算。"""
    usage = None
    output_chars = 0
    upstream_done = False
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
            if line.startswith("data:"):
                data = line[5:].strip()
                if data == "[DONE]":
                    upstream_done = True
                    continue
                try:
                    parsed = json.loads(data)
                except ValueError:
                    parsed = None
                usage = usage_of(parsed) or usage
                output_chars += generated_chars(parsed)
            yield f"{line}\n"
        settled = settle()
        yield f"event: mosael.usage\ndata: {json.dumps(_settled_view(settled))}\n\n"
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
