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

import datetime as dt
import hashlib
import hmac
import logging

import httpx

logger = logging.getLogger(__name__)

HOST = "open.volcengineapi.com"
REGION = "cn-beijing"
SERVICE = "speech_saas_prod"
TIMEOUT_SECONDS = 15
#: The families a voice can belong to. Each is queried separately — there is no "all" — and
#: the results merged, because a voice's family is exactly what synthesis needs back.
RESOURCE_FAMILIES = ("seed-tts-2.0", "seed-tts-1.0", "seed-icl-2.0")


class VolcOpenAPIError(RuntimeError):
    """Raised when the OpenAPI refuses the request, carrying 火山's own message."""


def _sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _signed_headers(ak: str, sk: str, query: str, body: bytes) -> dict[str, str]:
    """Build 火山's SigV4-style Authorization header.

    Chained derivation (date → region → service → request) means the signing key never
    equals the secret, so a leaked signature does not leak the credential.
    """
    now = dt.datetime.now(dt.UTC)
    x_date = now.strftime("%Y%m%dT%H%M%SZ")
    short_date = x_date[:8]
    payload_hash = hashlib.sha256(body).hexdigest()

    signed_header_names = "host;x-content-sha256;x-date"
    canonical_request = "\n".join(
        [
            "POST",
            "/",
            query,
            f"host:{HOST}",
            f"x-content-sha256:{payload_hash}",
            f"x-date:{x_date}",
            "",
            signed_header_names,
            payload_hash,
        ]
    )
    scope = f"{short_date}/{REGION}/{SERVICE}/request"
    string_to_sign = "\n".join(
        ["HMAC-SHA256", x_date, scope, hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()]
    )

    signing_key = _sign(_sign(_sign(sk.encode("utf-8"), short_date), REGION), SERVICE)
    signing_key = _sign(signing_key, "request")
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    return {
        "Host": HOST,
        "Content-Type": "application/json",
        "X-Date": x_date,
        "X-Content-Sha256": payload_hash,
        "Authorization": (
            f"HMAC-SHA256 Credential={ak}/{scope}, "
            f"SignedHeaders={signed_header_names}, Signature={signature}"
        ),
    }


def _error_message(payload: dict) -> str:
    error = (payload.get("ResponseMetadata") or {}).get("Error") or {}
    code = error.get("Code") or ""
    message = error.get("Message") or ""
    return f"{code} {message}".strip() or "火山 OpenAPI 返回了未知错误"


def list_speakers(ak: str, sk: str, resource_id: str, *, page_limit: int = 100, max_pages: int = 20) -> list[dict]:
    """Every voice the account may use in one resource family.

    Paginated defensively: an account with a large voice catalogue would otherwise silently
    return only the first page, which looks like "these are all my voices".
    """
    if not ak or not sk:
        raise VolcOpenAPIError("需要账号的 AK / SK 才能拉取音色列表")

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
                raise VolcOpenAPIError(f"火山 OpenAPI 返回了非 JSON 响应({response.status_code})") from exc
            # Errors arrive inside a 4xx body rather than as a bare status, so the body is
            # the thing to read either way.
            if response.status_code >= 400 or (payload.get("ResponseMetadata") or {}).get("Error"):
                raise VolcOpenAPIError(_error_message(payload))
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
