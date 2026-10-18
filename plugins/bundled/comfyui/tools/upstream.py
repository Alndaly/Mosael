"""ComfyUI 上游最新 release:联网查 GitHub,查不到就**明说查不到**(ADR 0073)。

    {"op": "service_versions", "directory", "check_upstream": true}
        → 除了装着哪个,还多一份 `upstream`:上游最新是哪个 tag / 版本、发布说明要点、什么时候查的、查不到为什么

**只用官方 GitHub**:`api.github.com/repos/comfyanonymous/ComfyUI/releases/latest`,带 `Accept` 和
`User-Agent`(GitHub API 会拒绝没有 UA 的请求),8 秒超时。跳转只许在官方主机之间(`pinned.OFFICIAL_HOSTS`)。

**查不到不是「已最新」**:offline(离线 / 超时 / 网络)、rate_limited(403 / 429,未认证 60 次一小时)、not_found(404)、
error(回答看不懂、tag 认不出)。这四种都把 `version` / `tag` 留空、给一句按读的人的语言说的原因;调用方据此
退回内置的钉死表或者什么都不升 —— **绝不**把空的上游版本说成「已经是最新的」。

上游 release 的正文是 Markdown:`_notes` 只取前几条 bullet 当「发布说明要点」,不搬一整篇。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from urllib import error as urlerror
from urllib import request

import pinned
from lines import say

#: 官方 releases API(仓库现在是 Comfy-Org/ComfyUI,旧地址会 301 过去;跳转由官方主机白名单接着)。
RELEASES_URL = "https://api.github.com/repos/comfyanonymous/ComfyUI/releases/latest"
#: 查一次最多等多久:版本那一行等着它,不能像下载那样等两分钟。
TIMEOUT_SECONDS = 8
#: GitHub API 要 User-Agent;带一个能认出是 Mosael 的。
USER_AGENT = "mosael-comfyui-plugin (+https://mosael.com)"
HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT, "X-GitHub-Api-Version": "2022-11-28"}
#: 回答最多读多少字节(release 的正文几 KB;再大就不是我们要的那一页)。
MAX_RESPONSE = 2 * 1024 * 1024
STATUSES = ("ok", "offline", "rate_limited", "not_found", "error", "not_checked")
#: `v0.41.0` / `0.41.0`。
TAG = re.compile(r"^v?(\d+(?:\.\d+)+)$")
NOTES_BULLETS = 5
NOTES_MAX = 600

#: (状态码, 响应头, 正文)。测试注入替身;生产走 `_http_get`。
Fetcher = Callable[[str, dict[str, str], float], tuple[int, Mapping[str, str], bytes]]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _http_get(locale: str) -> Fetcher:
    """真去问 GitHub:官方主机、官方跳转白名单、读有限的一段。"""

    def fetch(url: str, headers: dict[str, str], timeout: float) -> tuple[int, Mapping[str, str], bytes]:
        if not pinned.is_official(url):
            raise OSError(f"not an official GitHub address: {url}")
        req = request.Request(url, headers=headers)  # noqa: S310 — 上面刚核过是官方主机
        opener = request.build_opener(pinned._official_redirect(locale))
        try:
            with opener.open(req, timeout=timeout) as response:
                return response.status, dict(response.headers or {}), response.read(MAX_RESPONSE)
        except urlerror.HTTPError as exc:
            # urllib 对 4xx/5xx 抛异常而不是交回响应:状态码和正文就在这里,别当成「断网」——
            # 404(没有 release)和 403/429(限流)要说得不一样。
            try:
                return exc.code, dict(exc.headers or {}), exc.read(MAX_RESPONSE)
            finally:
                exc.close()

    return fetch


def _notes(body: object) -> str:
    """发布说明的要点:前几条 bullet,去掉 Markdown 链接和「by @谁 in …」的尾巴。"""
    bullets: list[str] = []
    for raw in str(body or "").splitlines():
        line = raw.strip()
        if not line.startswith(("* ", "- ")):
            continue
        text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line[2:].strip())
        text = re.sub(r"\s+by @\S+.*$", "", text).strip()
        if text:
            bullets.append(text)
        if len(bullets) >= NOTES_BULLETS:
            break
    return " · ".join(bullets)[:NOTES_MAX]


def _header(headers: Mapping[str, str], name: str) -> str:
    for key, value in (headers or {}).items():
        if str(key).lower() == name.lower():
            return str(value)
    return ""


def _result(status: str, checked_at: str, *, message: str = "", **fields: str) -> dict[str, str]:
    return {"status": status, "version": "", "tag": "", "notes": "", "url": "", "message": message,
            "checked_at": checked_at, **fields}


def release(locale: str, *, fetch: Fetcher | None = None, timeout: float = TIMEOUT_SECONDS) -> dict[str, str]:
    """上游最新 release 是什么;查不到就说查不到(状态 + 一句原因),不抛、不猜。"""
    checked_at = _now()
    try:
        status, headers, body = (fetch or _http_get(locale))(RELEASES_URL, dict(HEADERS), timeout)
    except (TimeoutError, OSError) as exc:
        detail = getattr(exc, "reason", None) or exc
        return _result("offline", checked_at, message=say(
            locale, f"连不上 GitHub(离线、代理或网络问题):{detail}",
            f"Couldn't reach GitHub (offline, proxy, or network problem): {detail}"))
    except Exception as exc:  # noqa: BLE001 — 替身 / 底层库抛什么都不能让版本那一行崩掉
        return _result("error", checked_at, message=say(
            locale, f"查上游最新版本时出错:{type(exc).__name__}: {exc}",
            f"Checking the latest upstream release failed: {type(exc).__name__}: {exc}"))

    if status in (403, 429):
        return _result("rate_limited", checked_at, message=say(
            locale, "GitHub 限流了(未认证的请求每小时 60 次),过一会儿再查",
            "GitHub rate-limited the request (60 unauthenticated requests per hour); check again later"))
    if status == 404:
        return _result("not_found", checked_at, message=say(
            locale, "GitHub 上说这个仓库没有发布版本", "GitHub says this repository has no release"))
    if status != 200:
        return _result("error", checked_at, message=say(
            locale, f"GitHub 的回答不是 200(状态 {status})", f"GitHub answered with status {status}, not 200"))
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return _result("error", checked_at, message=say(
            locale, "GitHub 的回答看不懂(不是 JSON)", "Couldn't read GitHub's answer (it isn't JSON)"))
    if not isinstance(data, dict):
        return _result("error", checked_at, message=say(
            locale, "GitHub 的回答看不懂(不是一条 release)", "Couldn't read GitHub's answer (it isn't a release)"))

    tag = str(data.get("tag_name") or "").strip()
    found = TAG.match(tag)
    if not found:
        return _result("error", checked_at, message=say(
            locale, f"GitHub 给的 tag 认不出:{tag or '(空)'}", f"GitHub's tag isn't a version: {tag or '(empty)'}"))
    url = str(data.get("html_url") or "").strip()
    if not url.startswith("https://github.com/"):
        url = f"https://github.com/Comfy-Org/ComfyUI/releases/tag/{tag}"
    return _result("ok", checked_at, version=found.group(1), tag=tag, notes=_notes(data.get("body")), url=url)


__all__ = ["HEADERS", "MAX_RESPONSE", "NOTES_MAX", "RELEASES_URL", "STATUSES", "TAG", "TIMEOUT_SECONDS", "USER_AGENT",
           "Fetcher", "release"]
