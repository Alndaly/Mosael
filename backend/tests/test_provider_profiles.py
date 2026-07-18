from __future__ import annotations

from app.core.db import SessionLocal
from app.domain.providers import resolve_profile, resolve_secret
from tests.util import fresh_client


def test_profile_crud_with_masked_keys() -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})

    created = client.post(
        "/api/settings/providers",
        json={"name": "我的 Kimi", "vendor": "moonshot", "api_key": "sk-kimi-1234"},
    ).json()
    # Preset fills base_url + default model; key never serializes, only a hint.
    assert created["base_url"] == "https://api.moonshot.cn/v1"
    assert created["default_model"] == "moonshot-v1-8k-vision-preview"
    assert "api_key" not in created
    assert created["key_hint"] == "…1234"

    second = client.post(
        "/api/settings/providers",
        json={"name": "备用 Kimi", "vendor": "moonshot", "api_key": "sk-kimi-5678"},
    ).json()
    listed = client.get("/api/settings/providers").json()
    assert len(listed) == 2  # multiple profiles per vendor

    updated = client.patch(f"/api/settings/providers/{second['id']}", json={"enabled": False}).json()
    assert updated["enabled"] is False

    assert client.delete(f"/api/settings/providers/{second['id']}").status_code == 204
    assert len(client.get("/api/settings/providers").json()) == 1


def test_resolution_prefers_profiles_then_legacy() -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    client.put("/api/settings/credentials", json={"provider": "alibaba", "secret": "legacy-key"})

    with SessionLocal() as db:
        assert resolve_secret(db, "alibaba") == "legacy-key"  # legacy fallback

    client.post(
        "/api/settings/providers",
        json={"name": "主力 DashScope", "vendor": "alibaba", "api_key": "profile-key"},
    )
    with SessionLocal() as db:
        assert resolve_secret(db, "alibaba") == "profile-key"  # profile wins
        assert resolve_profile(db, "alibaba").name == "主力 DashScope"


def test_vendor_presets_listed() -> None:
    client = fresh_client()
    presets = {item["vendor"]: item for item in client.get("/api/settings/provider-vendors").json()}
    assert "moonshot" in presets and "minimax" in presets
    assert presets["minimax"]["default_model"] == "MiniMax-VL-01"


def test_kb_embedding_config_put_get() -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    profile = client.post(
        "/api/settings/providers",
        json={"name": "本地 Ollama", "vendor": "openai-compatible", "api_key": "x",
              "base_url": "http://localhost:11434/v1"},
    ).json()

    saved = client.put(
        "/api/settings/kb-embedding",
        json={"provider_profile_id": profile["id"], "model": "nomic-embed-text", "dim": 768},
    ).json()
    assert saved["provider_profile_id"] == profile["id"]
    assert saved["model"] == "nomic-embed-text"
    assert saved["dim"] == 768
    assert saved["enabled"] is True

    fetched = client.get("/api/settings/kb-embedding").json()
    assert fetched == saved  # persisted, overrides the env fallback

    # Unknown provider is rejected.
    assert client.put(
        "/api/settings/kb-embedding",
        json={"provider_profile_id": "does-not-exist", "model": "m", "dim": 8},
    ).status_code == 404
