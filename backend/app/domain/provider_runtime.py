"""Build the provider payload understood by the pi sidecar.

Agent turns and tool-free Gateway completions share this exact runtime description. Keeping it in
one Module prevents OAuth identity, catalog limits and per-model overrides from drifting between
the two execution surfaces.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai.model_catalog import cached_model
from app.domain import provider_models
from app.domain.provider_credentials import ResolvedProvider
from app.domain.providers import pi_provider_id


def sidecar_provider(db: Session, profile: ResolvedProvider, model: str) -> dict:
    payload: dict = {
        "base_url": profile.base_url,
        "api_key": profile.api_key,
        "vendor": profile.vendor,
        "profile_id": profile.id,
    }
    if profile.auth_type == "oauth":
        payload["pi_provider"] = pi_provider_id(profile.vendor)
        payload["credential"] = profile.oauth_credential
    else:
        catalog = cached_model(profile.base_url or "", profile.api_key or "", model)
        payload["context_window"] = catalog.context_window if catalog else None
        payload["max_output_tokens"] = catalog.max_output_tokens if catalog else None
    payload.update(provider_models.runtime_limits(provider_models.get_model(db, profile.id, model)))
    return payload
