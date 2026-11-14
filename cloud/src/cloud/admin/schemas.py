"""管理端请求体。响应全部显式组装,不直接序列化 ORM。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

RoleName = Literal["member", "admin"]


class IpBanIn(BaseModel):
    ip: str = Field(min_length=1, max_length=64)
    reason: str = Field(default="", max_length=200)


class AdjustIn(BaseModel):
    delta: int = Field(ge=-10_000_000, le=10_000_000)
    days: int = Field(default=30, ge=1, le=3650)
    note: str = Field(default="", max_length=200)


class BanIn(BaseModel):
    reason: str = Field(default="", max_length=200)


class UserPatch(BaseModel):
    """管理台修改公开身份;邮箱 / 手机号会换登录方式,不在这里改。"""

    display_name: str | None = None
    handle: str | None = None


class RoleIn(BaseModel):
    role: RoleName


class GiftIn(BaseModel):
    credits: int = Field(gt=0, le=1_000_000)
    days: int = Field(gt=0, le=3650)
    note: str = Field(default="", max_length=200)


class SubscribeIn(BaseModel):
    plan: str = Field(min_length=1, max_length=64)


class ModelIn(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    interaction: Literal["stream", "job"] = "stream"
    capability: dict[str, object] = Field(default_factory=dict)
    max_output_tokens: int | None = Field(default=None, gt=0, le=1_000_000)
    sort_order: int = 0
    enabled: bool = True


class ModelPatch(ModelIn):
    pass


class PriceIn(BaseModel):
    #: 计量分量,如 {"token_input": 2, "token_output": 8} 或 {"image": 2}。
    components: dict[str, int]
    effective_from: datetime | None = None


class ProviderIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    adapter: str = Field(default="openai", min_length=1, max_length=32)
    config: dict[str, object] = Field(default_factory=dict)
    base_url: str = Field(min_length=1, max_length=500)
    api_key: str = Field(default="", max_length=1000)
    note: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def check_api_key(self) -> "ProviderIn":
        if self.adapter != "comfyui" and not self.api_key:
            raise ValueError("api_key is required for this adapter")
        return self


class ProviderPatch(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    adapter: str = Field(default="openai", min_length=1, max_length=32)
    config: dict[str, object] = Field(default_factory=dict)
    note: str = Field(default="", max_length=200)
    enabled: bool = True
    api_key: str = Field(default="", max_length=1000)


class ChannelIn(BaseModel):
    model_id: str = Field(min_length=1, max_length=64)
    provider_id: str = Field(min_length=1, max_length=64)
    upstream_model: str = Field(min_length=1, max_length=120)
    priority: int = 0
    note: str = Field(default="", max_length=200)


class ChannelPatch(BaseModel):
    upstream_model: str = Field(min_length=1, max_length=120)
    priority: int = 0
    note: str = Field(default="", max_length=200)
    enabled: bool = True


class OrderRefundIn(BaseModel):
    amount_cents: int | None = Field(default=None, gt=0)
    note: str = Field(default="", max_length=300)


class PlanPatch(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    period: Literal["month", "quarter", "year"]
    monthly_credits: int = Field(gt=0, le=10_000_000)
    credit_ttl_days: int = Field(gt=0, le=3650)
    on_sale: bool = True
    price_cents: int | None = Field(default=None, gt=0)


class PlanIn(PlanPatch):
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")
