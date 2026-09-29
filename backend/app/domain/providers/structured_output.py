"""**这个端点能不能把 JSON Schema 当成硬约束。**

## 三档是什么

`response_format` 有三档,差别在**什么时候起作用**:

| 档位 | 保证 | 什么时候 |
| --- | --- | --- |
| `text` | 什么都不保证 | —— |
| `json_object` | 语法上是合法 JSON;字段、类型、取值一概不管 | 生成时 |
| `json_schema` + `strict` | 合法 JSON **且符合这份 Schema** | **生成时约束解码器** |

最后一档是"模型吐不出不合规的 token":少一个必填字段、枚举值编一个出来,在物理上不可能发生。
前两档只能**事后校验** —— 拿到之后再比对,不对就报错或重试。

## 为什么要有这张表

因为**各家支持的档位不一样**,而不支持时的表现是**静默的**:参数要么被忽略,要么被网关逐级
降级(见 `ai_chat._response_format_fallback_payload`),两种都不会告诉任何人。于是用户在节点上
写着 `json_schema` + strict,实际跑的却是纯文本 —— 而他没有任何地方看得出来。

真实后果(2026-09 实测,deepseek-v4-flash):一次是某个字段超出了它看不见的取值范围,一次是
整份 JSON 根本没闭合。两次都不是模型笨,是**它被要求照着一张自己看不见的图纸画**。

## 只写查证过的

和 `domain/thinking` 同一条规矩:查得到的写进来,查不到的返回 None —— **None 是「不知道」,
不是「不支持」**。不知道时维持现有行为(照发 json_schema,被拒了再降级),那条路本来就是对的,
只是白花一个往返。

来源(2026-09 查证):

- OpenAI —— developers.openai.com/api/docs/guides/structured-outputs(官方):json_schema +
  strict「ensures the model will always generate responses that adhere to your supplied JSON Schema」
- DeepSeek —— api-docs.deepseek.com/guides/json_mode(官方):**只有** `{"type":"json_object"}`,
  文档里没有 json_schema;而且提示词里必须出现 "json" 这个词,否则直接 400。
"""

from __future__ import annotations

#: vendor → 支不支持 `json_schema`。**按 vendor 而不是按模型**:这是端点的能力,不是某个模型的。
#:
#: 中转(`openai-compatible`)刻意不写:它后面挂的可能是任何一家,猜错哪一边都有代价 ——
#: 猜"支持"会让不支持的端点白撞一次 400,猜"不支持"会让支持的端点白白失去硬约束。
KNOWN_VENDOR_SUPPORT: dict[str, bool] = {
    "openai": True,
    "openai-codex": True,
    "github-copilot": True,
    "azure-openai": True,
    "deepseek": False,
}


def known_support(vendor: str) -> bool | None:
    """这个 vendor 的结论;没查证过返回 None(**不知道**,不是不支持)。"""
    return KNOWN_VENDOR_SUPPORT.get((vendor or "").strip().lower())


def effective_support(vendor: str, override: bool | None) -> bool | None:
    """用户在模型设置里填的优先;没填就用查证过的;都没有就是不知道。

    `override` 是模型行上的 `structured_output`:`None` = 没设过(**和 False 是两回事**)。
    """
    return override if override is not None else known_support(vendor)
