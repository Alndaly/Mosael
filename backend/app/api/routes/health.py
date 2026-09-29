from __future__ import annotations

from fastapi import APIRouter, Response

from app.core import lifeline
from app.core.config import app_version, settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """活着,并且说得清自己是谁(见 core/lifeline):壳据此判断端口上那个后端能不能复用。"""
    return {
        "status": "ok",
        "app": "mosael",
        "version": app_version(),
        "instance": lifeline.INSTANCE_ID,
        "data_dir_id": lifeline.data_dir_id(settings.data_dir),
    }


@router.head("/health", status_code=204)
def health_head() -> Response:
    """Dev process managers such as wait-on probe HTTP URLs with HEAD."""
    return Response(status_code=204)
