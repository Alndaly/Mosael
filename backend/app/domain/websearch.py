"""Web search + page fetch for the agent.

No API key: DuckDuckGo's HTML endpoint is scraped for results, and page fetch pulls
readable text via BeautifulSoup. Read-only; both are exposed as MCP tools so the
pi agent can look things up on the web.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

_MAX_REDIRECTS = 5
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
_DDG = "https://html.duckduckgo.com/html/"


class WebSearchError(RuntimeError):
    pass


def search(query: str, count: int = 5) -> list[dict[str, str]]:
    """Return up to `count` web results as {title, url, snippet} via DuckDuckGo."""
    query = (query or "").strip()
    if not query:
        raise WebSearchError("query 不能为空")
    count = max(1, min(count, 10))
    try:
        with httpx.Client(timeout=15, headers={"User-Agent": _UA}, follow_redirects=True) as client:
            response = client.post(_DDG, data={"q": query})
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise WebSearchError(f"搜索请求失败: {exc}") from exc

    soup = BeautifulSoup(response.text, "html.parser")
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for node in soup.select(".result__body, .web-result"):
        if node.select_one(".badge--ad") or "result--ad" in (node.get("class") or []):
            continue  # skip sponsored results
        link = node.select_one("a.result__a")
        if link is None:
            continue
        url = link.get("href", "")
        title = link.get_text(" ", strip=True)
        if not url or not title or "duckduckgo.com/y.js" in url or "ad_domain" in url:
            continue
        if url in seen:
            continue
        seen.add(url)
        snippet = node.select_one(".result__snippet")
        results.append({"title": title, "url": url, "snippet": snippet.get_text(" ", strip=True) if snippet else ""})
        if len(results) >= count:
            break
    return results


def _is_public_http_url(url: str) -> bool:
    """Block non-http(s) schemes and requests to loopback / private / link-local hosts (SSRF guard)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
    return True


def fetch(url: str, max_chars: int = 6000) -> dict[str, str]:
    """Fetch a page and return {title, text} — readable text, scripts/styles stripped."""
    url = (url or "").strip()
    if not _is_public_http_url(url):
        raise WebSearchError("只能抓取公网 http/https 页面(已拦截内网/本机地址)")
    # Follow redirects by hand, re-checking every hop. _is_public_http_url only ever saw the
    # URL the caller supplied, so a public page answering 302 http://127.0.0.1:8800/... — or a
    # cloud metadata address — walked straight through the guard that exists to stop exactly
    # that. The check has to apply to wherever the request actually ends up.
    try:
        with httpx.Client(timeout=20, headers={"User-Agent": _UA}, follow_redirects=False) as client:
            current = url
            for _ in range(_MAX_REDIRECTS + 1):
                response = client.get(current)
                if not response.is_redirect:
                    break
                target = str(response.next_request.url) if response.next_request else ""
                if not _is_public_http_url(target):
                    raise WebSearchError("该页面跳转到了内网/本机地址,已拦截")
                current = target
            else:
                raise WebSearchError("跳转次数过多")
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise WebSearchError(f"抓取失败: {exc}") from exc

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "svg"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else url
    text = " ".join((soup.body or soup).get_text(" ", strip=True).split())
    return {"title": title, "url": str(response.url), "text": text[:max_chars]}
