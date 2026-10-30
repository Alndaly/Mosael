"""网关的模型目录、积分单价与上游通道(ADR 0088 §3、§4)。

- 一个模型对外是一个 id(桌面端选的就是它);**列不列出来**看三件事:启用了、此刻有生效的单价、至少一条启用的通道。
- 单价带生效时间,调价是加一行;一次调用按它预占那一刻生效的那一行算。
- 通道按优先级排;冷却中的排到最后(全都在冷却时照样按优先级试 —— 总比直接拒绝好)。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud.config import CloudConfig
from cloud.domain.channel_keys import seal
from cloud.models import CloudGatewayModel, CloudModelPrice, CloudUpstreamChannel

#: 一条通道回了 429 / 5xx / 超时之后歇多久。
CHANNEL_COOLDOWN = timedelta(seconds=60)


def upsert_model(
    db: Session, *, model_id: str, label: str, kind: str, max_output_tokens: int, enabled: bool = True, sort_order: int = 0
) -> CloudGatewayModel:
    model = db.get(CloudGatewayModel, model_id)
    if model is None:
        model = CloudGatewayModel(id=model_id)
        db.add(model)
    model.label = label
    model.kind = kind
    model.max_output_tokens = max_output_tokens
    model.enabled = enabled
    model.sort_order = sort_order
    db.flush()
    return model


def set_price(
    db: Session, *, model_id: str, input_per_1k: int, output_per_1k: int, effective_from: datetime
) -> CloudModelPrice:
    price = CloudModelPrice(
        model_id=model_id, input_per_1k=input_per_1k, output_per_1k=output_per_1k, effective_from=effective_from
    )
    db.add(price)
    db.flush()
    return price


def current_price(db: Session, model_id: str, *, at: datetime) -> CloudModelPrice | None:
    return db.scalars(
        select(CloudModelPrice)
        .where(CloudModelPrice.model_id == model_id, CloudModelPrice.effective_from <= at)
        .order_by(CloudModelPrice.effective_from.desc())
    ).first()


def add_channel(
    db: Session,
    config: CloudConfig,
    *,
    model_id: str,
    base_url: str,
    upstream_model: str,
    api_key: str,
    priority: int = 0,
    note: str = "",
) -> CloudUpstreamChannel:
    channel = CloudUpstreamChannel(
        model_id=model_id,
        protocol="openai",
        base_url=base_url.rstrip("/"),
        upstream_model=upstream_model,
        api_key_encrypted=seal(config, api_key),
        priority=priority,
        note=note,
    )
    db.add(channel)
    db.flush()
    return channel


def replace_channel_key(db: Session, config: CloudConfig, channel: CloudUpstreamChannel, api_key: str) -> None:
    channel.api_key_encrypted = seal(config, api_key)
    db.flush()


def channels_in_order(db: Session, model_id: str, *, at: datetime) -> list[CloudUpstreamChannel]:
    """这个模型可试的通道:没在冷却的按优先级在前,冷却中的按优先级排在后面。"""
    found = db.scalars(
        select(CloudUpstreamChannel)
        .where(CloudUpstreamChannel.model_id == model_id, CloudUpstreamChannel.enabled.is_(True))
        .order_by(CloudUpstreamChannel.priority, CloudUpstreamChannel.created_at)
    ).all()
    cooling = [one for one in found if one.cooldown_until is not None and one.cooldown_until > at]
    return [one for one in found if one not in cooling] + cooling


def cool_down(channel: CloudUpstreamChannel, *, at: datetime) -> None:
    channel.cooldown_until = at + CHANNEL_COOLDOWN


@dataclass(frozen=True)
class ListedModel:
    model: CloudGatewayModel
    price: CloudModelPrice


def listed_models(db: Session, *, at: datetime) -> list[ListedModel]:
    """此刻能用的模型:启用、有生效单价、至少一条启用的通道。"""
    listed: list[ListedModel] = []
    models = db.scalars(
        select(CloudGatewayModel)
        .where(CloudGatewayModel.enabled.is_(True))
        .order_by(CloudGatewayModel.sort_order, CloudGatewayModel.id)
    ).all()
    for model in models:
        price = current_price(db, model.id, at=at)
        if price is None or not channels_in_order(db, model.id, at=at):
            continue
        listed.append(ListedModel(model=model, price=price))
    return listed


def usable_model(db: Session, model_id: str, *, at: datetime) -> ListedModel | None:
    return next((one for one in listed_models(db, at=at) if one.model.id == model_id), None)
