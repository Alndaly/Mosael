from __future__ import annotations

import base64
import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.db import SessionLocal
from app.db.models import Asset, ProviderProfile
from app.domain.analysis import service
from tests.media_fixtures import TINY_HEIC
from tests.util import add_provider, fresh_client, make_video_asset


def _me() -> str:
    """钥匙归人之后,取供应商必须说清"为谁" —— 测试里就是第一个账号。"""
    from app.core.db import SessionLocal
    from app.db.models import User

    with SessionLocal() as db:
        return db.query(User).order_by(User.created_at).first().id

HAS_FFMPEG = shutil.which("ffmpeg") is not None


def add_profile(client, vendor: str, name: str = "P") -> dict:
    return client.post(
        "/api/settings/providers",
        json={"name": name, "vendor": vendor, "config": {"api_key": f"sk-{vendor}"}},
    ).json()


def test_profile_picking_prefers_vision_vendors() -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})  # instance settings need an admin
    with SessionLocal() as db:
        with pytest.raises(service.AnalysisError):
            service.pick_analysis_profile(db, None, None)
    add_profile(client, "minimax")
    add_profile(client, "moonshot")
    with SessionLocal() as db:
        from app.db.models import User

        # 钥匙是建连接那个人的 —— 解析要说清「为谁」(见 domain/provider_credentials)。
        me = db.query(User).order_by(User.created_at).first().id
        assert service.pick_analysis_profile(db, None, me).vendor == "moonshot"  # order: moonshot first


def test_standalone_analysis_skips_agent_only_oauth_connections() -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    with SessionLocal() as db:
        add_provider(
            db,
            name="Kimi 订阅",
            vendor="moonshot",
            auth_type="oauth",
            base_url="",
            oauth_credential={"access_token": "x"},
            model="kimi-k3",
            capability_ids=["chat"],
        )
        add_provider(
            db,
            name="MiniMax API",
            vendor="minimax",
            base_url="https://api.minimax.test/v1",
            api_key="sk-test",
            model="minimax-vl",
            capability_ids=["chat"],
        )
        db.commit()

    with SessionLocal() as db:
        assert service.pick_analysis_profile(db, None, _me()).name == "MiniMax API"


def test_build_messages_shape() -> None:
    class FakeAsset:
        name = "海边素材"
        kind = "video"
        media_info = {"duration": 8.0}

    messages = service.build_messages(FakeAsset(), "画面里有什么？", [b"a", b"b"])
    content = messages[0]["content"]
    assert content[0]["type"] == "text"
    assert "海边素材" in content[0]["text"] and "2 帧" in content[0]["text"]
    assert [part["type"] for part in content[1:]] == ["image_url", "image_url"]
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_build_messages_includes_transcript() -> None:
    class FakeAsset:
        name = "对谈"
        kind = "video"
        media_info = {"duration": 30.0}

    messages = service.build_messages(FakeAsset(), "讲了什么？", [b"a"], transcript="你好，今天聊剪辑。")
    text = messages[0]["content"][0]["text"]
    assert "语音转写" in text
    assert "你好，今天聊剪辑。" in text


