from __future__ import annotations

from fastapi import APIRouter, Response
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import CredentialSetRequest, CredentialStatusOut
from app.db.models import Credential

router = APIRouter(tags=["settings"])

KNOWN_PROVIDERS = ["alibaba", "bytedance", "openai", "google", "kuaishou"]


@router.get("/settings/credentials", response_model=list[CredentialStatusOut])
def list_credentials(db: DbSession, user: CurrentUser) -> list[CredentialStatusOut]:
    """Secrets never leave the backend — only configured-status and a hint."""
    stored = {credential.provider: credential for credential in db.scalars(select(Credential))}
    providers = sorted(set(KNOWN_PROVIDERS) | set(stored))
    return [
        CredentialStatusOut(
            provider=provider,
            configured=provider in stored,
            hint=f"…{stored[provider].secret[-4:]}" if provider in stored else "",
        )
        for provider in providers
    ]


@router.put("/settings/credentials", response_model=CredentialStatusOut)
def set_credential(body: CredentialSetRequest, db: DbSession, user: CurrentUser) -> CredentialStatusOut:
    credential = db.get(Credential, body.provider)
    if credential is None:
        credential = Credential(provider=body.provider, secret=body.secret)
        db.add(credential)
    else:
        credential.secret = body.secret
    db.commit()
    return CredentialStatusOut(provider=body.provider, configured=True, hint=f"…{body.secret[-4:]}")


@router.delete("/settings/credentials/{provider}", status_code=204)
def delete_credential(provider: str, db: DbSession, user: CurrentUser) -> Response:
    credential = db.get(Credential, provider)
    if credential is not None:
        db.delete(credential)
        db.commit()
    return Response(status_code=204)
