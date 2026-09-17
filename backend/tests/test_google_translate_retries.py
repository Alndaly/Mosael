"""逐句翻译那条路也要重试，而且限流时要说人话。

真机上撞到的：官方工作流「视频译配 · 字幕与配音」在 `逐句翻译成目标语言` 的**第 1/31 次迭代**
就整条失败，错误正文是一屏百分号编码 ——

    Google 翻译失败: Client error '429 Too Many Requests' for url
    'https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=en&dt=t&q=%E8%BF%99...'

两个毛病叠在一起：

1. **同一个 429，批量那条路退避重试、逐句这条当场失败。** `translate_many` 一直用
   `RetryingClient`，而工作流的翻译节点一句一次调用，走的是裸 `httpx.get` —— 设置页那句
   「连接断开/超时/限流时自动重试」管的是所有 AI 调用，这里漏了一条缝。免费端点按 IP 限流，
   而一条字幕轨就是几十上百次调用，正好是最需要重试的地方。
2. **错误正文把原文的百分号编码糊了一屏**：httpx 的 HTTPStatusError 带着完整 URL，而 URL 里
   是整段被编码的待译文本。真正有用的那半句（被限流了、可以换成 AI 翻译）淹在里面。
"""

from __future__ import annotations

import httpx
import pytest

from app.core import http_retry as ai_retry
from app.domain import translate as tr


def _transport(responses: list[httpx.Response]):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        index = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        return responses[index]

    return httpx.MockTransport(handler), calls


def _ok() -> httpx.Response:
    return httpx.Response(200, json=[[["hello", "你好", None, None]]])


def test_逐句那条路撞上限流会重试(monkeypatch) -> None:
    transport, calls = _transport([httpx.Response(429), _ok()])

    class Patched(ai_retry.RetryingClient):
        def __init__(self, *args, **kwargs) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(ai_retry, "backoff_seconds", lambda attempt: 0)
    monkeypatch.setattr(ai_retry, "RetryingClient", Patched)

    assert tr.google_translate("你好", "en") == "hello"
    assert calls["n"] == 2, "第一次 429 之后应该再试一次"


def test_一直限流才报错__而且说得出下一步(monkeypatch) -> None:
    transport, _ = _transport([httpx.Response(429)])

    class Patched(ai_retry.RetryingClient):
        def __init__(self, *args, **kwargs) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(ai_retry, "backoff_seconds", lambda attempt: 0)
    monkeypatch.setattr(ai_retry, "RetryingClient", Patched)

    with pytest.raises(tr.TranslateError) as caught:
        tr.google_translate("这是我工作室的 mac mini 小小玲珑", "en")

    assert caught.value.key == "translateErr_googleRateLimited"
    message = str(caught.value)
    #: 说得出另一条路,而不只是复述状态码。
    assert "AI" in message
    #: **原文不许出现在错误里**,更不许是百分号编码的那一坨。
    assert "%E" not in message and "mac mini" not in message
    assert "translate_a/single" not in message


def test_别的状态码也不把_URL_糊进去(monkeypatch) -> None:
    transport, _ = _transport([httpx.Response(503)])

    class Patched(ai_retry.RetryingClient):
        def __init__(self, *args, **kwargs) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(ai_retry, "backoff_seconds", lambda attempt: 0)
    monkeypatch.setattr(ai_retry, "RetryingClient", Patched)

    with pytest.raises(tr.TranslateError) as caught:
        tr.google_translate("你好", "en")
    assert caught.value.key == "translateErr_googleHttp"
    assert "503" in str(caught.value) and "translate_a/single" not in str(caught.value)


def test_调用方给了_client_就用它__不另开一个(monkeypatch) -> None:
    """批量那条路共享连接是为了省掉每条字幕一次 TLS 握手,不能被这次改动绕过去。"""
    transport, calls = _transport([_ok()])
    opened = {"n": 0}

    class Counting(ai_retry.RetryingClient):
        def __init__(self, *args, **kwargs) -> None:
            opened["n"] += 1
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(ai_retry, "RetryingClient", Counting)
    with httpx.Client(transport=transport) as shared:
        assert tr.google_translate("你好", "en", client=shared) == "hello"
    assert opened["n"] == 0, "给了 client 还自己再开一个,等于每句一次握手"