def test_adaptive_frame_count_scales_with_duration() -> None:
    # 约每 6 秒 1 帧,夹在 [4, 16]。
    assert service.adaptive_frame_count(0) == service.MIN_VIDEO_FRAMES
    assert service.adaptive_frame_count(3) == service.MIN_VIDEO_FRAMES  # 太短也保底 4 帧
    assert service.adaptive_frame_count(60) == 10
    assert service.adaptive_frame_count(6000) == service.MAX_VIDEO_FRAMES  # 长视频封顶


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_extract_video_frames(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
        check=True, timeout=60,
    )
    frames = service.extract_video_frames(video, count=4)
    assert 1 <= len(frames) <= 4
    assert all(frame[:2] == b"\xff\xd8" for frame in frames)  # JPEG magic


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_analyze_endpoint_end_to_end(monkeypatch, tmp_path: Path) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    add_profile(client, "moonshot", "Kimi")

    image = tmp_path / "pic.jpg"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:size=64x64", "-frames:v", "1", str(image)],
        check=True, timeout=30,
    )
    asset = client.post(
        "/api/assets/import",
        data={"workspace_id": ws["id"]},
        files={"file": ("pic.jpg", image.read_bytes(), "image/jpeg")},
    ).json()

    captured: dict = {}

    def fake_call(db, profile, messages, call=None):
        captured["model_profile"] = profile.vendor
        captured["parts"] = len(messages[0]["content"])
        return "画面是一张纯红色图片。"

    monkeypatch.setattr(service, "call_vision_model", fake_call)
    res = client.post(f"/api/assets/{asset['id']}/analyze", json={"question": "这是什么颜色？"})
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["answer"] == "画面是一张纯红色图片。"
    assert payload["provider"] == "moonshot"
    assert captured["parts"] == 2  # text + one image


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_analyze_heic_sends_real_jpeg_bytes_and_mime(monkeypatch) -> None:
    """不能只修界面:同一份 HEIC 交给视觉模型时也要走那份兼容预览。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    add_profile(client, "moonshot", "Kimi")
    asset = client.post(
        "/api/assets/import",
        data={"workspace_id": ws["id"]},
        files={"file": ("photo.heic", TINY_HEIC, "image/heic")},
    ).json()
    captured: dict[str, str] = {}

    def fake_call(db, profile, messages, call=None):
        captured["url"] = messages[0]["content"][1]["image_url"]["url"]
        return "红色图片"

    monkeypatch.setattr(service, "call_vision_model", fake_call)
    response = client.post(f"/api/assets/{asset['id']}/analyze", json={"question": "什么颜色？"})
    assert response.status_code == 200, response.text
    prefix, encoded = captured["url"].split(",", 1)
    assert prefix == "data:image/jpeg;base64"
    assert base64.b64decode(encoded).startswith(b"\xff\xd8")


def test_analyze_rejects_audio_assets() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    add_profile(client, "moonshot")
    asset = client.post(
        "/api/assets",
        json={"workspace_id": ws["id"], "kind": "audio", "name": "song", "file_key": "media/s.mp3", "media_info": {}},
    ).json()
    res = client.post(f"/api/assets/{asset['id']}/analyze", json={"question": "?"})
    assert res.status_code == 422


class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def _add_native_profile(
    db, vendor: str, base_url: str = "", model: str = "m", capability_ids: list[str] | None = None
) -> None:
    add_provider(
        db,
        name=vendor,
        vendor=vendor,
        base_url=base_url,
        api_key=f"sk-{vendor}",
        model=model,
        capability_ids=capability_ids,
    )
    db.commit()


def test_pick_native_video_profile_priority() -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    with SessionLocal() as db:
        assert service.pick_native_video_profile(db, None, None) is None
        _add_native_profile(db, "moonshot")
        _add_native_profile(db, "alibaba")
    with SessionLocal() as db:
        from app.db.models import User

        me = db.query(User).order_by(User.created_at).first().id
        assert service.pick_native_video_profile(db, None, me).vendor == "alibaba"  # google>alibaba>moonshot
        _add_native_profile(
            db, "google", base_url="https://gl/v1beta", model="gemini-2.0-flash", capability_ids=["chat"]
        )
    with SessionLocal() as db:
        assert service.pick_native_video_profile(db, None, _me()).vendor == "google"


def test_analyze_video_native_qwen_video_url(monkeypatch) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    asset_json = make_video_asset(client, ws["id"])
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return _FakeResp({"choices": [{"message": {"content": "海边散步的女孩"}}]})

    monkeypatch.setattr(service.ai_retry, "post", fake_post)
    with SessionLocal() as db:
        _add_native_profile(db, "alibaba", base_url="https://dashscope/compatible-mode/v1", model="qwen-vl-max")
        asset = db.get(Asset, asset_json["id"])
        result = service.analyze_asset(db, asset, "讲了什么", mode="native", user_id=_me())
    assert result["mode"] == "native" and result["provider"] == "alibaba"
    assert result["answer"] == "海边散步的女孩"
    content = captured["json"]["messages"][0]["content"]
    assert any(part.get("type") == "video_url" for part in content)
    assert content[-1]["video_url"]["url"].startswith("data:video/mp4;base64,")


def test_analyze_video_native_gemini_inline_data(monkeypatch) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    asset_json = make_video_asset(client, ws["id"])
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        captured["params"] = kwargs.get("params")
        return _FakeResp({"candidates": [{"content": {"parts": [{"text": "Gemini 看到了海"}]}}]})

    monkeypatch.setattr(service.ai_retry, "post", fake_post)
    with SessionLocal() as db:
        _add_native_profile(
            db,
            "google",
            base_url="https://generativelanguage.googleapis.com/v1beta",
            model="gemini-2.0-flash",
            capability_ids=["chat"],
        )
        asset = db.get(Asset, asset_json["id"])
        result = service.analyze_asset(db, asset, "描述", mode="native", user_id=_me())
    assert result["mode"] == "native" and result["provider"] == "google"
    assert captured["url"].endswith("/models/gemini-2.0-flash:generateContent")
    assert captured["params"]["key"] == "sk-google"
    parts = captured["json"]["contents"][0]["parts"]
    assert parts[1]["inline_data"]["mime_type"] == "video/mp4"


def test_analyze_native_gemini_refuses_missing_chat_model(monkeypatch) -> None:
    """Gemini 原生视频也必须使用连接中显式配置的模型，不能暗换成固定默认值。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    asset_json = make_video_asset(client, ws["id"])

    def unexpected_post(*_args, **_kwargs):
        pytest.fail("没有配置模型时不应发起 Gemini 请求")

    monkeypatch.setattr(service.ai_retry, "post", unexpected_post)
    with SessionLocal() as db:
        add_provider(
            db,
            name="Google",
            vendor="google",
            base_url="https://generativelanguage.googleapis.com/v1beta",
            api_key="sk-google",
        )
        asset = db.get(Asset, asset_json["id"])
        with pytest.raises(service.AnalysisError, match="没有可用的对话模型"):
            service.analyze_asset(db, asset, "描述", mode="native", user_id=_me())


