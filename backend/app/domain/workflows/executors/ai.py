"""AI 文本类节点:直连供应商 API(不产生子 job)。"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.db.models import Workflow
from app.domain.providers import require_profile
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors import register

LLM_TIMEOUT_SECONDS = 120

# 生成风格预设 → temperature(替代让用户填裸数值)。默认均衡。
_LLM_PRESET_TEMPS = {"precise": 0.1, "balanced": 0.4, "creative": 0.9}


@register("llm")
def llm(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    profile = require_profile(db, config.get("profile_id"), error=WorkflowDomainError)
    messages: list[dict[str, Any]] = []
    if config.get("system"):
        messages.append({"role": "system", "content": str(config["system"])})
    messages.append({"role": "user", "content": str(config.get("prompt", ""))})
    base_url = profile.base_url.rstrip("/")
    model = str(config.get("model") or profile.default_model)
    temperature = _LLM_PRESET_TEMPS.get(str(config.get("preset") or "balanced"), 0.4)
    response = httpx.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {profile.api_key}"},
        json={"model": model, "messages": messages, "temperature": temperature},
        timeout=LLM_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    text = str(response.json()["choices"][0]["message"]["content"]).strip()
    return {"text": text}


@register("translate")
def translate(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    from app.domain.translate import translate as translate_text

    text = str(config.get("text", ""))
    if not text.strip():
        return {"text": ""}
    return {
        "text": translate_text(
            db,
            text,
            str(config.get("target_lang") or "en"),
            engine=str(config.get("engine") or "google").lower(),
            profile_id=str(config.get("profile_id") or "") or None,
        )
    }
