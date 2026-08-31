"""OAuth 模型经受控 sidecar Gateway 做无工具补全，不暴露令牌也不要求 base_url。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.ai.sidecar import adapters
from app.core.db import SessionLocal
from app.domain.ai_chat import ChatTarget, chat, target_for
from app.domain import provider_credentials
from tests.util import add_provider, fresh_client


GATEWAY_SIDECAR = '''
import json, os, sys
frame = json.loads(sys.stdin.readline())
open(os.environ["FRAME_LOG"], "w").write(json.dumps(frame))
print(json.dumps({
    "type": "gateway_done",
    "turnId": frame["turnId"],
    "text": "gateway answer",
    "usage": {"input": 12, "output": 4, "totalTokens": 16},
}), flush=True)
'''


def test_gateway_frame_contains_identity_not_an_exposed_http_endpoint(tmp_path: Path, monkeypatch) -> None:
    fresh_client()
    script = tmp_path / "gateway.py"
    script.write_text(GATEWAY_SIDECAR)
    log = tmp_path / "frame.json"
    monkeypatch.setenv("FRAME_LOG", str(log))
    monkeypatch.setattr(adapters, "pi_sidecar_command", lambda: (sys.executable, str(script)))

    result = adapters.gateway_complete(
        system_prompt="只回答正文",
        prompt="写一句",
        images=[{"data": "aW1hZ2U=", "mimeType": "image/png"}],
        provider={
            "base_url": "",
            "api_key": "",
            "vendor": "kimi-coding",
            "pi_provider": "kimi-coding",
            "credential": {"access_token": "secret"},
            "profile_id": "profile-1",
        },
        model="k3",
        api_base="http://127.0.0.1:8800",
        token="short-lived-service-token",
        options={"temperature": 0.7, "maxTokens": 128},
    )

    frame = json.loads(log.read_text())
    assert frame["type"] == "gateway_complete"
    assert frame["provider"]["piProvider"] == "kimi-coding"
    assert frame["provider"]["profileId"] == "profile-1"
    assert frame["images"][0]["data"] == "aW1hZ2U="
    assert frame["provider"]["baseUrl"] == ""
    assert result.text == "gateway answer"
    assert result.usage == {"input": 12, "output": 4, "totalTokens": 16}


def test_chat_uses_gateway_adapter_for_an_automation_target(monkeypatch) -> None:
    fresh_client()
    captured: dict = {}

    def fake_complete(**kwargs):
        captured.update(kwargs)
        return adapters.GatewayResult(text="from oauth", usage={"input": 3, "output": 2})

    monkeypatch.setattr(adapters, "gateway_complete", fake_complete)
    target = ChatTarget(
        base_url="",
        api_key="",
        model="k3",
        profile_id="p",
        vendor="kimi-coding",
        execution_surface="gateway",
        gateway_provider={"pi_provider": "kimi-coding", "credential": {"access_token": "x"}, "profile_id": "p"},
        gateway_api_base="http://127.0.0.1:8800",
        gateway_token="ephemeral",
    )

    text = chat(
        target,
        [
            {"role": "system", "content": "只给 JSON"},
            {"role": "user", "content": "写一句"},
        ],
        temperature=0.6,
        extra={"max_tokens": 64, "top_p": 0.8},
    )

    assert text == "from oauth"
    assert captured["system_prompt"] == "只给 JSON"
    assert "写一句" in captured["prompt"]
    assert captured["options"]["temperature"] == 0.6
    assert captured["options"]["maxTokens"] == 64
    assert captured["options"]["samplingParams"]["top_p"] == 0.8


def test_automation_target_resolves_oauth_identity_without_a_base_url(monkeypatch) -> None:
    fresh_client()
    with SessionLocal() as db:
        profile = add_provider(
            db,
            name="Kimi Code",
            vendor="kimi-coding",
            base_url="",
            auth_type="oauth",
            oauth_credential={"access_token": "x"},
            model="k3",
            capability_ids=["chat"],
        )
        db.commit()
        resolved = provider_credentials.resolve(db, profile, profile.owner_user_id)
        assert resolved is not None
        target = target_for(db, resolved, model="k3", surface="automation")

    assert target.execution_surface == "gateway"
    assert target.base_url == ""
    assert target.gateway_provider["pi_provider"] == "kimi-coding"
    assert target.gateway_token

    from app.core.security import find_session

    with SessionLocal() as db:
        assert find_session(db, target.gateway_token) is not None
    monkeypatch.setattr(
        adapters,
        "gateway_complete",
        lambda **_kwargs: adapters.GatewayResult(text="ok", usage={"input": 1, "output": 1}),
    )
    assert chat(target, [{"role": "user", "content": "hello"}]) == "ok"
    with SessionLocal() as db:
        assert find_session(db, target.gateway_token) is None
