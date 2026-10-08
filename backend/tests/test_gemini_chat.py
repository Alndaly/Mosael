"""Gemini 对话:Google 连接填 AI Studio 的 API Key,对话由 pi 的原生 Gemini Provider 承载。

钉的是四件事,每一件错了都不会报错,只会「看起来能用」:

1. **能力与目录**:Google 的预设能对话了,但同一把 Key 下的模型清单里混着 Imagen、Veo、向量、语音、实时音频 ——
   只有 Gemini 的对话模型能进对话下拉,Veo / Lyria 照旧只在视频 / 音频里。
2. **执行面**:Gemini 走智能体与无工具网关(pi 原生协议),**不走**后端的 OpenAI 兼容直连 —— 它有服务地址,
   不拦的话会拼出 `…/v1beta/chat/completions` 打过去,一个 404。
3. **发给 sidecar 的那份**:带 pi Provider id 和这个人的钥匙,不带 OAuth 凭据;网关不为它铸服务令牌。
4. **老连接不用迁移**:能力从预设现算,升级前建的 Google 连接一行不改就能对话。
"""

from __future__ import annotations

import httpx
import pytest

from app.ai import model_catalog
from app.ai.gemini_models import is_chat_model
from app.ai.sidecar import pi_client
from app.core.db import SessionLocal
from app.domain.ai_chat import AiChatError, chat, target_for
from app.domain.providers import credentials as provider_credentials
from app.domain.providers import health
from app.domain.providers import models as provider_models
from app.domain.providers import thinking
from app.domain.providers.chat_connection import default_chat_connection, reachable_on
from app.domain.providers.presets import provider_definition, served_by_pi
from app.domain.providers.runtime import sidecar_provider
from tests.util import add_provider, fresh_client, stub_client

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


# ---------------------------------------------------------------- 预设


def test_google_预设能对话_只收_API_Key_由_pi_原生_Provider_承载() -> None:
    google = provider_definition("google")
    assert google is not None
    assert google.capability_ids == ("chat", "video", "audio"), "Veo / Lyria 照旧,对话是加上去的"
    assert google.auth_types == ("api_key",), "Gemini 订阅不许第三方用 —— 不能有订阅登录"
    assert google.pi_provider == "google"
    assert google.model_catalog == "gemini"
    assert "AI Studio" in google.capabilities and "Google AI Pro/Ultra" in google.capabilities
    assert served_by_pi("google")
    assert not served_by_pi("openai") and not served_by_pi("deepseek")
    assert served_by_pi("anthropic"), "订阅授权那几家照旧由 pi 承载"


def test_设置页的服务商清单里_google_出现在对话分区() -> None:
    client = fresh_client()
    vendors = {row["vendor"]: row for row in client.get("/api/settings/provider-vendors").json()}
    assert "chat" in vendors["google"]["capability_ids"]
    assert vendors["google"]["auth"] == ["api_key"]


# ---------------------------------------------------------------- 目录


@pytest.mark.parametrize(
    ("model_id", "chat"),
    [
        ("gemini-2.5-pro", True),
        ("gemini-2.5-flash", True),
        ("gemini-2.5-flash-lite", True),
        ("gemini-3-flash-preview", True),
        ("gemini-3.1-pro-preview", True),
        ("gemini-3.1-pro-preview-customtools", True),
        ("gemini-3.5-flash-lite", True),
        ("gemini-3.8-flash", True),
        ("gemini-flash-latest", True),
        ("models/gemini-3.7-flash", True),
        ("gemini-2.5-flash-image", False),
        ("gemini-3-pro-image", False),
        ("gemini-3.1-flash-lite-image", False),
        ("gemini-embedding-2", False),
        ("gemini-2.5-flash-preview-tts", False),
        ("gemini-3.8-flash-tts", False),
        ("gemini-3.8-live", False),
        ("gemini-3.1-flash-live-preview", False),
        ("gemini-3.5-live-translate-preview", False),
        ("gemini-2.5-flash-native-audio-preview-12-2025", False),
        ("gemini-3.5-transcribe", False),
        ("gemini-omni-1.1-flash", False),
        ("gemini-2.5-computer-use-preview-10-2025", False),
        ("gemini-robotics-er-2-preview", False),
        ("imagen-4.0-generate-001", False),
        ("veo-3.1-generate-preview", False),
        ("lyria-3.5", False),
        ("gemma-4-31b-it", False),
        ("deep-research-preview-04-2026", False),
    ],
)
def test_哪些名字是_gemini_对话模型(model_id: str, chat: bool) -> None:
    assert is_chat_model(model_id) is chat


