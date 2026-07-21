from __future__ import annotations

from fastapi import APIRouter, Response

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.head("/health", status_code=204)
def health_head() -> Response:
    """Dev process managers such as wait-on probe HTTP URLs with HEAD."""
    return Response(status_code=204)
