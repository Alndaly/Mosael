"""火山引擎 OpenAPI — just enough of it to ask which voices an account actually has.

The voice id is not cosmetic: synthesis fails with an opaque `55000000 resource ID is
mismatched` unless the request header names the voice's family, and a hardcoded list goes
stale the moment 火山 ships a voice or the account buys one. So the list is pulled live when
the account's AK/SK are configured, and falls back to a built-in list when they are not.

This endpoint does not accept the speech API Key — it is the account-level OpenAPI, signed
with AK/SK the same way as the rest of 火山's console APIs. That signature is the only reason
this module exists; everything else here is a thin wrapper around one Action.
"""

from __future__ import annotations

from app.core.i18n import LocalizedError

import logging

import httpx

from app.ai.providers.adapters.bytedance.volcano.openapi_sign import HOST, signed_headers

logger = logging.getLogger(__name__)

SERVICE = "speech_saas_prod"
TIMEOUT_SECONDS = 15
#: The families a voice can belong to. Each is queried separately — there is no "all" — and
#: the results merged, because a voice's family is exactly what synthesis needs back.
RESOURCE_FAMILIES = ("seed-tts-2.0", "seed-tts-1.0", "seed-icl-2.0")


class VolcOpenAPIError(LocalizedError, RuntimeError):
    """Raised when the OpenAPI refuses the request, carrying 火山's own message (as `detail`, key `volcErr_*`)."""


def _signed_headers(ak: str, sk: str, query: str, body: bytes) -> dict[str, str]:
    """火山的签名住在 ai 层(音乐生成也用它,见 openapi_sign);这里只点名服务。"""
    return signed_headers(ak, sk, query, body, service=SERVICE)


def _error_message(payload: dict) -> str:
    error = (payload.get("ResponseMetadata") or {}).get("Error") or {}
    code = error.get("Code") or ""
    message = error.get("Message") or ""
    return f"{code} {message}".strip()


def _upstream_error(payload: dict) -> VolcOpenAPIError:
    said = _error_message(payload)
    return VolcOpenAPIError("volcErr_upstream", detail=said) if said else VolcOpenAPIError("volcErr_unknown")


def list_speakers(ak: str, sk: str, resource_id: str, *, page_limit: int = 100, max_pages: int = 20) -> list[dict]:
    """Every voice the account may use in one resource family.

    Paginated defensively: an account with a large voice catalogue would otherwise silently
    return only the first page, which looks like "these are all my voices".
    """
    if not ak or not sk:
        raise VolcOpenAPIError("volcErr_needsAkSk")

    import json

    query = "Action=ListSpeakers&Version=2025-05-20"
    speakers: list[dict] = []
    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        for page in range(1, max_pages + 1):
            body = json.dumps({"ResourceIDs": [resource_id], "Page": page, "Limit": page_limit}).encode("utf-8")
            response = client.post(
                f"https://{HOST}/?{query}", headers=_signed_headers(ak, sk, query, body), content=body
            )
            try:
                payload = response.json()
            except ValueError as exc:
                raise VolcOpenAPIError("volcErr_notJson", status=response.status_code) from exc
            # Errors arrive inside a 4xx body rather than as a bare status, so the body is
            # the thing to read either way.
            if response.status_code >= 400 or (payload.get("ResponseMetadata") or {}).get("Error"):
                raise _upstream_error(payload)
            batch = ((payload.get("Result") or {}).get("Speakers")) or []
            speakers.extend(batch)
            if len(batch) < page_limit:
                break
    return speakers


def list_all_speakers(ak: str, sk: str) -> list[dict]:
    """Merge every family, de-duplicated, each voice tagged with the family it came from.

    A family that fails is skipped rather than fatal: an account entitled to seed-tts-1.0 but
    not 2.0 should still see the voices it has, instead of an error about the ones it does not.
    """
    merged: dict[str, dict] = {}
    failures: list[str] = []
    for family in RESOURCE_FAMILIES:
        try:
            found = list_speakers(ak, sk, family)
        except VolcOpenAPIError as exc:
            logger.info("volcano ListSpeakers %s failed: %s", family, exc)
            failures.append(str(exc))
            continue
        for speaker in found:
            voice_id = speaker.get("VoiceType") or ""
            if voice_id and voice_id not in merged:
                merged[voice_id] = {**speaker, "ResourceID": speaker.get("ResourceID") or family}
    if not merged and failures:
        raise VolcOpenAPIError(failures[0])
    return list(merged.values())
