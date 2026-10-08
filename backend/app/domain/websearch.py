"""Web search + page fetch for the agent.

No API key: DuckDuckGo's HTML endpoint is scraped for results, and page fetch pulls
readable text via BeautifulSoup. Read-only; both are exposed as MCP tools so the
pi agent can look things up on the web.
"""

from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

from app.core import outbound_guard
from app.core.i18n import LocalizedError

_MAX_REDIRECTS = 5
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
_DDG = "https://html.duckduckgo.com/html/"


class WebSearchError(LocalizedError, RuntimeError):
    """搜索 / 抓取失败。带文案 key(`webErr_*`)。"""


def search(query: str, count: int = 5) -> list[dict[str, str]]:
    """Return up to `count` web results as {title, url, snippet} via DuckDuckGo."""
    query = (query or "").strip()
    if not query:
        raise WebSearchError("webErr_emptyQuery")
    count = max(1, min(count, 10))
    try:
        with httpx.Client(timeout=15, headers={"User-Agent": _UA}, follow_redirects=True) as client:
            response = client.post(_DDG, data={"q": query})
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise WebSearchError("webErr_searchFailed", detail=str(exc)) from exc

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


#: 读一个网页最多收多少字节。交回去的只是前几千字,而此前整份先读进内存再截 —— 任何登录用户都能让后端去读一个
#: 几个 GB 的地址(SEC-4)。网页正文远小于这个数;超了就停,说清是太大了。
FETCH_MAX_BYTES = 8 * 1024 * 1024


def fetch(url: str, max_chars: int = 6000) -> dict[str, str]:
    """Fetch a page and return {title, text} — readable text, scripts/styles stripped.

    出口走 core/outbound_guard:只许公网(或部署允许名单里的内网地址),按解析出来的 IP 判、连的就是查过的那个 IP,
    重定向每一跳重新判 —— 此前这里自己判一遍名字、再让 httpx 自己解析一遍,DNS 第二次答 127.0.0.1 就进去了。
    """
    url = (url or "").strip()
    try:
        exchange = outbound_guard.send(
            "GET", url, headers={"User-Agent": _UA}, timeout=20, follow_redirects=True, max_redirects=_MAX_REDIRECTS,
            max_bytes=FETCH_MAX_BYTES,
        )
        response = exchange.response
        response.raise_for_status()
    except (outbound_guard.OutboundBlocked, outbound_guard.ResponseTooLarge) as exc:
        raise WebSearchError.relay(exc) from exc
    except httpx.TooManyRedirects as exc:
        raise WebSearchError("webErr_tooManyRedirects") from exc
    except httpx.HTTPError as exc:
        raise WebSearchError("webErr_fetchFailed", detail=str(exc)) from exc

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "svg"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else url
    text = " ".join((soup.body or soup).get_text(" ", strip=True).split())
    return {"title": title, "url": exchange.url, "text": text[:max_chars]}
