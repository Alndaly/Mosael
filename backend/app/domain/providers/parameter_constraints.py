"""供应商把某些采样参数**钉死**时,我们不要在请求里带它们。

Kimi 的 K3 / K2.7-code / K2.6 都把 `temperature` 固定成 1.0(thinking 时的 K2.6 也是 1.0;
非 thinking 是 0.6,而模型自己知道该用哪个),`top_p` 固定 0.95,`presence_penalty` /
`frequency_penalty` / `n` 也固定。官方文档写得很直接:**不要显式传这些参数** —— 传一个别的值
就是 400,而传"看起来一样"的值也没有意义。

我们默认的 `temperature=0.2` 是给普通对话模型准备的。直接发给 Kimi 时会得到:

    invalid temperature: only 1 is allowed for this model

这不是某一次调用点的问题:分析、标题、工作流 LLM 节点都会经过 `ai_chat.chat`。所以在这条
公共请求构造处按厂商/模型名把固定参数拿掉,而不是在每个调用点各写一遍例外。
"""

from __future__ import annotations

#: Kimi 这套固定参数的名字。大小写无关地匹配模型名,不靠 vendor 拼写 ——
#: 第三方 OpenAI 兼容端点后面挂的也可能是同一个模型。
_KIMI_FIXED = frozenset({"temperature", "top_p", "presence_penalty", "frequency_penalty", "n"})
_KIMI_VENDORS = frozenset({"moonshot", "kimi-coding"})


def fixed_sampling_parameters(vendor: str, model: str) -> frozenset[str]:
    """这次请求里**不能显式发送**的采样参数;空集合表示没有这类限制。"""

    name = (model or "").strip().lower().split("/")[-1]
    if name.startswith("kimi-"):
        return _KIMI_FIXED
    if (vendor or "").strip().lower() in _KIMI_VENDORS and any(family in name for family in ("k3", "k2.6", "k2.7")):
        return _KIMI_FIXED
    return frozenset()
