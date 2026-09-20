"""**一个模型能读多长、一次能说多长,以及这两个数从哪来。**

## 为什么需要这张表

供应商的 `/models` 目录是第一手事实,但**多数端点不报上限**:DeepSeek 官方端点、各家中转、
本地推理服务都只列一个 id。于是所有这些模型都落到"未知云模型"的回退上 —— 128K 窗口、
思考模型 16,384 的输出额度。用户撞到的正是这个:deepseek-v4-flash 真实是 1M 窗口、384K
输出上限,而我们按 16,384 发,一轮思考还没说完就报「模型已用完本轮输出额度」。

`ai/model_catalog` 那边写着「端点没给的字段一律留空,不猜」,这条仍然成立 —— 这张表不是猜,
是**查证过的事实**(2026-09,来源见下),和 `domain/thinking` 那张思考档位表同一性质:
查得到的写进来,查不到的走回退。

## 三条约定

1. **按模型名前缀匹配,不按 vendor。** 中转端点的 vendor 一律是 `openai-compatible`,
   后面挂的可能是任何一家;OpenRouter 的 id 还带 `厂商/` 前缀。按 vendor 查表在这两种
   最常见的配置下必然落空 —— 那正是 `domain/thinking._by_model_name` 踩过的坑。
2. **最长前缀赢。** `grok-4.6` 要用它自己那条,而不是 `grok-4` 那条。这也让**家族兜底**
   成立:`claude-` 给整个家族一个保守的 200K/64K,具体型号的那几条再逐个盖掉它。没有兜底
   的话,表里漏掉一个新型号 = 那个型号直接掉回 128K,而它的同门明明都写着 1M。
3. **宁可报小,不可报大。** 表里的数一律向下取整到整千(1,048,576 → 1,000,000,
   393,216 → 384,000,65,535 → 65,000)。窗口报小只是早一点压缩;报大则是发出去被服务端拒,
   整轮对话失败。同理,拿不准的一律不写 —— 不写就走回退,而回退是安全的。

## 来源(2026-09 查证)

- OpenAI —— developers.openai.com/api/docs/models 及各模型页(官方)
- Anthropic —— platform.claude.com 模型总览表与各模型页(官方)
- DeepSeek —— api-docs.deepseek.com 定价页(官方)
- xAI —— docs.x.ai/developers/models(官方,只列窗口,不列输出上限 → 输出留空)
- Kimi / Moonshot —— platform.kimi.ai 定价页(官方,同样只列窗口)
- 智谱 GLM —— docs.z.ai 模型页
- Google Gemini / 通义千问 / MiniMax / 豆包 / 开源权重(Llama、Mistral)—— 第三方汇总
  (OpenRouter 与各家模型页),官方文档未给出结构化的上限表。按第 3 条向下取整后收录。

**百度文心、腾讯混元等暂不收录**:这一轮没查到可引用的结构化上限,按第 3 条宁可不写。
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlparse

from app.domain import thinking

#: 目录查不到、也没手动设时的窗口。**必须与 sidecar 的两个 fallback 常量一致** ——
#: 云端按 128K、本机/LAN 按 32K;界面与运行时用不同值会让水位和压缩行为对不上。
#: 由 contracts/context-meter-cases.json 钉住,两侧测试跑同一份语料。
FALLBACK_CONTEXT_WINDOW = 128000
LOCAL_FALLBACK_CONTEXT_WINDOW = 32000
#: 连这张表都没有这个模型时的输出额度。同样由那份语料钉住(max_output_cases)。
FALLBACK_MAX_OUTPUT_TOKENS = 4096
#: 思考模型的那一档。思考 token 和正文共用输出额度,4K 很容易全花在思考上。
FALLBACK_REASONING_MAX_OUTPUT_TOKENS = 32768

#: 不填「最大输出 Token」时,单轮最多给到这么多。**这是预算,不是模型上限**。
#:
#: 为什么要封顶:表里记的是模型**能接受的最大值**(DeepSeek 384K、Claude 128K),而
#: `max_tokens` 在 Anthropic 一类接口上要和输入一起装进窗口 —— 把上限原样发出去,
#: 一个长对话会因为"预留了 384K 输出"而被拒。而且没有哪一轮智能体对话需要 64K 以上的
#: 正文;真要更长,设置页的「最大输出 Token」就是为此存在的,填了的值不受这里约束。
OUTPUT_BUDGET_CAP = 65536


@dataclass(frozen=True)
class Limits:
    """一个模型的上限。两项都可能为 None —— 查不到就是查不到。"""

    context_window: int | None = None
    max_output_tokens: int | None = None


#: 模型名前缀 → 上限。**只写查证过的**,其余留给回退(见模块头)。
#: 维护方式:改一条就更新模块头的来源与日期;`tests/test_model_limits.py` 盯着这张表的形状。
KNOWN_LIMITS: dict[str, Limits] = {
    # —— OpenAI ——(developers.openai.com/api/docs/models,官方)
    "gpt-6": Limits(1_000_000, 128_000),
    "gpt-5.6": Limits(1_000_000, 128_000),
    "gpt-5.4": Limits(1_000_000, 128_000),
    "gpt-5.2": Limits(1_000_000, 128_000),
    #: gpt-5 / 5.1 / 5-mini 那一代是 400K 一档,和 5.2 起的 1.05M 不是一回事。
    "gpt-5": Limits(400_000, 128_000),
    "gpt-4.1": Limits(1_000_000, 32_000),
    "gpt-4o": Limits(128_000, 16_000),
    "o3": Limits(200_000, 100_000),
    "o4-mini": Limits(200_000, 100_000),
    # —— Anthropic ——(platform.claude.com 各模型页,官方)
    #: 家族兜底:4.x 起每个 Claude 至少 200K/64K。更长的前缀会盖掉它(最长前缀赢)。
    "claude-": Limits(200_000, 64_000),
    "claude-3": Limits(200_000, 4_000),
    "claude-opus-5": Limits(1_000_000, 128_000),
    "claude-sonnet-5": Limits(1_000_000, 128_000),
    "claude-fable-5": Limits(1_000_000, 128_000),
    "claude-opus-4-8": Limits(1_000_000, 128_000),
    "claude-opus-4-7": Limits(1_000_000, 128_000),
    "claude-opus-4-6": Limits(1_000_000, 128_000),
    "claude-sonnet-4-6": Limits(1_000_000, 64_000),
    "claude-haiku-4-5": Limits(200_000, 64_000),
    # —— DeepSeek ——(api-docs.deepseek.com 定价页,官方)
    "deepseek-v4": Limits(1_000_000, 384_000),
    "deepseek-flash": Limits(1_000_000, 384_000),
    #: chat / reasoner 是老别名,当前定价页已不列;按 V3.x 的保守值给。
    "deepseek-chat": Limits(128_000, 8_000),
    "deepseek-reasoner": Limits(128_000, 64_000),
    "deepseek-v3": Limits(128_000, 64_000),
    # —— Google Gemini ——(第三方汇总;官方文档未给结构化上限表)
    "gemini-3": Limits(1_000_000, 64_000),
    "gemini-2.5": Limits(1_000_000, 64_000),
    "gemini-2.0": Limits(1_000_000, 8_000),
    # —— xAI Grok ——(docs.x.ai/developers/models,官方;该页只列窗口,输出上限未公布)
    "grok-4.6": Limits(500_000, None),
    "grok-4.5": Limits(500_000, None),
    "grok-4.3": Limits(1_000_000, None),
    "grok-4.20": Limits(1_000_000, None),
    "grok-4.1-fast": Limits(2_000_000, None),
    "grok-4": Limits(256_000, None),
    "grok-3": Limits(131_000, None),
    "grok-code": Limits(256_000, None),
    "grok-build-0.1": Limits(256_000, None),
    # —— Kimi / Moonshot ——(platform.kimi.ai 定价页,官方;同样只列窗口)
    "kimi-k3": Limits(1_000_000, None),
    "kimi-k2.7": Limits(256_000, None),
    "kimi-k2.6": Limits(256_000, None),
    "kimi-k2": Limits(128_000, None),
    "moonshot-v1-128k": Limits(128_000, None),
    "moonshot-v1-32k": Limits(32_000, None),
    "moonshot-v1-8k": Limits(8_000, None),
    # —— 智谱 GLM ——(docs.z.ai 与第三方汇总)
    "glm-5": Limits(1_000_000, 128_000),
    "glm-4.6": Limits(200_000, 16_000),
    "glm-4.5": Limits(128_000, 98_000),
    "glm-4": Limits(128_000, 4_000),
    # —— 通义千问 ——(第三方汇总:OpenRouter 的模型页)
    "qwen3.8-max": Limits(1_000_000, 131_000),
    "qwen3.6": Limits(1_000_000, 65_000),
    "qwen3.5": Limits(1_000_000, 65_000),
    "qwen3-max": Limits(256_000, 65_000),
    "qwen3-coder-flash": Limits(1_000_000, 65_000),
    "qwen3-coder-plus": Limits(998_000, 65_000),
    "qwen3-coder-next": Limits(262_000, 262_000),
    "qwen3-coder": Limits(256_000, 65_000),
    "qwen-long": Limits(10_000_000, 8_000),
    "qwen-turbo": Limits(1_000_000, 8_000),
    "qwen-plus": Limits(128_000, 8_000),
    "qwen-max": Limits(32_000, 8_000),
    # —— MiniMax ——(第三方汇总)
    "minimax-m2": Limits(200_000, 128_000),
    "minimax-m1": Limits(1_000_000, 40_000),
    # —— 豆包 / 火山方舟 ——(第三方汇总)
    "doubao-seed-evolving": Limits(1_000_000, 256_000),
    "doubao-seed-2.1": Limits(256_000, 256_000),
    "doubao-seed-1.6": Limits(256_000, 32_000),
    # —— 开源权重(常挂在中转或本地端点后面)——(第三方汇总)
    #: Scout 宣称的 10M 是理论值,没有端点真的按那个提供服务 —— 按第 3 条取保守值。
    "llama-4": Limits(1_000_000, 8_000),
    "llama-3": Limits(128_000, 8_000),
    "mistral-large": Limits(128_000, 8_000),
}


def known_limits(model_id: str) -> Limits:
    """表里这个模型的上限;查不到返回两项皆空的 `Limits()`。

    归一化只做两件事:小写,以及去掉 `厂商/` 前缀(OpenRouter 的 id 形如
    `deepseek/deepseek-v4-flash`)。日期后缀不用管 —— 前缀匹配天然覆盖
    `claude-haiku-4-5-20251001`、`qwen3-max-2026-01-23` 这类。
    """
    name = (model_id or "").strip().lower().rsplit("/", 1)[-1]
    if not name:
        return Limits()
    # 最长前缀赢:grok-4.6 要用它自己那条,而不是更短的 grok-4.20 之类擦边匹配。
    match = max(
        (prefix for prefix in KNOWN_LIMITS if name.startswith(prefix)),
        key=len,
        default=None,
    )
    return KNOWN_LIMITS[match] if match else Limits()


def fallback_context_window(base_url: str) -> int:
    """未知云模型按 128K;本机/LAN 推理端点继续采用保守窗口。"""
    try:
        hostname = (urlparse(base_url).hostname or "").lower()
        if hostname == "localhost" or hostname.endswith(".local"):
            return LOCAL_FALLBACK_CONTEXT_WINDOW
        if hostname and ipaddress.ip_address(hostname).is_private:
            return LOCAL_FALLBACK_CONTEXT_WINDOW
    except ValueError:
        pass
    return FALLBACK_CONTEXT_WINDOW


def fallback_max_output_tokens(context_window: int, *, thinking: bool) -> int:
    """连表都没有这个模型时用多少。**和 sidecar 同一个形状**(pi.ts 的 fallbackMaxTokens)。

    思考 token 和正文共用这份额度,所以对推理模型给得宽 —— 4K 很容易全花在思考上,最后一个字
    都没说出来(那正是用户会看到的「已用完本轮输出额度」)。但不超过窗口的四分之一:输出占掉
    大半个窗口,就没剩下多少装对话了,而本机小模型的窗口正是靠这一项兜住的。
    """
    if not thinking:
        return FALLBACK_MAX_OUTPUT_TOKENS
    return max(FALLBACK_MAX_OUTPUT_TOKENS, min(FALLBACK_REASONING_MAX_OUTPUT_TOKENS, context_window // 4))


def output_budget(*, context_window: int, model_max_output: int | None, thinking: bool) -> int:
    """不填「最大输出 Token」时,单轮实际发出去的 `max_tokens`。

    知道模型上限就按上限封顶(见 OUTPUT_BUDGET_CAP 那段说明),不知道才按窗口推。
    """
    if model_max_output:
        return max(1, min(model_max_output, OUTPUT_BUDGET_CAP, context_window // 4))
    return fallback_max_output_tokens(context_window, thinking=thinking)


#: 一个上限是从哪来的。界面照此措辞,用户才知道"这个数改不改得动"。
SOURCES = ("override", "catalog", "builtin", "fallback")


@dataclass(frozen=True)
class Resolved:
    """合并「用户填的 → 目录给的 → 内置表 → 回退」之后的结果。

    `context_window` / `max_output_tokens` 是**查到的上限**(None = 只有回退),
    `effective_*` 是**运行时真正会用的数**。两者分开给,是因为它们经常不一样:
    DeepSeek 的输出上限是 384,000,而不填时我们按 65,536 发。界面把两个都显示出来,
    「为什么只有这么多输出额度」这个问题才在界面上推得出来。
    """

    context_window: int | None
    context_window_source: str
    max_output_tokens: int | None
    max_output_tokens_source: str
    effective_context_window: int
    effective_max_output_tokens: int


def resolve(
    *,
    model_id: str,
    base_url: str,
    vendor: str,
    override_window: int | None = None,
    override_output: int | None = None,
    catalog_window: int | None = None,
    catalog_output: int | None = None,
) -> Resolved:
    """这个模型的两个上限,以及运行时会用的那两个数。**唯一的合并处。**

    优先级:用户在模型设置里填的 → 供应商目录报的 → 内置表 → 回退。目录压在内置表之前,
    是因为目录是这个端点**自己**的说法:中转商完全可能把 1M 的模型限到 128K,那时该听它的。

    用户填的输出额度**不受 OUTPUT_BUDGET_CAP 约束**:那一格存在的意义就是突破默认预算。
    """
    builtin = known_limits(model_id)

    if override_window:
        window, window_source = override_window, "override"
    elif catalog_window:
        window, window_source = catalog_window, "catalog"
    elif builtin.context_window:
        window, window_source = builtin.context_window, "builtin"
    else:
        window, window_source = None, "fallback"

    if override_output:
        output, output_source = override_output, "override"
    elif catalog_output:
        output, output_source = catalog_output, "catalog"
    elif builtin.max_output_tokens:
        output, output_source = builtin.max_output_tokens, "builtin"
    else:
        output, output_source = None, "fallback"

    effective_window = int(window or fallback_context_window(base_url))
    if output_source == "override":
        effective_output = int(output or 0)
    else:
        # 和 provider_models.runtime_limits 同一条判据:有一档能发得出去,才算思考模型。
        profile = thinking.profile_for(vendor, model_id)
        effective_output = output_budget(
            context_window=effective_window,
            model_max_output=output,
            thinking=any(mapped is not None for mapped in profile.level_map.values()),
        )
    return Resolved(
        context_window=window,
        context_window_source=window_source,
        max_output_tokens=output,
        max_output_tokens_source=output_source,
        effective_context_window=effective_window,
        effective_max_output_tokens=effective_output,
    )