def _models_page(names: list[tuple[str, list[str]]], token: str = "") -> dict:
    page: dict = {
        "models": [
            {
                "name": f"models/{name}",
                "displayName": name,
                "inputTokenLimit": 1_048_576,
                "outputTokenLimit": 65_536,
                "supportedGenerationMethods": methods,
            }
            for name, methods in names
        ]
    }
    if token:
        page["nextPageToken"] = token
    return page


#: `GET /v1beta/models` 两页,形状照官方 models.list:对话模型、出图、念字、向量、实时、Veo、Imagen、Lyria 混在一起。
_PAGE_1 = _models_page(
    [
        ("gemini-2.5-pro", ["generateContent", "countTokens", "createCachedContent", "batchGenerateContent"]),
        ("gemini-2.5-flash-image", ["generateContent", "countTokens"]),
        ("gemini-2.5-flash-preview-tts", ["generateContent", "countTokens"]),
        ("gemini-embedding-2", ["embedContent", "countTextTokens"]),
        ("veo-3.1-generate-preview", ["predictLongRunning"]),
        ("imagen-4.0-generate-001", ["predict"]),
    ],
    token="page-2",
)
_PAGE_2 = _models_page(
    [
        ("gemini-3-flash-preview", ["generateContent", "countTokens"]),
        ("gemini-3.1-flash-live-preview", ["bidiGenerateContent"]),
        ("lyria-3.5", ["generateContent"]),
        ("gemma-4-31b-it", ["generateContent", "countTokens"]),
        ("gemini-3.8-flash", ["generateContent", "countTokens"]),
        # 名字像对话模型、却不支持 generateContent 的(只能拿来调优的底座这一类):不进对话下拉。
        ("gemini-2.5-flash-tuning-base", ["createTunedModel"]),
    ]
)


def test_gemini_目录只列对话模型_按原生协议鉴权_翻页(monkeypatch) -> None:
    model_catalog.clear_cache()
    seen: list[tuple[str, dict, dict]] = []

    def fake_get(url, **kwargs):
        params = dict(kwargs.get("params") or {})
        seen.append((url, dict(kwargs.get("headers") or {}), params))
        body = _PAGE_2 if params.get("pageToken") == "page-2" else _PAGE_1
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(model_catalog, "RetryingClient", stub_client(get=fake_get))
    models = model_catalog.fetch_models(GEMINI_BASE, "aistudio-key", protocol="gemini", use_cache=False)

    assert [model.id for model in models] == ["gemini-2.5-pro", "gemini-3-flash-preview", "gemini-3.8-flash"]
    assert models[0].context_window == 1_048_576 and models[0].max_output_tokens == 65_536
    assert [url for url, _, _ in seen] == [f"{GEMINI_BASE}/models", f"{GEMINI_BASE}/models"]
    assert seen[0][1] == {"x-goog-api-key": "aistudio-key"}, "AI Studio 的钥匙走 x-goog-api-key,不是 Bearer"
    assert seen[1][2]["pageToken"] == "page-2"


def test_openai_兼容的目录照旧(monkeypatch) -> None:
    """同一个函数,不点名协议时还是 OpenAI 兼容那一套:Bearer、`data` 数组。"""
    model_catalog.clear_cache()
    seen: list[dict] = []

    def fake_get(url, **kwargs):
        seen.append(dict(kwargs.get("headers") or {}))
        return httpx.Response(200, json={"data": [{"id": "gpt-x"}]}, request=httpx.Request("GET", url))

    monkeypatch.setattr(model_catalog, "RetryingClient", stub_client(get=fake_get))
    assert [m.id for m in model_catalog.fetch_models("https://api.openai.com/v1", "sk", use_cache=False)] == ["gpt-x"]
    assert seen == [{"Authorization": "Bearer sk"}]


# ---------------------------------------------------------------- 能力


def test_模型行没写能力时_只有_gemini_对话模型被认成对话() -> None:
    evidenced = provider_models.evidenced_capabilities
    assert evidenced("google", "gemini-2.5-flash") == ["chat"]
    assert evidenced("google", "gemini-3.9-flash") == ["chat"], "目录外的新型号照样能对话"
    assert evidenced("google", "veo") == ["video"]
    assert evidenced("google", "lyria-3.5") == ["audio"]
    assert evidenced("google", "veo-3.1-generate-preview") == [], "内置目录外的 Veo 型号要用户标能力,但绝不是对话模型"
    assert evidenced("google", "imagen-4.0-generate-001") == [], "手动加进来的 Imagen 不能冒充对话模型"
    assert evidenced("google", "gemini-2.5-flash-preview-tts") == []
    assert evidenced("google", "gemini-3-pro-image") == []
    # 别家不受这条规则影响。
    assert evidenced("openai-compatible", "imagen-4.0-generate-001") == ["chat"]


