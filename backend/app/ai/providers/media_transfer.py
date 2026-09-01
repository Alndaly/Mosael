"""Safe transfer of provider input/output media across HTTP trust boundaries.

Provider API clients carry bearer/API-key headers. Generated assets usually live on a
pre-signed object-storage URL, and user-supplied source URLs may point anywhere. Reusing the
API client for either leaks credentials (or invalidates the signature). This module is the
single seam that decides whether a hop is trusted and drops headers again after a cross-origin
redirect.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from app.core.http_retry import RetryingClient

_MAX_REDIRECTS = 5


@dataclass(frozen=True)
class DownloadedBytes:
    data: bytes
    content_type: str


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(url)
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme.lower() == "https" else 80 if parsed.scheme.lower() == "http" else None
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), port


def trusted_headers_for_url(url: str, trusted_base_url: str, headers: dict[str, str] | None) -> dict[str, str]:
    """Return credentials only when the absolute URL is exactly same-origin as the API."""
    if not headers or not trusted_base_url or _origin(url) != _origin(trusted_base_url):
        return {}
    return dict(headers)


def _redirect_target(current: str, response) -> str | None:
    if not response.is_redirect:
        return None
    location = str(response.headers.get("location") or "").strip()
    return urljoin(current, location) if location else None


def download_to_path(
    url: str,
    target: Path,
    *,
    timeout: float = 180,
    trusted_base_url: str = "",
    trusted_headers: dict[str, str] | None = None,
) -> str:
    """Stream a remote asset to disk without carrying credentials across origins."""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f"{target.name}.part")
    current = str(url)
    try:
        for _hop in range(_MAX_REDIRECTS + 1):
            headers = trusted_headers_for_url(current, trusted_base_url, trusted_headers)
            with RetryingClient(timeout=timeout, headers=headers, follow_redirects=False) as client:
                with client.stream("GET", current) as response:
                    redirected = _redirect_target(current, response)
                    if redirected is not None:
                        current = redirected
                        continue
                    response.raise_for_status()
                    with partial.open("wb") as handle:
                        for chunk in response.iter_bytes():
                            handle.write(chunk)
                    partial.replace(target)
                    return str(response.headers.get("content-type") or "").split(";", 1)[0].strip()
        raise RuntimeError(f"Too many redirects while downloading media: {url}")
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def fetch_bytes(
    url: str,
    *,
    timeout: float = 120,
    max_bytes: int = 64 * 1024 * 1024,
    trusted_base_url: str = "",
    trusted_headers: dict[str, str] | None = None,
) -> DownloadedBytes:
    """Fetch a bounded source asset for APIs that require inline/multipart bytes."""
    current = str(url)
    for _hop in range(_MAX_REDIRECTS + 1):
        headers = trusted_headers_for_url(current, trusted_base_url, trusted_headers)
        with RetryingClient(timeout=timeout, headers=headers, follow_redirects=False) as client:
            with client.stream("GET", current) as response:
                redirected = _redirect_target(current, response)
                if redirected is not None:
                    current = redirected
                    continue
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise ValueError(f"Remote media exceeds {max_bytes} bytes")
                return DownloadedBytes(
                    bytes(body),
                    str(response.headers.get("content-type") or "").split(";", 1)[0].strip(),
                )
    raise RuntimeError(f"Too many redirects while downloading media: {url}")


__all__ = ["DownloadedBytes", "download_to_path", "fetch_bytes", "trusted_headers_for_url"]