def test_analyze_native_without_provider_errors() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    asset_json = make_video_asset(client, ws["id"])
    with SessionLocal() as db:
        asset = db.get(Asset, asset_json["id"])
        with pytest.raises(service.AnalysisError):
            service.analyze_asset(db, asset, "?", mode="native", user_id=_me())


def test_analyze_auto_falls_back_to_frames(monkeypatch) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    asset_json = make_video_asset(client, ws["id"])
    monkeypatch.setattr(service, "extract_video_frames", lambda path: [b"f1", b"f2"])
    monkeypatch.setattr(service, "call_vision_model", lambda _db, profile, messages, call=None: "抽帧描述")
    with SessionLocal() as db:
        _add_native_profile(db, "minimax")  # 视觉但非原生视频
        asset = db.get(Asset, asset_json["id"])
        result = service.analyze_asset(db, asset, "?", mode="auto", user_id=_me())
    assert result["mode"] == "frames" and result["frames"] == 2


def test_native_video_size_guard(monkeypatch) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    asset_json = make_video_asset(client, ws["id"])
    monkeypatch.setattr(service, "MAX_NATIVE_VIDEO_MB", 0)  # 任何视频都超限
    with SessionLocal() as db:
        _add_native_profile(db, "alibaba")
        asset = db.get(Asset, asset_json["id"])
        with pytest.raises(service.AnalysisError):
            service.analyze_asset(db, asset, "?", mode="native", user_id=_me())


