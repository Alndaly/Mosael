"""首页那句古诗:向「今日诗词」取一句。

**为什么走后端而不是浏览器直连**:

1. 出站代理。用户配的代理是给后端进程用的(见 domain/network),前端 fetch 走不到它 ——
   在需要代理的网络里,直连的结果是首页每次都静默降级到本地列表。
2. token 只换一次。今日诗词是 token + sentence 两步,token 换一次能用很久;放前端就变成
   每个客户端各存一份、各自续期,而这件事没有任何理由分散。
3. 断网不该让首页少一块。这里失败就抛,前端回落到本地那份精选列表 —— **本地优先**是这个
   应用的底色,首页尤其不该因为一次网络抖动而空一格。

不做缓存 TTL:用户点刷新就是想换一句,缓存住等于把刷新按钮变成摆设。token 才需要复用。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import httpx

from app.domain.ai_retry import RetryingClient

TOKEN_URL = "https://v2.jinrishici.com/token"
SENTENCE_URL = "https://v2.jinrishici.com/sentence"
TIMEOUT_SECONDS = 6

_token_lock = threading.Lock()
_token: str | None = None


class PoemUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Poem:
    text: str
    author: str
    source: str
    dynasty: str = ""


def _client() -> httpx.Client:
    # 借统一的出站客户端吃到代理配置;重试压到 0 —— 一句诗不值得为它多等两轮退避,
    # 失败就让前端用本地那份。
    return RetryingClient(timeout=TIMEOUT_SECONDS, max_retries=0)


def _fetch_token(client: httpx.Client) -> str:
    response = client.get(TOKEN_URL)
    response.raise_for_status()
    token = str((response.json() or {}).get("data") or "").strip()
    if not token:
        raise PoemUnavailable("今日诗词没有返回 token")
    return token


def fetch_poem() -> Poem:
    """取一句。token 失效(换过设备、过期)时自动换一个再试一次。"""
    global _token
    with _client() as client:
        with _token_lock:
            token = _token
        for attempt in (0, 1):
            if not token:
                token = _fetch_token(client)
            try:
                response = client.get(SENTENCE_URL, headers={"X-User-Token": token})
                response.raise_for_status()
                payload = response.json() or {}
            except httpx.HTTPError as exc:
                # 第一次失败先当作 token 过期重来一次;第二次还失败就是真不通了。
                if attempt == 1:
                    raise PoemUnavailable(str(exc)) from exc
                token = None
                continue
            data = payload.get("data") or {}
            content = str(data.get("content") or "").strip()
            if not content:
                if attempt == 1:
                    raise PoemUnavailable("今日诗词返回了空句子")
                token = None
                continue
            with _token_lock:
                _token = str(payload.get("token") or token)
            origin = data.get("origin") or {}
            return Poem(
                text=content,
                author=str(origin.get("author") or "").strip(),
                source=str(origin.get("title") or "").strip(),
                dynasty=str(origin.get("dynasty") or "").strip(),
            )
    raise PoemUnavailable("今日诗词不可达")
