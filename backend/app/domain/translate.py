"""Text translation with two backends:

- **google**: Google's free (unofficial) translate endpoint — no API key, good for quick
  subtitle/caption translation. Returns the concatenated translated segments.
- **ai**: handled by the caller via an LLM provider (see the workflow translate node), so this
  module only owns the Google path + the shared language list.

Kept dependency-light (httpx only) so it can be reused by workflow nodes and, later, editor
subtitle translation.
"""
from __future__ import annotations

import httpx

_GOOGLE_URL = "https://translate.googleapis.com/translate_a/single"
_TIMEOUT = 30

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


def ai_translate(db, text: str, target: str, profile_id: str | None = None) -> str:
    """Translate via an enabled AI provider (LLM). Reused by the workflow node + the API."""
    from sqlalchemy import select

    from app.db.models import ProviderProfile

    if not text.strip():
        return ""
    profile = None
    if profile_id:
        profile = db.get(ProviderProfile, profile_id)
    if profile is None:
        profile = db.scalars(
            select(ProviderProfile).where(ProviderProfile.enabled.is_(True)).order_by(ProviderProfile.created_at)
        ).first()
    if profile is None or not profile.enabled:
        raise TranslateError("没有可用的 AI 供应商,请先在设置里添加")
    prompt = (
        f"Translate the following text into {language_label(target)} ({target}). "
        f"Output only the translation, no explanations or quotes.\n\n{text}"
    )
    try:
        response = httpx.post(
            f"{profile.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {profile.api_key}"},
            json={"model": profile.default_model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2},
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


def google_translate(text: str, target: str, source: str = "auto") -> str:
    """Free Google translate. Returns the translation, or "" for empty input."""
    if not text.strip():
        return ""
    try:
        response = httpx.get(
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
