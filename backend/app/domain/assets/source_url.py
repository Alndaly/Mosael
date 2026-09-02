"""Resolve URL-imported assets without making the browser extension own library state."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Asset, Job, Transcript
from app.domain.transcripts import get_transcript_for_asset


_TRACKING_QUERY_PREFIXES = ("utm_",)
_TRACKING_QUERY_NAMES = {"fbclid", "gclid", "spm", "from", "share_source"}


def source_url_key(raw_url: str) -> str:
    """Return a stable identity for supported video URLs and a conservative generic fallback."""
    value = str(raw_url or "").strip()
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    host = (parts.hostname or "").lower()
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    path = parts.path.rstrip("/") or "/"

    if (host == "pornhub.com" or host.endswith(".pornhub.com")) and path == "/view_video.php":
        viewkey = query.get("viewkey", "").strip()
        if viewkey:
            return f"pornhub:{viewkey}"
    if host == "youtu.be":
        video_id = path.strip("/").split("/", 1)[0]
        if video_id:
            return f"youtube:{video_id}"
    if host == "youtube.com" or host.endswith(".youtube.com"):
        video_id = query.get("v", "").strip()
        if not video_id and path.startswith("/shorts/"):
            video_id = path.split("/", 3)[2]
        if video_id:
            return f"youtube:{video_id}"
    if host == "bilibili.com" or host.endswith(".bilibili.com"):
        segments = [segment for segment in path.split("/") if segment]
        if len(segments) >= 2 and segments[0] == "video":
            return f"bilibili:{segments[1]}"
        if len(segments) >= 3 and segments[:2] == ["bangumi", "play"]:
            return f"bilibili:{segments[2]}"

    filtered_query = [
        (name, item)
        for name, item in parse_qsl(parts.query, keep_blank_values=True)
        if name.lower() not in _TRACKING_QUERY_NAMES
        and not name.lower().startswith(_TRACKING_QUERY_PREFIXES)
    ]
    netloc = host
    if parts.port and not ((parts.scheme == "https" and parts.port == 443) or (parts.scheme == "http" and parts.port == 80)):
        netloc = f"{host}:{parts.port}"
    normalized = urlunsplit((parts.scheme.lower(), netloc, path, urlencode(sorted(filtered_query)), ""))
    return f"url:{normalized}"


def remember_asset_source(asset: Asset, raw_url: str) -> None:
    asset.media_info = {
        **(asset.media_info or {}),
        "source_url": raw_url,
        "source_url_key": source_url_key(raw_url),
    }


def _ready_transcript(db: Session, asset_id: str, workspace_id: str) -> Transcript | None:
    asset = db.get(Asset, asset_id)
    if asset is None or asset.workspace_id != workspace_id:
        return None
    transcript = get_transcript_for_asset(db, asset.id)
    return transcript if transcript is not None and transcript.status == "ready" else None


def find_transcript_by_source(db: Session, workspace_id: str, raw_url: str) -> Transcript | None:
    """Find a ready transcript, including imports created before source metadata was stored."""
    wanted = source_url_key(raw_url)
    assets = db.scalars(
        select(Asset)
        .where(Asset.workspace_id == workspace_id)
        .order_by(Asset.created_at.desc())
    )
    for asset in assets:
        info = asset.media_info or {}
        remembered = str(info.get("source_url_key") or "")
        if remembered == wanted or (info.get("source_url") and source_url_key(str(info["source_url"])) == wanted):
            transcript = _ready_transcript(db, asset.id, workspace_id)
            if transcript is not None:
                return transcript

    legacy_jobs = db.scalars(
        select(Job)
        .where(Job.workspace_id == workspace_id, Job.kind == "url_import", Job.status == "succeeded")
        .order_by(Job.created_at.desc())
    )
    for job in legacy_jobs:
        items = list((job.payload or {}).get("items") or [])
        asset_ids = list((job.result or {}).get("asset_ids") or [])
        if len(items) == 1 and asset_ids:
            pairs = [(items[0], asset_ids[0])]
        elif len(items) == len(asset_ids):
            pairs = zip(items, asset_ids, strict=True)
        else:
            continue
        for item, asset_id in pairs:
            if source_url_key(str(item.get("url") or "")) != wanted:
                continue
            transcript = _ready_transcript(db, str(asset_id), workspace_id)
            if transcript is not None:
                return transcript
    return None


__all__ = ["find_transcript_by_source", "remember_asset_source", "source_url_key"]
