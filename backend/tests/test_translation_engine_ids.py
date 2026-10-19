"""翻译引擎 id:三条发起路都要对得上能力表。

真机上撞到的:智能体里让它翻译 / 用工作流节点翻译,后端回 **502: 没有这一家翻译:google**。
id 从哪来、为什么对不上,和「哪一层该认它」是两件事:

- 智能体工具 `translate_text` 的默认真的是 `engine="google"`(ADR 0032 之前的老 id),而能力表里
  内置那一家叫 `builtin:google` —— 对不上,所以 502;
- 老工作流、老画板、第三方客户端手里也还是 `google` / `ai`;
- 字幕面板传的是空串(按默认)或能力表给的下拉 id(`builtin:google`),一直是对的。

**不把 `google` 注册成第二家引擎**(那会让「设置 → 能力提供方」和节点下拉里出现两个同一家的选项),
也不让每个调用点各认一遍:旧 id 在能力表契约里登记成别名,由 `capabilities.canonical_id` 统一解析一次。

"没有这一家"那句话也要说人话:说清哪一家、这台机器上现在能用哪几家、下一步去哪换。
"""

from __future__ import annotations

import contextvars

import pytest

from app.core.db import SessionLocal
from app.domain import capabilities as caps
from app.domain import translate as tr
from tests.util import fresh_client


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _as_this_client(monkeypatch, client) -> None:
    """让直接调领域的工具认得出「这次调用是谁」—— 和经 /api/agent/tools 调用时同一个身份。"""
    import mcp_server
    from app.core.security import find_session

    with SessionLocal() as db:
        caller = find_session(db, client.headers["Authorization"].removeprefix("Bearer ")).user_id
    monkeypatch.setattr(mcp_server, "_CALLER_ID", contextvars.ContextVar("test_caller", default=caller))


def _stub_google(monkeypatch) -> list[tuple[str, str]]:
    """Google 免费端点打桩:这条链只验「挑到了谁」,不连外网。"""
    calls: list[tuple[str, str]] = []

    def fake(text: str, target: str, source: str = "auto", client=None) -> str:
        calls.append((text, target))
        return f"[{target}]{text}"

    monkeypatch.setattr(tr, "google_translate", fake)
    monkeypatch.setattr(tr, "_GOOGLE_MIN_INTERVAL_SECONDS", 0)
    return calls


# ── ① 三条发起路各自能选中 Google 翻译 ────────────────────────────────────────────


def test_智能体的翻译工具按默认翻_不再502(monkeypatch) -> None:
    """这是真机上那条路:工具默认发 `engine="google"`。以前它必然 502,一次都翻不成。"""
    import mcp_server

    client = fresh_client()
    _workspace(client)
    _as_this_client(monkeypatch, client)
    calls = _stub_google(monkeypatch)

    out = mcp_server.translate_text("你好", "en")

    assert out == {"text": "[en]你好"}, out
    assert calls == [("你好", "en")]


def test_智能体传老id_google_也不再502(monkeypatch) -> None:
    """模型读过旧文档、或第三方客户端照旧写 `google` —— 和默认那条同一个 id,一视同仁。"""
    import mcp_server

    client = fresh_client()
    _workspace(client)
    _as_this_client(monkeypatch, client)
    calls = _stub_google(monkeypatch)

    assert mcp_server.translate_text("hi", "zh", engine="google") == {"text": "[zh]hi"}
    assert calls == [("hi", "zh")]


def test_工作流翻译节点_空引擎与老id_都落到内置Google(monkeypatch) -> None:
    """节点不点名 = 按运行者默认(没定默认就是 Google);老图里存着 `google` 的也得照样能跑。"""
    from app.domain.workflows.executors import ai as ai_executors

    calls = _stub_google(monkeypatch)

    for engine in ("", "google"):
        out = ai_executors.translate_lines(
            None, None, {"texts": ["第一句"], "target_lang": "en", "engine": engine},
        )
        assert out == {"texts": ["[en]第一句"], "count": 1}, (engine, out)

    single = ai_executors.translate(None, None, {"text": "你好", "target_lang": "en", "engine": "google"})
    assert single == {"text": "[en]你好"}
    assert calls == [("第一句", "en"), ("第一句", "en"), ("你好", "en")]


def test_字幕翻译接口_空串按默认_点名内置id也照旧(monkeypatch) -> None:
    """字幕面板传的就是这两种:空串(默认),或能力表下拉给的 `builtin:google`。"""
    client = fresh_client()
    ws = _workspace(client)
    _stub_google(monkeypatch)

    for engine in ("", "builtin:google"):
        res = client.post("/api/translate", json={"workspace_id": ws, "texts": ["你好"], "target_lang": "en",
                                                  "engine": engine})
        assert res.status_code == 200, (engine, res.text)
        assert res.json()["translations"] == ["[en]你好"]


