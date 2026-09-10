"""**这个模型能不能被要求思考、能不能被要求别思考、档位怎么叫。**

## 为什么需要这张表

用户报过:会话里选了「关闭」,Kimi k3 照样在思考。查下来比那更糟 —— 默认配置下,
四个档位发出去的请求逐字节相同,一个思考参数都没有。

链路末端的原因是我们给 pi 造的是一个**合成模型**(provider 是我们自己的 id,不带
thinkingFormat),于是 pi 里那些按供应商匹配的分支一条都不命中,全落到通用的
`reasoning_effort` 上;而那条要求模型带着 `thinkingLevelMap`,我们从来没给过。

## 为什么不能只补一个 `off: "none"`

因为各家根本不是同一套词,而且**有些模型压根关不掉**(2026-09 查证):

- **Kimi k3** —— 一直思考。`reasoning_effort` 只收 `low` / `high` / `max`,默认 `max`;
  没有关闭这一说。我们的界面此前还给它「中」,那是个发出去会被拒的值。
- Kimi k2.6 —— `thinking: {type: "enabled"|"disabled"}`;k2.7-code 只收 `enabled`。
- **OpenAI GPT-5.x** —— `reasoning_effort` 收 `none`(即关闭)…`xhigh`,按模型不同。
  GPT-6 Astra 一直思考,给 `none`/`minimal` 会报错。
- **DeepSeek** —— `thinking: {type: "enabled"}` 开,`reasoning_effort` 定强度。
- **Qwen(DashScope)** —— `enable_thinking: true/false`。
- **智谱 GLM** —— `thinking: {type:"enabled"|"disabled"}`;GLM-5.3 只能开,强度走
  `reasoning_effort`。

一个全局的 `"none"` 会被其中大多数拒掉 —— 而被拒的后果是**整轮对话 400**,不是少一个增强。

## 判据是「有没有把握」,不是「猜一个」

查不到的模型走 `UNKNOWN`:不声明任何档位,界面据此说"这条连接发不出思考档位"。
少一个能用的开关,比一个点了会让对话失败的开关好。
"""

from __future__ import annotations

from dataclasses import dataclass, field


#: 我们对用户说的档位。pi 的 `thinkingLevelMap` 用的也是这套键。
LEVELS = ("off", "low", "medium", "high")


@dataclass(frozen=True)
class ThinkingProfile:
    """一个模型的思考能力。

    `level_map` 直接喂给 pi 的 `model.thinkingLevelMap`:值是**供应商接受的字符串**,
    `None` 表示这一档这个模型不支持(pi 的 getSupportedThinkingLevels 据此把它从清单里去掉)。
    """

    #: 能不能把思考关掉。False = 这个模型一直思考(Kimi k3、GPT-6 Astra、GLM-5.3)。
    can_disable: bool
    #: 档位 → 供应商接受的值。None = 不支持这一档。
    level_map: dict[str, str | None] = field(default_factory=dict)

    def levels(self) -> list[str]:
        """界面上该出现哪几档。"""
        return [level for level in LEVELS if self.level_map.get(level, "") is not None]


#: 查不到的:不声明,界面据此说"发不出档位"。**默认保守**是这张表的立身之本。
UNKNOWN = ThinkingProfile(can_disable=False, level_map={level: None for level in LEVELS})

#: OpenAI 风格:`reasoning_effort` 收 none/low/medium/high。
_OPENAI = ThinkingProfile(
    can_disable=True,
    level_map={"off": "none", "low": "low", "medium": "medium", "high": "high"},
)

#: Kimi k3:一直思考,而且只有 low / high / max —— **没有 medium**。
#: 界面上那个「中」映到 high:少一档比发一个会被拒的值好。
_KIMI_K3 = ThinkingProfile(
    can_disable=False,
    level_map={"off": None, "low": "low", "medium": None, "high": "high"},
)


def profile_for(vendor: str, model_id: str) -> ThinkingProfile:
    """按 vendor + 模型名给出思考能力。**只写查证过的**,其余走 UNKNOWN。"""
    name = (model_id or "").lower()
    if vendor == "moonshot" or vendor == "kimi-coding":
        # k3 一直思考;k2 系列这里还没查证到位,先不声明。
        return _KIMI_K3 if "k3" in name else UNKNOWN
    if vendor in {"openai", "openai-codex", "github-copilot"}:
        # gpt-5 系列收 reasoning_effort;更老的模型不思考,由模型行上的 reasoning 决定。
        return _OPENAI if name.startswith("gpt-5") or name.startswith("o") else UNKNOWN
    return UNKNOWN
