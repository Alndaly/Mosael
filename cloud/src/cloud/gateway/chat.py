"""网关的一次对话:预占 → 挑通道转发 → 按用量结算(ADR 0088 §2、§3、§4)。

1. `begin`:认模型、定 `max_tokens`、按上限估预占(输入按**字数**算 token —— 宁多勿少,多的结算时退),建调用记录、预占,提交。
2. `connect`:按通道顺序试;可重试的失败(连不上 / 超时 / 429 / 5xx)把那条冷却、换下一条;上游明确拒绝的不换,全额释放后
   原话告诉调用方;全都不行也全额释放。**换通道只发生在上游开始生成之前**,所以一次调用不会被两条通道各收一次钱。
3. `finish`:流读完(或被掐断)后按上游报的用量结算;上游没报就按字数估(`estimate_tokens`),写进调用记录、多退。

结算在流结束那一刻发生,那时请求的数据库会话早已还回去了 —— `finish` 自己开一个。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime

import httpx2
from sqlalchemy.orm import Session

from cloud.config import CloudConfig
from cloud.db import Database
from cloud.domain import catalog, credits
from cloud.domain.channel_keys import unseal
from cloud.errors import CloudError
from cloud.gateway.upstream import UpstreamFailure, UpstreamUsage, open_chat
from cloud.models import CloudGatewayCall, CloudUpstreamChannel


def prompt_chars(messages: list[dict[str, object]], tools: list[object] | None) -> int:
    """请求里会被上游算成输入的字数:每条消息的内容(多段内容的文字部分)+ 工具声明。"""
    total = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            total += len(content)
        elif content is not None:
            total += len(json.dumps(content, ensure_ascii=False))
        if message.get("tool_calls") is not None:
            total += len(json.dumps(message["tool_calls"], ensure_ascii=False))
    if tools:
        total += len(json.dumps(tools, ensure_ascii=False))
    return total


def estimate_tokens(chars: int) -> int:
    """上游没报用量时按字数估 token:两个字算一个(中文约一字一 token、英文约四字符一 token,取中间)。"""
    return math.ceil(chars / 2)


@dataclass(frozen=True)
class Rate:
    """预占那一刻生效的单价 —— 结算按它算(ADR 0088 §2「已经预占的调用按预占那一刻的单价结算」)。取成普通值带着走,
    不带 ORM 行:结算时请求的会话早已关了。"""

    input_per_1k: int
    output_per_1k: int


@dataclass(frozen=True)
class Begun:
    call: CloudGatewayCall
    model_id: str
    rate: Rate
    max_tokens: int
    input_chars: int


def begin(
    db: Session,
    config: CloudConfig,
    *,
    user_id: str,
    device_token_id: str,
    model_id: str,
    max_tokens: int | None,
    input_chars: int,
    at: datetime,
) -> Begun:
    if not config.channel_key:
        raise CloudError(503, "gateway_not_configured")
    listed = catalog.usable_model(db, model_id, at=at)
    if listed is None or listed.model.kind != "chat":
        raise CloudError(404, "gateway_model_unknown")
    ceiling = listed.model.max_output_tokens
    if max_tokens is not None and max_tokens > ceiling:
        raise CloudError(400, "gateway_max_tokens_too_large", max=ceiling)
    granted = max_tokens or ceiling
    reserved = credits.chat_cost(
        input_per_1k=listed.price.input_per_1k,
        output_per_1k=listed.price.output_per_1k,
        input_tokens=input_chars,
        output_tokens=granted,
    )
    call = CloudGatewayCall(
        user_id=user_id, device_token_id=device_token_id, model_id=model_id, reserved=max(reserved, 1), created_at=at
    )
    db.add(call)
    db.flush()
    credits.reserve(db, call, at=at)
    db.commit()
    rate = Rate(input_per_1k=listed.price.input_per_1k, output_per_1k=listed.price.output_per_1k)
    return Begun(call=call, model_id=model_id, rate=rate, max_tokens=granted, input_chars=input_chars)


def connect(
    db: Session,
    config: CloudConfig,
    client: httpx2.Client,
    begun: Begun,
    *,
    body: dict[str, object],
    at: datetime,
) -> tuple[CloudUpstreamChannel, httpx2.Response]:
    """按顺序试通道,交回第一条接通的和它还没读的响应。都不行就全额释放并抛错。"""
    last: UpstreamFailure | None = None
    for routed in catalog.channels_in_order(db, begun.model_id, at=at):
        channel = routed.channel
        try:
            response = open_chat(
                client,
                routed.provider,
                upstream_model=channel.upstream_model,
                api_key=unseal(config, routed.provider.api_key_encrypted),
                body=body,
            )
        except UpstreamFailure as failure:
            last = failure
            if failure.retryable:
                catalog.cool_down(channel, at=at)
                db.commit()
                continue
            _release(db, begun.call, at=at)
            raise CloudError(400, "upstream_rejected", detail=failure.detail,
                             details={"upstream_status": failure.status}) from failure
        begun.call.channel_id = channel.id
        db.commit()
        return channel, response
    _release(db, begun.call, at=at)
    raise CloudError(503, "upstream_unavailable", details={"upstream_status": last.status if last else None})


def _release(db: Session, call: CloudGatewayCall, *, at: datetime) -> None:
    credits.settle(db, call, charged=0, at=at)
    db.commit()


@dataclass(frozen=True)
class Settled:
    call_id: str
    charged: int
    input_tokens: int
    output_tokens: int
    usage_reported: bool
    credits_left: int


def finish(
    database: Database,
    *,
    call_id: str,
    rate: Rate,
    usage: UpstreamUsage | None,
    input_chars: int,
    output_chars: int,
    at: datetime,
) -> Settled:
    """按用量结算这一次(上游没报就按字数估),多预占的退回。自己开会话:流结束时请求的会话已经还了。"""
    with database.session() as db:
        call = db.get(CloudGatewayCall, call_id)
        assert call is not None
        reported = usage is not None
        input_tokens = usage.input_tokens if usage else estimate_tokens(input_chars)
        output_tokens = usage.output_tokens if usage else estimate_tokens(output_chars)
        charged = credits.chat_cost(
            input_per_1k=rate.input_per_1k,
            output_per_1k=rate.output_per_1k,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        call.input_tokens = input_tokens
        call.output_tokens = output_tokens
        call.usage_reported = reported
        credits.settle(db, call, charged=charged, at=at)
        left = credits.balance(db, call.user_id, at=at).total
        db.commit()
        return Settled(
            call_id=call.id,
            charged=call.charged,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            usage_reported=reported,
            credits_left=left,
        )
