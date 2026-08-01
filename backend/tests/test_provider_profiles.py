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
    # 预设不再写死默认模型(核实过的名字也会随供应商下架失效,而模型目录是实时拉的),
    # 所以新建档案不再自动落一行模型 —— 用户在模型列表里从目录挑。
    models = client.get(f"/api/settings/providers/{created['id']}/models").json()
    assert not [row for row in models if row["configured"]]
    assert "api_key" not in created
    assert created["key_hint"] == "…1234"
    assert created["config"]["api_key"] == "…1234"
    assert created["config"]["base_url"] == "https://api.moonshot.cn/v1"

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


def test_能力挂在模型行上而不是连接上() -> None:
    """此前能力是档案级覆盖,于是同一个端点只能二选一:要么对话要么生图 —— 用户被迫为同一把
    key 建两个档案。现在能力在模型行上,一条连接可以同时提供两者。"""
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    created = client.post(
        "/api/settings/providers",
        json={
            "name": "多能力端点",
            "vendor": "openai-compatible",
            "config": {"base_url": "http://127.0.0.1:1/v1", "api_key": "k", "default_model": "chat-m"},
        },
    ).json()

    client.post(f"/api/settings/providers/{created['id']}/models", json={"model_id": "image-m"})
    client.patch(
        f"/api/settings/providers/{created['id']}/models/chat-m", json={"capability_ids": ["chat"]}
    )
    client.patch(
        f"/api/settings/providers/{created['id']}/models/image-m", json={"capability_ids": ["image"]}
    )

    chat = [row["model"] for row in client.get("/api/settings/capability-models/chat").json()]
    image = [row["model"] for row in client.get("/api/settings/capability-models/image").json()]
    assert "chat-m" in chat and "image-m" not in chat
    assert "image-m" in image and "chat-m" not in image

    # 连接对外的能力 = 它下面模型能力的并集
    profile = next(p for p in client.get("/api/settings/providers").json() if p["id"] == created["id"])
    assert set(profile["capability_ids"]) == {"chat", "image"}

def test_vendor_presets_listed() -> None:
    client = fresh_client()
    presets = {item["vendor"]: item for item in client.get("/api/settings/provider-vendors").json()}
    assert "moonshot" in presets and "minimax" in presets
    # 预设不再写死默认模型:实测 deepseek 那个 "deepseek-chat" 在真实端点上根本不存在,
    # 而这种字符串没人会去复核。模型从供应商目录实时拉。
    assert not presets["minimax"].get("default_model")
    # 百炼同时提供对话与向量嵌入(compatible-mode 端点),此前只写了 image —— 同一把
    # DashScope Key 想配对话还得再建一个「OpenAI 兼容端点」档案,而它明明就是这一家。
    assert presets["alibaba"]["capability_ids"] == ["chat", "image", "embedding"]
    # 火山方舟合成一家:同一把 Key 既做图像(Seedream)也做视频(Seedance)。
    # 拆成两个 vendor 是"一档案一能力"年代的产物,重构后只剩"同一把 Key 填两遍"的代价。
    assert presets["bytedance"]["capability_ids"] == ["image", "video"]
    assert presets["openai-tts"]["capability_ids"] == ["tts"]
    # 预设不再写死默认模型:核实过一次的名字也会随供应商下架而失效,而模型目录是实时拉的。
    assert not presets["openai-tts"].get("default_model")
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
        json={"name": "火山生图", "vendor": "bytedance", "config": {}, "copy_credentials_from": video["id"]},
    ).json()
    assert image["vendor"] == "bytedance"
    assert image["key_hint"] == "…9876"  # 密钥拷到了,响应仍只有打码提示
    assert image["base_url"] == "https://ark.cn-beijing.volces.com/api/v3"
    # 同上:不再自动落模型行。密钥拷贝这件事本身仍然成立,那才是这条用例要测的。
    image_models = client.get(f"/api/settings/providers/{image['id']}/models").json()
    assert not [row for row in image_models if row["configured"]]

    # 独立性:改视频档案的 key 不影响生图档案
    client.patch(f"/api/settings/providers/{video['id']}", json={"config": {"api_key": "ark-new-0000"}})
    listed = {p["id"]: p for p in client.get("/api/settings/providers").json()}
    assert listed[video["id"]]["key_hint"] == "…0000"
    assert listed[image["id"]]["key_hint"] == "…9876"

    # 来源不存在 → 404;显式给了 key 则不复制
    assert (
        client.post(
            "/api/settings/providers",
            json={"name": "x", "vendor": "bytedance", "config": {}, "copy_credentials_from": "nope"},
        ).status_code
        == 404
    )
