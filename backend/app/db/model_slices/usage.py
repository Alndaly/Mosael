"""用量与计价:每一次调用花了多少,以及按什么规则算的。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base
from app.db.model_base import new_id, now

class ProviderPricingRule(Base):
    """Versioned price rule for one provider capability.

    Pricing is deliberately outside ProviderProfile: a profile tells Mosael how to call an
    Adapter, while this table tells the usage Module how to estimate spend for a metered unit.
    """

    __tablename__ = "provider_pricing_rules"
    __table_args__ = (
        Index("idx_provider_pricing_lookup", "workspace_id", "provider_profile_id", "provider", "capability", "model"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True)
    provider_profile_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("provider_profiles.id", ondelete="CASCADE"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    capability: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    billing_unit: Mapped[str] = mapped_column(String(40), nullable=False)
    unit_amount_micros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    effective_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class ProviderUsageEvent(Base):
    """Immutable-ish metering row for a billable provider interaction.

    Task events are good for timeline display but may be pruned; this table is the durable audit
    fact source. Callers create rows through app.domain.usage, never directly.
    """

    __tablename__ = "provider_usage_events"
    __table_args__ = (
        Index("idx_provider_usage_workspace_created", "workspace_id", "created_at"),
        Index("idx_provider_usage_job", "job_id"),
        Index("idx_provider_usage_agent_message", "agent_message_id"),
        Index("uq_provider_usage_idempotency", "idempotency_key", unique=True),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    provider_profile_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("provider_profiles.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    capability: Mapped[str] = mapped_column(String(40), nullable=False)
    operation: Mapped[str] = mapped_column(String(60), nullable=False)
    source_type: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    source_id: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    agent_message_id: Mapped[str | None] = mapped_column(ForeignKey("agent_messages.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="succeeded")
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    units: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    raw_usage: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    cost_micros: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    cost_confidence: Mapped[str] = mapped_column(String(24), nullable=False, default="unknown")
    pricing_rule_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("provider_pricing_rules.id", ondelete="SET NULL"), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
