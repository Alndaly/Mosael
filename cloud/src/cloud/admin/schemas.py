"""管理端请求体。响应全部显式组装,不直接序列化 ORM。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

RoleName = Literal["member", "admin"]


class RoleIn(BaseModel):
    role: RoleName


class GiftIn(BaseModel):
    credits: int = Field(gt=0, le=1_000_000)
    days: int = Field(gt=0, le=3650)
    note: str = Field(default="", max_length=200)


class SubscribeIn(BaseModel):
    plan: str = Field(min_length=1, max_length=64)


class ModelIn(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    label: str = Field(min_length=1, max_length=80)
    max_output_tokens: int = Field(gt=0, le=1_000_000)
    sort_order: int = 0
    enabled: bool = True


class ModelPatch(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    max_output_tokens: int = Field(gt=0, le=1_000_000)
    sort_order: int = 0
    enabled: bool = True


class PriceIn(BaseModel):
    input_per_1k: int = Field(ge=0, le=1_000_000)
    output_per_1k: int = Field(ge=0, le=1_000_000)
    effective_from: datetime | None = None


class ChannelIn(BaseModel):
    model_id: str = Field(min_length=1, max_length=64)
    base_url: str = Field(min_length=1, max_length=500)
    upstream_model: str = Field(min_length=1, max_length=120)
    api_key: str = Field(min_length=1, max_length=1000)
    priority: int = 0
    note: str = Field(default="", max_length=200)


class ChannelPatch(BaseModel):
    upstream_model: str = Field(min_length=1, max_length=120)
    priority: int = 0
    note: str = Field(default="", max_length=200)
    enabled: bool = True
    api_key: str = Field(default="", max_length=1000)


class PlanPatch(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    period: Literal["month", "quarter", "year"]
    monthly_credits: int = Field(gt=0, le=10_000_000)
    credit_ttl_days: int = Field(gt=0, le=3650)
    on_sale: bool = True
    price_cents: int | None = Field(default=None, gt=0)


class PlanIn(PlanPatch):
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")
