"""空密钥不发 `Authorization` —— 而且这条规矩**只有一处实现**。

## 为什么这条看不出来

`f"Bearer {''}"` 的值是 `"Bearer "`(带尾随空格),那是一个非法头值:h11 在发送时抛
`LocalProtocolError`。本地 / 无鉴权端点(Ollama、LM Studio、vLLM)正是空密钥的那一批。

`ai_chat` 写对了,还写了理由;而 `ai/model_catalog.fetch_models` 不知道那一处存在,
无条件发头 —— 抛出来的异常落进一个 `except Exception`(端点不可达和不实现 /models 都只是
「没有目录」),于是被当成「这个端点没有模型」,还往缓存写一条失败记录,每 60 秒重试一次
并再次失败。四处后果全是静默的,而且看着都像"本来就该这样":

1. 设置页的模型选择器对本地端点**永远是空的**;
2. 价格预填拿不到目录报价;
3. `sidecar_provider` 的 `cached_model` 恒为 None,于是一个 128K 的本地 qwen3 按 32000 的
   回退窗口**提前四倍**开始压缩上下文 —— 设置页显示的 `context_window_source` 是
   `"fallback"`,它说的是真话,只是没说"我压根问不出来";
4. 每 60 秒重试一次并再次失败。

这是标准的"同一份语义要在多处成立":两处都写得对,但第二处根本不知道第一处存在。
所以这条棘轮问的是 **OpenAI 兼容那条路上还有没有人自己拼这个头**。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import ast
from pathlib import Path

import httpx
import pytest

from app.core.http_retry import auth_headers

BACKEND = Path(__file__).resolve().parent.parent
#: 会连到**用户自己填地址**的 OpenAI 兼容端点的那几处 —— 只有这些可能是空密钥。
#: 托管厂商的适配器(dashscope / ark / minimax / evolink)密钥是必填的,空了是配置错误,
#: 不在这条规矩的范围里。
OPENAI_COMPATIBLE = (
    BACKEND / "app" / "domain" / "ai_chat.py",
    BACKEND / "app" / "ai" / "model_catalog.py",
)


def test_空密钥不发这个头() -> None:
    assert auth_headers("") == {}
    assert auth_headers("   ") == {}, "只有空白的密钥等于没填"
    assert auth_headers(None) == {}
    assert auth_headers("sk-x") == {"Authorization": "Bearer sk-x"}


def test_带空格的头确实是非法的_这不是我们保守() -> None:
    """钉住**前提**:哪天这个头不再被拒,这条规矩就该重新讨论,而不是一直传下去。

    直接问 h11(httpx 的 HTTP/1.1 实现)—— MockTransport 不经过它,所以拿 mock 来验这件事
    会得到一个假的"不抛",那比没测更坏。
    """
    import h11

    connection = h11.Connection(our_role=h11.CLIENT)
    with pytest.raises(h11.LocalProtocolError, match="Illegal header value"):
        connection.send(
            h11.Request(method="GET", target="/models",
                        headers=[("host", "x"), ("Authorization", "Bearer ")])
        )


def test_没有第二处自己拼这个头() -> None:
    """判据是"加第三个 OpenAI 兼容调用点时,用不用再想一遍这件事"。"""
    offenders: list[str] = []
    for path in OPENAI_COMPATIBLE:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            # f"Bearer {…}" 在 AST 里是 JoinedStr,第一段是常量 "Bearer "。
            if not isinstance(node, ast.JoinedStr):
                continue
            head = node.values[0] if node.values else None
            if isinstance(head, ast.Constant) and str(head.value).strip() == "Bearer":
                offenders.append(f"{path.relative_to(BACKEND).as_posix()}:{node.lineno}")
    assert not offenders, (
        "这几处自己拼了 Bearer 头,空密钥时会抛一个被 except 吞掉的非法头值异常 —— "
        "改用 app.core.http_retry.auth_headers:\n  " + "\n  ".join(offenders)
    )


def test_本地端点问得出目录() -> None:
    """反面那一条此前没有:测试只断言了"填了 key 时 key 要发到端点"。"""
    import app.ai.model_catalog as catalog

    seen: list[dict] = []

    def fake_get(url, **kwargs):
        seen.append(dict(kwargs.get("headers") or {}))
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={"data": [{"id": "qwen3:32b", "context_window": 131072}]},
        )

    original = catalog.httpx.get
    catalog.httpx.get = fake_get  # type: ignore[assignment]
    try:
        models = catalog.fetch_models("http://127.0.0.1:11434/v1", "", use_cache=False)
    finally:
        catalog.httpx.get = original  # type: ignore[assignment]

    assert [one.id for one in models] == ["qwen3:32b"], "本地端点的目录还是拿不到"
    assert "Authorization" not in seen[0], "空密钥还是把 Authorization 发出去了"