def test_vision_call_refuses_a_profile_with_no_chat_model() -> None:
    """连接下没有对话模型时必须当场报错,而不是把请求换成 gpt-4o-mini 发出去。

    那个回落曾经真实存在:用户选的是 Kimi,分析却跑在别家端点的 gpt-4o-mini 上 ——
    静默换模型换厂商,正是 provider_credentials 要消灭的「花错钱」。
    """
    from app.domain.provider_credentials import ResolvedProvider

    fresh_client()  # 建表 —— 没有它,单独跑这条测试时 model_id_for 会撞「没有这张表」
    profile = ResolvedProvider(
        id="no-such-profile", name="空连接", vendor="moonshot",
        base_url="https://api.moonshot.cn/v1", auth_type="api_key", enabled=True,
        api_key="sk-test",
    )
    with SessionLocal() as db:
        with pytest.raises(service.AnalysisError, match="没有可用的对话模型"):
            service.call_vision_model(db, profile, [{"role": "user", "content": "hi"}])


def test_agent_video_analysis_uses_current_oauth_model_and_gateway(monkeypatch) -> None:
    """已有视频走当前会话模型：抽帧可以复用 Gateway 图片协议，不要求 OAuth 连接填服务地址。"""
    from app.ai.sidecar import adapters
    from app.core.security import mint_service_session
    from app.db.models import User

    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    asset = make_video_asset(client, workspace_id)
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

    session = client.post(
        "/api/agent/sessions",
        json={
            "workspace_id": workspace_id,
            "provider_profile_id": profile.id,
            "model": "k3",
        },
    ).json()
    client.patch(
        f"/api/agent/sessions/{session['id']}",
        json={"analysis_video_mode": "frames"},
    )

    captured: dict = {}

    def fake_gateway(**kwargs):
        captured.update(kwargs)
        return adapters.GatewayResult(text="K3 看到了两段画面", usage={"input": 9, "output": 4})

    monkeypatch.setattr(adapters, "gateway_complete", fake_gateway)
    monkeypatch.setattr(service, "extract_video_frames", lambda _path: [b"frame-1", b"frame-2"])
    with SessionLocal() as db:
        user = db.query(User).order_by(User.created_at).first()
        tool_token = mint_service_session(db, user.id, agent_session_id=session["id"])
    client.headers["Authorization"] = f"Bearer {tool_token}"

    response = client.post(
        f"/api/assets/{asset['id']}/analyze",
        # 即使工具参数说 auto，也以用户在这次会话里选定的 frames 为准。
        json={"question": "视频里发生了什么？", "mode": "auto"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "answer": "K3 看到了两段画面",
        "provider": "kimi-coding",
        "model": "k3",
        "mode": "frames",
        "frames": 2,
        "used_transcript": False,
    }
    assert captured["model"] == "k3"
    assert captured["provider"]["pi_provider"] == "kimi-coding"
    assert [image["data"] for image in captured["images"]] == [
        base64.b64encode(b"frame-1").decode(),
        base64.b64encode(b"frame-2").decode(),
    ]


def test_agent_oauth_native_video_requires_frames(monkeypatch) -> None:
    """Gateway 没有 video block；显式 native 不能暗中退化，也不能要求用户伪造服务地址。"""
    from app.ai.sidecar import adapters
    from app.core.security import mint_service_session
    from app.db.models import User

    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    asset = make_video_asset(client, workspace_id)
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
    session = client.post(
        "/api/agent/sessions",
        json={"workspace_id": workspace_id, "provider_profile_id": profile.id, "model": "k3"},
    ).json()
    client.patch(f"/api/agent/sessions/{session['id']}", json={"analysis_video_mode": "native"})

    monkeypatch.setattr(adapters, "gateway_complete", lambda **_kwargs: pytest.fail("native 不应调用图片 Gateway"))
    monkeypatch.setattr(service, "extract_video_frames", lambda _path: pytest.fail("native 不应静默改成抽帧"))
    with SessionLocal() as db:
        user = db.query(User).order_by(User.created_at).first()
        tool_token = mint_service_session(db, user.id, agent_session_id=session["id"])
    client.headers["Authorization"] = f"Bearer {tool_token}"

    response = client.post(
        f"/api/assets/{asset['id']}/analyze",
        # 工具参数不能覆盖用户在会话中明确选择的 native。
        json={"question": "描述视频", "mode": "frames"},
    )

    assert response.status_code == 422
    assert "OAuth" in response.json()["detail"]
    assert "抽帧" in response.json()["detail"]
