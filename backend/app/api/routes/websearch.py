from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUser
from app.domain.websearch import WebSearchError, fetch, search

router = APIRouter(tags=["websearch"])


@router.get("/websearch")
def web_search(user: CurrentUser, q: str = Query(..., min_length=1), count: int = Query(5, ge=1, le=10)) -> dict:
    """Search the web (DuckDuckGo) → {results: [{title, url, snippet}]}. Read-only."""
    try:
        return {"results": search(q, count)}
    except WebSearchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/webfetch")
def web_fetch(user: CurrentUser, url: str = Query(..., min_length=1)) -> dict:
    """Fetch a public web page's readable text → {title, url, text}. Read-only."""
    try:
        return fetch(url)
    except WebSearchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
