from __future__ import annotations

import httpx
import pytest

from app.ai.model_catalog import cached_model, cached_models, clear_cache, fetch_models

"""供应商模型目录的解析与缓存。

要点是**不臆造**:上下文窗口只在端点真的给了的时候才有值。以前智能体侧硬编 128000,
配 8k 上下文的本地模型时,pi 以为还有 128k 可用、不做压缩,请求直到服务端才被拒 ——
用户看到的是一次莫名失败的对话。留 None 的价值就在于调用方能识别「不知道」并保守回退。
"""


@pytest.fixture(autouse=True)
def _clean_cache() -> None:
    clear_cache()
    yield
    clear_cache()


def _stub(monkeypatch, payload: object, *, calls: list | None = None) -> None:
    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        if calls is not None:
            calls.append((url, kwargs.get("headers")))
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)


def test_metadata_is_absent_when_the_endpoint_omits_it(monkeypatch) -> None:
    """只给 id 的端点(Ollama 就是这样)→ 元数据必须是 None,不能被填成默认值。"""
    _stub(monkeypatch, {"data": [{"id": "qwen3:8b"}]})
    (model,) = fetch_models("http://localhost:11434/v1", "")
    assert model.id == "qwen3:8b"
    assert model.context_window is None, "端点没给上下文窗口时不能编一个 —— 那正是硬编 128000 的老毛病"
    assert model.max_output_tokens is None


def test_both_field_spellings_are_accepted(monkeypatch) -> None:
    """context_length(OpenRouter)与 context_window(部分网关)是同一件事。"""
    _stub(monkeypatch, {"data": [
        {"id": "a", "context_length": 8192, "max_output_tokens": 1024},
        {"id": "b", "context_window": 200000, "max_tokens": 8192},
    ]})
    models = {m.id: m for m in fetch_models("http://x/v1", "k")}
    assert (models["a"].context_window, models["a"].max_output_tokens) == (8192, 1024)
    assert (models["b"].context_window, models["b"].max_output_tokens) == (200000, 8192)


def test_dirty_rows_are_dropped_not_crashed(monkeypatch) -> None:
    """字符串窗口、0、负数、非法行 —— 一律当作「没给」,而不是抛异常或者带着脏值往下走。"""
    _stub(monkeypatch, {"data": [
        "not-a-dict",
        {"no_id": 1},
        {"id": ""},
        {"id": "ok", "context_length": "8k", "max_tokens": 0},
        {"id": "neg", "context_length": -1},
        {"id": "ok"},  # 重复 id,取先出现的那条
    ]})
    models = fetch_models("http://x/v1", "k")
    assert [m.id for m in models] == ["neg", "ok"]
    assert all(m.context_window is None and m.max_output_tokens is None for m in models)


def test_unreachable_endpoint_yields_empty_not_error(monkeypatch) -> None:
    """端点连不上/不实现 /models,只是「没有目录」,调用方各自回退,不该炸。"""
    def boom(url: str, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", boom)
    assert fetch_models("http://127.0.0.1:9/v1", "k") == []
    assert cached_model("http://127.0.0.1:9/v1", "k", "m") is None


def test_result_is_cached_so_a_turn_does_not_refetch(monkeypatch) -> None:
    """智能体每轮都要查一次 contextWindow;没有缓存就是每轮多一次网络往返。"""
    calls: list = []
    _stub(monkeypatch, {"data": [{"id": "m", "context_length": 8192}]}, calls=calls)
    fetch_models("http://x/v1", "k")
    assert cached_model("http://x/v1", "k", "m").context_window == 8192
    assert len(calls) == 1, f"目录被重复抓取了 {len(calls)} 次"


def test_api_key_reaches_the_endpoint(monkeypatch) -> None:
    calls: list = []
    _stub(monkeypatch, {"data": []}, calls=calls)
    fetch_models("http://x/v1/", "secret")
    url, headers = calls[0]
    assert url == "http://x/v1/models", "base_url 末尾斜杠没被规范化"
    assert headers["Authorization"] == "Bearer secret"


def test_model_absent_from_catalog_is_none(monkeypatch) -> None:
    """自定义模型名/别名在目录里查不到很常见 —— 返回 None 让调用方回退,而不是随便挑一个。"""
    _stub(monkeypatch, {"data": [{"id": "other", "context_length": 8192}]})
    assert cached_model("http://x/v1", "k", "my-alias") is None


def test_a_turn_never_waits_on_the_catalog(monkeypatch) -> None:
    """**对话启动这条路上不许等网络。**

    上下文窗口是可选元数据:端点没列出来就留空,下游有保守回退,用户在模型行上填的值还压在
    它上面。而一次问不通的目录请求要等满 _FETCH_TIMEOUT(8 秒)——配了个连不通的地址,
    就是每说一句话都先卡八秒不动。所以这条路只读缓存,缺了在后台补。

    这里用一个**永远不返回**的 httpx.get 来钉:只要谁在调用方线程里发请求,这条就挂死。
    """
    import threading as _th

    from app.ai import model_catalog

    started = _th.Event()
    release = _th.Event()

    def never_returns(url: str, **kwargs: object):
        started.set()
        release.wait(10)  # 不设死等,免得断言失败时整个测试卡住
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", never_returns)
    clear_cache()
    try:
        # 缓存里没有 → 必须立刻返回「还不知道」,而不是跟着那个请求一起挂住。
        assert model_catalog.cached_models("http://x/v1", "k") is None
        assert model_catalog.cached_model("http://x/v1", "k", "m") is None
        assert started.wait(3), "后台刷新压根没起来 —— 那下一轮也永远拿不到目录"
    finally:
        release.set()


def test_none_means_unknown_not_empty(monkeypatch) -> None:
    """`None`(还没问到)和 `[]`(问过了,端点没列模型)必须分得开。

    混成一个的话,「不知道有没有」会被下游读成「确定没有」—— 而这两件事该走的回退不一样。
    """
    from app.ai import model_catalog

    clear_cache()
    _stub(monkeypatch, {"data": []})
    assert model_catalog.cached_models("http://x/v1", "k") is None, "第一次问不该假装已经知道"
    fetch_models("http://x/v1", "k")
    assert model_catalog.cached_models("http://x/v1", "k") == [], "问过之后就是确定的空"


def test_an_unreachable_endpoint_is_not_retried_every_time(monkeypatch) -> None:
    """连不通的端点要记一笔负缓存。

    不记的话每一次取目录都重来一遍、各等满 8 秒 —— 而调用方里有"每轮对话问一次"的那种。
    这正是测试套里 agent 那一批既慢又概率性变红的由来。
    """
    calls: list = []

    def refused(url: str, **kwargs: object):
        calls.append(url)
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", refused)
    clear_cache()
    for _ in range(5):
        assert fetch_models("http://127.0.0.1:9/v1", "k") == []
    assert len(calls) == 1, f"连不通的端点被反复重试了 {len(calls)} 次"