def test_批量节点收段落也收字符串__顺序就是对齐(monkeypatch) -> None:
    """译文和时间码靠**顺序**对齐:第 i 条译文配第 i 段。

    所以空段落也要占住自己的位置 —— 压缩掉一条,后面每一句都往前错一格,而错位在成片里
    表现为"配音对不上画面",不会有任何报错。上游最常见的是逐字稿的 segments(带 start/end/
    text),节点自己取正文 —— 此前那是模板里一句 `{{loop.item.text}}`,把节点的职责推给了调用方。
    """
    from app.domain import translate as domain_translate
    from app.domain.workflows.executors import ai as ai_executors

    seen: dict[str, object] = {}

    def fake_many(db, texts, target, *, user_id=None, engine="", profile_id=None, model=""):
        seen["texts"] = list(texts)
        seen["engine"] = engine
        return [f"[{target}] {one}" if one else "" for one in texts]

    monkeypatch.setattr(domain_translate, "translate_many", fake_many)

    out = ai_executors.translate_lines(
        None,
        None,
        {
            "texts": [{"start": 0, "end": 1, "text": "第一句"}, {"text": ""}, {"text": "第三句"}],
            "target_lang": "en",
            "engine": "google",
        },
    )

    assert seen["texts"] == ["第一句", "", "第三句"], "节点该自己从段落里取正文"
    assert out["texts"] == ["[en] 第一句", "", "[en] 第三句"], "空的那条要占住位置"
    assert out["count"] == 3

    #: 一列纯字符串也认 —— 上游不一定是逐字稿。
    plain = ai_executors.translate_lines(None, None, {"texts": ["a", "b"], "target_lang": "en"})
    assert plain["texts"] == ["[en] a", "[en] b"]


def test_模板不再逐句发请求() -> None:
    """真机上那条失败是「第 1/31 次迭代」—— 循环把一轨字幕拆成 31 次串行调用,
    每次一个新连接,而免费端点按 IP 限流。判据是模板里那一步**不是循环**。"""
    from app.domain.workflows.templates import translated_dub_graph

    graph = translated_dub_graph(voice_id="")
    step = next(node for node in graph["nodes"] if node["id"] == "translate_lines")
    assert step["type"] == "translate_lines", step["type"]
    assert not any(node["type"] == "loop_foreach" for node in graph["nodes"] if node["id"] == "translate_lines")

    #: 模板里的 `{{…}}` 会被 canonicalize_data_bindings 落成数据边,所以判据在边上。
    data = {
        (edge["source"], edge["source_output"], edge["target"], edge["target_input"])
        for edge in graph["edges"]
        if edge.get("kind") == "data"
    }
    assert ("verbatim_transcript", "segments", "translate_lines", "texts") in data, "段落该整批交给它"
    #: 下游读的是这个节点的输出名,改名而不改引用会让整条链路拿到空。
    assert ("translate_lines", "texts", "translated_subtitles", "texts") in data

    #: **官方模板不走免费端点。** 它按出口 IP 封,而且往往不会自己好(真机上直接请求拿到的是
    #: Google 的 "Sorry..." 拦截页,重试多少次都一样)。一条官方模板不能把成败押在这上面;
    #: 而这条链路本来就在用用户自己的供应商(转写、配音都是),翻译用同一套不是新的花费面。
    assert step["config"]["engine"] == "ai", step["config"]