def _google(db, *, model: str = "gemini-2.5-flash", capability_ids=None, make_default: bool = True):
    """一条**升级前就建好的** Google 连接:API Key、默认地址,和一行模型。连接上没有任何能力字段。"""
    return add_provider(
        db,
        name="我的 Gemini",
        vendor="google",
        base_url=GEMINI_BASE,
        api_key="aistudio-key",
        auth_type="api_key",
        model=model,
        capability_ids=capability_ids,
        make_default=make_default,
    )


def test_老的_google_连接不用迁移就能对话_veo_lyria_不变() -> None:
    client = fresh_client()
    with SessionLocal() as db:
        profile = _google(db, model="veo-3.1-generate-preview", capability_ids=["video"], make_default=False)
        provider_models.upsert(db, profile, "lyria-3.5")
        provider_models.upsert(db, profile, "gemini-3-flash-preview")
        db.commit()
        profile_id = profile.id
        owner = profile.owner_user_id

        assert "chat" in provider_models.profile_capabilities(db, profile)
        chat_models = {m.model_id for m in provider_models.models_for_capability(db, "chat", owner)}
        assert chat_models == {"gemini-3-flash-preview"}, "Veo / Lyria 不能出现在对话下拉里"
        assert {m.model_id for m in provider_models.models_for_capability(db, "video", owner)} == {"veo-3.1-generate-preview"}
        assert {m.model_id for m in provider_models.models_for_capability(db, "audio", owner)} == {"lyria-3.5"}

    # 智能体的模型下拉读的那一份(capability-models/chat),连同它发得出的思考档位。
    rows = client.get("/api/settings/capability-models/chat").json()
    assert [(row["provider_profile_id"], row["model"]) for row in rows] == [(profile_id, "gemini-3-flash-preview")]
    assert rows[0]["thinking_levels"] == ["low", "medium", "high"], "Gemini 3 关不掉思考,「关」由界面写成「模型默认」"


# ---------------------------------------------------------------- 执行面


def test_gemini_走智能体与网关_不走直连() -> None:
    fresh_client()
    with SessionLocal() as db:
        profile = _google(db)
        db.commit()
        owner = profile.owner_user_id
        by_surface = {
            surface: {m.model_id for m in provider_models.models_for_capability(db, "chat", owner, surface=surface)}
            for surface in ("all", "direct", "gateway", "automation")
        }
        assert by_surface == {
            "all": {"gemini-2.5-flash"},
            "direct": set(),
            "gateway": {"gemini-2.5-flash"},
            "automation": {"gemini-2.5-flash"},
        }
        assert reachable_on(profile, "automation") and not reachable_on(profile, "direct")
        # 他把 Gemini 设成了默认对话模型:直连的调用方(翻译、发布文案)不挑它,工作流照挑。
        assert default_chat_connection(db, owner_user_id=owner, surface="direct") is None
        assert default_chat_connection(db, owner_user_id=owner, surface="automation").id == profile.id


def test_直连调用方拿到_gemini_说清楚_不拼一个_404() -> None:
    fresh_client()
    with SessionLocal() as db:
        profile = _google(db)
        db.commit()
        resolved = provider_credentials.resolve_connection(db, profile, profile.owner_user_id)
        with pytest.raises(AiChatError) as caught:
            target_for(db, resolved, surface="direct")
    assert caught.value.key == "aiChat_nativeOnly"


def test_发给_sidecar_的那份带_pi_Provider_和这个人的钥匙() -> None:
    fresh_client()
    with SessionLocal() as db:
        profile = _google(db, model="gemini-2.5-pro")
        db.commit()
        resolved = provider_credentials.resolve_connection(db, profile, profile.owner_user_id)
        payload = sidecar_provider(db, resolved, "gemini-2.5-pro")
    assert payload["pi_provider"] == "google"
    assert payload["api_key"] == "aistudio-key"
    assert payload["base_url"] == GEMINI_BASE
    assert "credential" not in payload, "API Key 连接没有 OAuth 凭据可带"
    # 窗口与输出额度在后端定死(和设置页显示的是同一个数),思考档位表跟着模型走。
    assert payload["context_window"] > 0 and payload["max_output_tokens"] > 0
    assert payload["thinking_level_map"] == {"off": None, "low": "low", "medium": "medium", "high": "high"}


