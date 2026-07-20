"""Text translation with two backends:

- **google**: Google's free (unofficial) translate endpoint — no API key, good for quick
  subtitle/caption translation. Returns the concatenated translated segments.
- **ai**: handled by the caller via an LLM provider (see the workflow translate node), so this
  module only owns the Google path + the shared language list.

Kept dependency-light (httpx only) so it can be reused by workflow nodes and, later, editor
subtitle translation.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import httpx

_GOOGLE_URL = "https://translate.googleapis.com/translate_a/single"
_TIMEOUT = 30
# Translating a subtitle track means one independent network round-trip per cue, so they run
# concurrently rather than one after another. Bounded, not unbounded: Google's free endpoint
# rate-limits a burst, and a 200-cue track would otherwise open 200 sockets at once.
_MAX_PARALLEL = 8

# Target languages surfaced in the UI (google codes; the AI path takes the same codes as hints).
LANGUAGES: tuple[tuple[str, str], ...] = (
    ("en", "English"),
    ("zh-CN", "简体中文"),
    ("zh-TW", "繁體中文"),
    ("ja", "日本語"),
    ("ko", "한국어"),
    ("fr", "Français"),
    ("de", "Deutsch"),
    ("es", "Español"),
    ("ru", "Русский"),
)
_LANG_NAMES = dict(LANGUAGES)


class TranslateError(RuntimeError):
    pass


def language_label(code: str) -> str:
    return _LANG_NAMES.get(code, code)


@dataclass(frozen=True)
class AiProvider:
    """A provider resolved out of the DB, so the network calls that use it can run on other
    threads. Passing the Session itself would not be safe — a SQLAlchemy Session belongs to one
    thread, and a lazy attribute load from a worker is a race."""

    base_url: str
    api_key: str
    model: str


def resolve_ai_provider(db, profile_id: str | None = None) -> AiProvider:
    from sqlalchemy import select

    from app.db.models import ProviderProfile

    profile = None
    if profile_id:
        profile = db.get(ProviderProfile, profile_id)
    if profile is None:
        profile = db.scalars(
            select(ProviderProfile).where(ProviderProfile.enabled.is_(True)).order_by(ProviderProfile.created_at)
        ).first()
    if profile is None or not profile.enabled:
        raise TranslateError("没有可用的 AI 供应商,请先在设置里添加")
    return AiProvider(base_url=profile.base_url, api_key=profile.api_key, model=profile.default_model)


def ai_translate(db, text: str, target: str, profile_id: str | None = None) -> str:
    """Translate via an enabled AI provider (LLM). Reused by the workflow node + the API."""
    if not text.strip():
        return ""
    return ai_translate_with(resolve_ai_provider(db, profile_id), text, target)


def ai_translate_with(provider: AiProvider, text: str, target: str, client: httpx.Client | None = None) -> str:
    if not text.strip():
        return ""
    prompt = (
        f"Translate the following text into {language_label(target)} ({target}). "
        f"Output only the translation, no explanations or quotes.\n\n{text}"
    )
    try:
        response = (client or httpx).post(
            f"{provider.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {provider.api_key}"},
            json={"model": provider.model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2},
            timeout=_TIMEOUT * 2,
        )
        response.raise_for_status()
        return str(response.json()["choices"][0]["message"]["content"]).strip()
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise TranslateError(f"AI 翻译失败: {exc}") from exc


def translate(db, text: str, target: str, engine: str = "google", profile_id: str | None = None) -> str:
    """Dispatch to the requested engine."""
    if engine == "ai":
        return ai_translate(db, text, target, profile_id)
    return google_translate(text, target)


def google_translate(text: str, target: str, source: str = "auto", client: httpx.Client | None = None) -> str:
    """Free Google translate. Returns the translation, or "" for empty input."""
    if not text.strip():
        return ""
    try:
        response = (client or httpx).get(
            _GOOGLE_URL,
            params={"client": "gtx", "sl": source, "tl": target, "dt": "t", "q": text},
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise TranslateError(f"Google 翻译失败: {exc}") from exc
    # data[0] = list of [translated_segment, original_segment, ...]; join the translated parts.
    segments = data[0] if isinstance(data, list) and data else []
    return "".join(seg[0] for seg in segments if isinstance(seg, list) and seg and seg[0])


def translate_many(
    db,
    texts: list[str],
    target: str,
    engine: str = "google",
    profile_id: str | None = None,
) -> list[str]:
    """Translate a batch, running the round-trips concurrently.

    Each cue is an independent network call, so a subtitle track used to cost
    len(texts) × latency — about ten seconds for a typical track. They now overlap.

    Two things are deliberately done before the pool starts: the provider is read out of the DB
    (a Session is single-threaded), and one httpx.Client is created so the batch shares
    connections instead of repeating the TLS handshake per cue.
    """
    if not texts:
        return []
    provider = resolve_ai_provider(db, profile_id) if engine == "ai" else None
    indexed = [(i, text) for i, text in enumerate(texts) if text.strip()]
    results = [""] * len(texts)
    if not indexed:
        return results

    with httpx.Client(timeout=_TIMEOUT * 2) as client:
        def one(item: tuple[int, str]) -> tuple[int, str]:
            index, text = item
            if provider is not None:
                return index, ai_translate_with(provider, text, target, client=client)
            return index, google_translate(text, target, client=client)

        workers = min(_MAX_PARALLEL, len(indexed))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            # map() surfaces the first exception when consumed, so one failed cue still fails the
            # batch as it did before — the caller applies translations atomically either way.
            for index, translated in pool.map(one, indexed):
                results[index] = translated
    return results
