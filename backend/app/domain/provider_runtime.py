"""Build the provider payload understood by the pi sidecar.

Agent turns and tool-free Gateway completions share this exact runtime description. Keeping it in
one Module prevents OAuth identity, catalog limits and per-model overrides from drifting between
the two execution surfaces.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai.model_catalog import cached_model
from app.domain import model_limits, provider_models
from app.domain.provider_credentials import ResolvedConnection
from app.domain.providers import pi_provider_id


def sidecar_provider(db: Session, profile: ResolvedConnection, model: str) -> dict:
    row = provider_models.get_model(db, profile.id, model)
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
        # **窗口和输出额度在这边定死,不留给 sidecar 回退。** sidecar 那侧同样有一套回退
        # (contracts/context-meter-cases.json 钉住两边形状一致),但只有这边看得到内置的
        # 查证表和用户在模型设置里填的值 —— 把"不知道"发过去,sidecar 只能按未知云模型猜,
        # 而界面显示的是这边算出来的数,两个数就对不上了。
        catalog = cached_model(profile.base_url or "", profile.api_key or "", model)
        resolved = model_limits.resolve(
            model_id=model,
            base_url=profile.base_url or "",
            vendor=profile.vendor,
            override_window=row.context_window if row else None,
            override_output=row.max_output_tokens if row else None,
            catalog_window=catalog.context_window if catalog else None,
            catalog_output=catalog.max_output_tokens if catalog else None,
        )
        payload["context_window"] = resolved.effective_context_window
        payload["max_output_tokens"] = resolved.effective_max_output_tokens
    payload.update(provider_models.runtime_limits(row))
    return payload