def test_工作流和画板经网关调_gemini_不铸服务令牌(monkeypatch) -> None:
    fresh_client()
    captured: dict = {}

    def fake_complete(**kwargs):
        captured.update(kwargs)
        return pi_client.GatewayResult(text="来自 Gemini", usage={"input": 9, "output": 3})

    monkeypatch.setattr(pi_client, "gateway_complete", fake_complete)
    with SessionLocal() as db:
        profile = _google(db)
        db.commit()
        resolved = provider_credentials.resolve_connection(db, profile, profile.owner_user_id)
        target = target_for(db, resolved, surface="automation")

    assert target.execution_surface == "gateway"
    assert target.gateway_token == "" and target.gateway_user_id == "", "钥匙随帧带下去,没有要回写的东西"
    assert chat(target, [{"role": "user", "content": "写一句"}]) == "来自 Gemini"
    assert captured["provider"]["pi_provider"] == "google"
    assert captured["provider"]["api_key"] == "aistudio-key"
    assert captured["model"] == "gemini-2.5-flash"
    assert captured["token"] == ""


def test_智能体用_gemini_时_sidecar_收到原生_Provider() -> None:
    from app.domain.agent.host import resolve_chat_provider

    fresh_client()
    with SessionLocal() as db:
        profile = _google(db, model="gemini-3-flash-preview")
        db.commit()
        provider, model, chosen = resolve_chat_provider(db, None, "", user_id=profile.owner_user_id)
    assert (model, chosen.id) == ("gemini-3-flash-preview", profile.id)
    assert provider["pi_provider"] == "google" and provider["api_key"] == "aistudio-key"


def test_三种帧带同一份供应商描述_压缩也带思考档位表(tmp_path, monkeypatch) -> None:
    """手动压缩的摘要请求同样要知道「这个模型关不掉思考」,否则 2.5 Pro 收到 thinkingBudget 0 —— 400。"""
    import json
    import sys

    script = tmp_path / "sidecar.py"
    script.write_text(
        "import json, os, sys\n"
        "frame = json.loads(sys.stdin.readline())\n"
        "open(os.environ['FRAME_LOG'], 'w').write(json.dumps(frame))\n"
        "print(json.dumps({'type': 'compacted', 'turnId': frame['turnId'], 'sessionState': []}), flush=True)\n"
    )
    log = tmp_path / "frame.json"
    monkeypatch.setenv("FRAME_LOG", str(log))
    monkeypatch.setattr(pi_client, "pi_sidecar_command", lambda: (sys.executable, str(script)))
    provider = {
        "base_url": GEMINI_BASE,
        "api_key": "aistudio-key",
        "vendor": "google",
        "pi_provider": "google",
        "context_window": 1_000_000,
        "thinking_level_map": {"off": None, "low": "low", "medium": "medium", "high": "high"},
        "vision": True,
    }
    pi_client.compact_session(api_base="http://127.0.0.1:1", token="t", provider=provider, model="gemini-2.5-pro", adapter_state=[])
    frame = json.loads(log.read_text())
    assert frame["provider"]["piProvider"] == "google"
    assert frame["provider"]["thinkingLevelMap"] == provider["thinking_level_map"]
    assert frame["provider"]["vision"] is True


# ---------------------------------------------------------------- 思考档位、探活


@pytest.mark.parametrize(
    ("model_id", "levels"),
    [
        ("gemini-2.5-flash", ["off", "low", "medium", "high"]),
        ("gemini-2.5-flash-lite", ["off", "low", "medium", "high"]),
        ("gemini-2.5-pro", ["low", "medium", "high"]),
        ("gemini-3-flash-preview", ["low", "medium", "high"]),
        ("gemini-3.1-pro-preview", ["low", "medium", "high"]),
        ("gemini-3-pro-preview", ["low", "high"]),
        ("gemini-3.8-flash", ["low", "medium", "high"]),
        ("gemini-2.0-flash", []),
    ],
)
def test_gemini_的思考档位(model_id: str, levels: list[str]) -> None:
    assert thinking.profile_for("google", model_id).levels() == levels


def test_探活按_gemini_的鉴权头(monkeypatch) -> None:
    fresh_client()
    sent: list[dict] = []

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, url, headers=None):
            sent.append({"url": url, "headers": dict(headers or {})})
            return httpx.Response(200, json={"models": []}, request=httpx.Request("GET", url))

    monkeypatch.setattr(health, "RetryingClient", Client)
    with SessionLocal() as db:
        profile = _google(db)
        db.commit()
        resolved = provider_credentials.resolve_connection(db, profile, profile.owner_user_id)
    result = health.probe(resolved)
    assert result.online and not result.detail, "钥匙是对的,不能报「凭据被拒」"
    assert sent == [{"url": f"{GEMINI_BASE}/models", "headers": {"x-goog-api-key": "aistudio-key"}}]