def test_字幕翻译接口_老客户端传google_也被认回来(monkeypatch) -> None:
    """ADR 0032 之前发出去的那份客户端(或存量的第三方脚本)手里是 `google` —— 不能因此 502。"""
    client = fresh_client()
    ws = _workspace(client)
    calls = _stub_google(monkeypatch)

    res = client.post("/api/translate", json={"workspace_id": ws, "texts": ["hi"], "target_lang": "zh",
                                              "engine": "google"})
    assert res.status_code == 200, res.text
    assert res.json()["translations"] == ["[zh]hi"]
    assert calls == [("hi", "zh")]


# ── ② 空字符串 = 按默认(默认就是 builtin:google)────────────────────────────────


def test_空字符串就是按默认_默认是内置Google() -> None:
    client = fresh_client()
    _workspace(client)
    with SessionLocal() as db:
        from app.db.models import User

        me = db.query(User).order_by(User.created_at).first()
        for engine in ("", "   "):
            provider = caps.pick(db, me.id, tr.CAPABILITY, engine)
            assert provider.id == tr.GOOGLE == "builtin:google"
            assert provider.builtin and not provider.missing


def test_别名只改名字_不改按默认的语义() -> None:
    assert caps.canonical_id(tr.CAPABILITY, "") == ""
    assert caps.canonical_id(tr.CAPABILITY, "   ") == ""
    assert caps.canonical_id(tr.CAPABILITY, "google") == tr.GOOGLE
    assert caps.canonical_id(tr.CAPABILITY, " Google ") == tr.GOOGLE
    assert caps.canonical_id(tr.CAPABILITY, "ai") == tr.CHAT
    #: 没登记过的原样交出去(插件连接 id 大小写敏感,不能顺手归一)。
    assert caps.canonical_id(tr.CAPABILITY, "Plugin-AbC123") == "Plugin-AbC123"
    #: 不把旧 id 注册成第二家引擎 —— 候选里只有规范 id。
    ids = [one.id for one in tr.CAPABILITY.builtins]
    assert ids == ["builtin:google", "builtin:chat"]
    assert "google" not in ids and "ai" not in ids


def test_默认也能用旧id点名_存下来的仍是规范id() -> None:
    """「设置 → 能力提供方 → 翻译」如果收到旧 id(老客户端),不能让那一格存着一个认不出的 id。"""
    client = fresh_client()
    _workspace(client)
    res = client.put("/api/settings/capabilities/translation", json={"provider_id": "ai"})
    assert res.status_code == 200, res.text
    assert res.json()["current"] == "builtin:chat"


# ── ③ 真不存在时说人话:哪一家、为什么、下一步、还有哪些能用 ─────────────────────


def test_点名不存在的引擎_列出能用的几家并说下一步() -> None:
    client = fresh_client()
    ws = _workspace(client)
    res = client.post("/api/translate", json={"workspace_id": ws, "texts": ["hi"], "target_lang": "en",
                                              "engine": "nope"})
    assert res.status_code >= 400, res.text
    detail = res.json()["detail"]
    #: 哪一家。
    assert "nope" in detail
    #: 哪几家能用(以能力表为准,不写死名字):Google 那一家在。
    assert tr.CAPABILITY.builtins[0].id == "builtin:google"
    assert "Google" in detail
    #: 下一步。
    assert "设置" in detail and "能力提供方" in detail
    #: 不再是那句「没有这一家翻译:x」。
    assert "没有这一家翻译" not in detail

    en = client.post("/api/translate", json={"workspace_id": ws, "texts": ["hi"], "target_lang": "en",
                                            "engine": "nope"}, headers={"Accept-Language": "en-US"})
    english = en.json()["detail"]
    assert "nope" in english and "Google" in english and "Settings" in english, english


def test_一家能用的都没有_那句话的下一步是去接一个(monkeypatch) -> None:
    """一台机器上一家可用的都没有(连免费 Google 都没有,比如被裁掉的部署):下一步是「去接一个」。"""
    monkeypatch.setattr(caps, "providers", lambda *args, **kwargs: [])
    with pytest.raises(caps.CapabilityUnavailable) as caught:
        caps.pick(None, None, tr.CAPABILITY, "nope")
    assert caught.value.key == "translateErr_unknownProviderNone"
    message = str(caught.value)
    assert "nope" in message and "设置" in message


def test_没登记这句话的能力_保持原来的key(monkeypatch) -> None:
    """翻译那句话的下一步和别处不一样;转写之类没登记的,不能因为翻译改了措辞就跟着换 key
    (`asrErr_unsupportedEngine` 已经被别的测试钉着)。"""
    from app.domain.voices import transcription as asr

    monkeypatch.setattr(caps, "providers", lambda *args, **kwargs: [
        caps.Provider(id="builtin:funasr", name="FunASR", builtin=True, missing=("没装运行环境",)),
    ])
    with pytest.raises(asr.TranscriptionProviderUnavailable) as caught:
        caps.pick(None, None, asr.CAPABILITY, "nonsense")
    assert caught.value.key == "asrErr_unsupportedEngine"
    assert "nonsense" in str(caught.value)


def test_不存在的引擎在领域层也是同一个key() -> None:
    with pytest.raises(tr.TranslateProviderUnavailable) as caught:
        caps.pick(None, None, tr.CAPABILITY, "nope")
    assert caught.value.key == "translateErr_unknownProvider"
    assert "nope" in str(caught.value)
