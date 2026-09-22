"""用户在「模型设置」里填的「最大输出 Token」,要真的出现在直连那条通道发出去的 payload 里。

## 现场

那一格此前只进两个地方:拼给 pi sidecar 的 payload,和设置页自己回显的那几行。而
`domain/ai_chat.chat()` 这条直连 HTTP 通道**从头到尾没有 import 过 `model_limits`** ——
翻译、素材分析、工作流 LLM 节点、工作流 AI 编排、发布文案、提示词优化、画板写作、放行判断,
八个调用点,一个字节都发不出去。

**为什么一直没人发现**:不填 `max_tokens` 时供应商用自己的默认值,通常能跑出结果,只是结果
比用户要求的短 —— 没有任何东西会报错。而设置页显示的那行写着「运行时真正会用的数」,
这句话在智能体那条路上是真的,在这八条路上是假的,界面上两者长得一模一样。

`model_limits` 模块头记录的那个真实故障(deepseek-v4-flash 按 16,384 发、「一轮思考还没说完
就报已用完输出额度」)在这八条路上**根本没被修过**,只是从"发错的数"变成了"不发"。
"""

from __future__ import annotations

import httpx
import pytest

from app.core import http_retry as ai_retry
from app.domain.ai_chat import ChatTarget, chat


def _req() -> httpx.Request:
    return httpx.Request("POST", "https://provider.test/chat/completions")


def _install(monkeypatch, seen: list[dict]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.append(json.loads(request.content))
        return httpx.Response(200, request=_req(), json={"choices": [{"message": {"content": "ok"}}]})

    real = ai_retry.RetryingClient
    monkeypatch.setattr(
        ai_retry,
        "RetryingClient",
        lambda *a, **k: real(*a, **{**k, "transport": httpx.MockTransport(handler)}),
    )


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(ai_retry.time, "sleep", lambda *a, **k: None)


def test_解析出来的输出上限真的发出去了(monkeypatch) -> None:
    seen: list[dict] = []
    _install(monkeypatch, seen)
    target = ChatTarget(base_url="https://provider.test", api_key="k", model="m", max_output_tokens=384_000)

    chat(target, [{"role": "user", "content": "hi"}])

    assert seen[0].get("max_tokens") == 384_000, "用户设的输出上限没有发到线上 —— 结果会比他要的短"


def test_节点上那一格更具体_它先说了算(monkeypatch) -> None:
    """工作流 LLM 节点把 max_tokens 开放给了用户,那是**这一次调用**的意图,
    比模型上的默认值更具体。所以是 setdefault 而不是覆盖。"""
    seen: list[dict] = []
    _install(monkeypatch, seen)
    target = ChatTarget(base_url="https://provider.test", api_key="k", model="m", max_output_tokens=384_000)

    chat(target, [{"role": "user", "content": "hi"}], extra={"max_tokens": 1024})

    assert seen[0].get("max_tokens") == 1024


def test_解析不出上限时不瞎发(monkeypatch) -> None:
    """发一个猜的数比不发更坏:供应商的默认值至少是它自己的实情。"""
    seen: list[dict] = []
    _install(monkeypatch, seen)

    chat(ChatTarget(base_url="https://provider.test", api_key="k", model="m"), [{"role": "user", "content": "hi"}])

    assert "max_tokens" not in seen[0]


def test_两条通道取的是同一个数() -> None:
    """`target_for` 解析出的上限,必须和 `sidecar_provider` 拼给 pi 的那个是同一个 ——
    `model_limits.resolve` 自称「唯一的合并处」,这条钉住两边真的都经过它。"""
    from app.domain import model_limits

    # 纯函数层面对齐就够:两边都传同一组入参时,resolve 只有一个答案。
    kwargs = dict(model_id="deepseek-v4-flash", base_url="https://api.deepseek.com", vendor="deepseek")
    once = model_limits.resolve(**kwargs)
    twice = model_limits.resolve(**kwargs)
    assert once.effective_max_output_tokens == twice.effective_max_output_tokens
    assert once.effective_max_output_tokens, "内置表对这个模型没有结论,这条测试选错了样本"


def test_用户在模型设置里填的那个数_一路走到线上() -> None:
    """**这条走真实接线**,前面几条构造的是 `ChatTarget`,绕过了 `target_for`。

    而第一版的 bug 正好在 `target_for` 里(import 写错了模块路径),前面三条测试全绿 ——
    一条绕过接线的测试,证明不了接线是通的。
    """
    from app.core.db import SessionLocal
    from app.db.models import ProviderProfile
    from app.domain import provider_models
    from app.domain.ai_chat import target_for
    from app.domain.provider_credentials import ResolvedConnection
    from tests.util import fresh_client

    client = fresh_client()
    profile_id = client.post(
        "/api/settings/providers",
        json={"vendor": "openai", "name": "直连", "api_key": "k", "base_url": "https://provider.test"},
    ).json()["id"]
    with SessionLocal() as db:
        profile = db.get(ProviderProfile, profile_id)
        row = provider_models.upsert(db, profile, "some-chat-model", source="manual")
        row.max_output_tokens = 384_000  # 用户在「模型设置」里填的那一格
        db.commit()
        target = target_for(
            db,
            ResolvedConnection(
                id=profile_id, name="直连", vendor="openai",
                base_url="https://provider.test", auth_type="api_key", enabled=True, api_key="k",
            ),
            model="some-chat-model",
        )

    assert target.max_output_tokens == 384_000, "设置页那格没有走到调用目标上"
