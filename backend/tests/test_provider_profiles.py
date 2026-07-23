from __future__ import annotations

from app.core.db import SessionLocal
from app.domain.providers import resolve_profile
from tests.util import fresh_client


def test_profile_crud_with_masked_keys() -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})

    created = client.post(
        "/api/settings/providers",
        json={"name": "我的 Kimi", "vendor": "moonshot", "config": {"api_key": "sk-kimi-1234"}},
    ).json()
    # Preset fills base_url + default model; key never serializes, only a hint.
    assert created["base_url"] == "https://api.moonshot.cn/v1"
    assert created["default_model"] == "moonshot-v1-8k-vision-preview"
    assert "api_key" not in created
    assert created["key_hint"] == "…1234"
    assert created["config"]["api_key"] == "…1234"
    assert created["config"]["base_url"] == "https://api.moonshot.cn/v1"
    assert created["config"]["default_model"] == "moonshot-v1-8k-vision-preview"

    second = client.post(
        "/api/settings/providers",
        json={"name": "备用 Kimi", "vendor": "moonshot", "config": {"api_key": "sk-kimi-5678"}},
    ).json()
    listed = client.get("/api/settings/providers").json()
    assert len(listed) == 2  # multiple profiles per vendor

    updated = client.patch(f"/api/settings/providers/{second['id']}", json={"enabled": False}).json()
    assert updated["enabled"] is False

    assert client.delete(f"/api/settings/providers/{second['id']}").status_code == 204
    assert len(client.get("/api/settings/providers").json()) == 1


def test_resolution_reads_enabled_profiles() -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})

    client.post(
        "/api/settings/providers",
        json={"name": "主力 DashScope", "vendor": "alibaba", "config": {"api_key": "profile-key"}},
    )
    with SessionLocal() as db:
        assert resolve_profile(db, "alibaba").name == "主力 DashScope"


def test_vendor_presets_listed() -> None:
    client = fresh_client()
    presets = {item["vendor"]: item for item in client.get("/api/settings/provider-vendors").json()}
    assert "moonshot" in presets and "minimax" in presets
    assert presets["minimax"]["default_model"] == "MiniMax-VL-01"
    assert presets["alibaba"]["capability_ids"] == ["image"]
    assert presets["bytedance"]["capability_ids"] == ["video"]
    assert presets["bytedance-image"]["capability_ids"] == ["image"]  # Seedream 独立厂商项:各配各的档案
    assert presets["bytedance"]["default_model"] == "doubao-seedance-2-0-260128"
    assert presets["openai-tts"]["capability_ids"] == ["tts"]
    assert presets["openai-tts"]["default_model"] == "gpt-4o-mini-tts"
    assert presets["openai-compatible-tts"]["capability_ids"] == ["tts"]
    assert [field["key"] for field in presets["volcano-podcast"]["fields"]] == ["api_key", "appid"]
    assert presets["volcano-podcast"]["fields"][0]["label"] == "Access Token"


def test_provider_defaults_require_matching_capability() -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    kimi = client.post(
        "/api/settings/providers",
        json={"name": "Kimi", "vendor": "moonshot", "config": {"api_key": "sk-kimi"}},
    ).json()
    assert kimi["capability_ids"] == ["chat"]

    assert client.put(
        "/api/settings/provider-defaults/chat",
        json={"provider_profile_id": kimi["id"], "model": "moonshot-v1-8k"},
    ).status_code == 200
    assert client.put(
        "/api/settings/provider-defaults/image",
        json={"provider_profile_id": kimi["id"], "model": "qwen-image"},
    ).status_code == 422

    openai_tts = client.post(
        "/api/settings/providers",
        json={"name": "OpenAI TTS", "vendor": "openai-tts", "config": {"api_key": "sk-tts"}},
    ).json()
    assert client.put(
        "/api/settings/provider-defaults/tts",
        json={"provider_profile_id": openai_tts["id"], "model": "gpt-4o-mini-tts"},
    ).status_code == 200


def test_kb_embedding_config_put_get() -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    profile = client.post(
        "/api/settings/providers",
        json={
            "name": "本地 Ollama",
            "vendor": "openai-compatible",
            "config": {
                "api_key": "x",
                "base_url": "http://localhost:11434/v1",
                "default_model": "nomic-embed-text",
            },
        },
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


def test_create_profile_copies_credentials_server_side() -> None:
    """同一把 Key 配到另一能力的独立档案:copy_credentials_from 服务端复制,
    密钥不经前端往返;两个档案随后各自独立(改一个不动另一个)。"""
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    video = client.post(
        "/api/settings/providers",
        json={"name": "火山视频", "vendor": "bytedance", "config": {"api_key": "ark-secret-9876"}},
    ).json()

    image = client.post(
        "/api/settings/providers",
        json={"name": "火山生图", "vendor": "bytedance-image", "config": {}, "copy_credentials_from": video["id"]},
    ).json()
    assert image["vendor"] == "bytedance-image"
    assert image["key_hint"] == "…9876"  # 密钥拷到了,响应仍只有打码提示
    assert image["base_url"] == "https://ark.cn-beijing.volces.com/api/v3"
    assert image["default_model"] == "doubao-seedream-4-0-250828"

    # 独立性:改视频档案的 key 不影响生图档案
    client.patch(f"/api/settings/providers/{video['id']}", json={"config": {"api_key": "ark-new-0000"}})
    listed = {p["id"]: p for p in client.get("/api/settings/providers").json()}
    assert listed[video["id"]]["key_hint"] == "…0000"
    assert listed[image["id"]]["key_hint"] == "…9876"

    # 来源不存在 → 404;显式给了 key 则不复制
    assert (
        client.post(
            "/api/settings/providers",
            json={"name": "x", "vendor": "bytedance-image", "config": {}, "copy_credentials_from": "nope"},
        ).status_code
        == 404
    )