def test_目标语言和音色留在能选它们的那个控件上() -> None:
    """一度把这两样提成起始参数,想让它"更通用" —— 换来的是两个自由文本框。

    `start.params` 在节点表里是无类型的 object,值那一列只能填字符串或引用上游输出,而起始
    节点没有上游(界面上就是一个点开写着「没有匹配的结果」的下拉)。留在节点上时,`target_lang`
    有 9 种语言的下拉、音色有按引擎列出的真正的选择器。
    要让「运行时问我一次」成立,缺的是**起始参数能声明类型**,那是引擎级的口子。
    """
    from app.domain.workflows import NODE_TYPES
    from app.domain.workflows.templates import translated_dub_graph

    graph = translated_dub_graph(voice_id="voice-1")
    nodes = {node["id"]: node for node in graph["nodes"]}

    assert nodes["translate_lines"]["config"]["target_lang"] == "en"
    assert nodes["dubbing"]["config"]["voice"] == "voice-1"
    #: 判据不是"是个常量",而是**那一格真的有可选值**;没有 options 就又回到自由文本。
    assert NODE_TYPES["translate_lines"]["config"]["target_lang"]["options"], "语言那格得有下拉"
    assert NODE_TYPES["dub_subtitles"]["config"]["voice"]["options_from"], "音色那格得是选择器"


def test_译配模板里一个循环节点都没有() -> None:
    """「逐句」说的是切分,不是逐个发请求 —— 整轨一次交给批量节点。"""
    from app.domain.workflows.templates import translated_dub_graph

    types = {node["type"] for node in translated_dub_graph(voice_id="")["nodes"]}
    assert not {one for one in types if one.startswith("loop_")}, types


def test_原声三档各做各的事() -> None:
    """「压低」不等于「听不见」。

    闪避把原声压到 30%(≈ −10.5 dB),那是给「旁白盖在环境音之上」准备的档位。而译配是用
    **另一种语言的说话声替换说话声** —— 两边都是人声,压到 30% 的结果是观众同时听见两个人
    在说话,只是一个小声点。真机上报回来的正是这句:「视频原本的文案对应的音频还在」。
    """
    from app.domain.workflows import NODE_TYPES
    from app.domain.workflows.templates import translated_dub_graph

    spec = NODE_TYPES["dub_subtitles"]["config"]["original_audio"]
    assert spec["options"] == ["duck", "mute", "keep", "separate"], spec
    assert spec["default"] == "duck", "单独用这个节点时保持旧行为"
    #: separate 是"先拆再丢人声" —— 它存在的理由就是 mute 会把背景音乐一起带走(ADR-0016)。

    nodes = {node["id"]: node for node in translated_dub_graph(voice_id="")["nodes"]}
    #: 译配要的是替换,而整轨静音会把背景音乐一起带走 —— 所以先拆,只丢人声那半。
    assert nodes["dubbing"]["config"]["original_audio"] == "separate"


def test_翻译用哪个模型是能配的() -> None:
    """一条连接上常常挂着好几个模型 —— 「用哪条连接」和「用哪个模型」是两个问题。

    此前只有前者:engine=ai 时用的永远是这条连接的默认对话模型,而翻译质量和成本都跟着它走。
    """
    from app.domain.workflows import NODE_TYPES

    for node_type in ("translate", "translate_lines"):
        config = NODE_TYPES[node_type]["config"]
        assert "model" in config, node_type
        #: 换连接就换了一整套模型 id,旧的那个在新连接下不存在 —— 声明出来界面才会跟着变。
        assert config["model"]["depends_on"] == "profile_id"
        assert not config["profile_id"].get("advanced"), "选了 ai 之后它立刻要紧,不该收在高级里"


def test_模型一路传到调用目标(monkeypatch) -> None:
    """声明了却没接上,界面上看得见一个下拉、发出去的仍是默认模型 —— 那种漏最难发现。"""
    from app.domain import translate as tr

    seen: dict[str, object] = {}

    def fake_target_for(db, resolved, *, model="", surface="direct"):
        seen["model"] = model
        return "target"

    monkeypatch.setattr(tr, "target_for", fake_target_for)

    class _Profile:
        enabled = True
        name = "x"

    monkeypatch.setattr(
        "app.domain.providers.find_enabled_connection", lambda *a, **k: _Profile(), raising=False
    )
    monkeypatch.setattr(
        "app.domain.provider_credentials.resolve_connection", lambda *a, **k: object(), raising=False
    )

    assert tr.resolve_ai_chat_target(None, "p1", "u1", "kimi-k3") == "target"
    assert seen["model"] == "kimi-k3"
