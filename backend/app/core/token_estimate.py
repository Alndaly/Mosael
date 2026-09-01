"""正文的 token 估算。

**纯函数,住在 core** —— 没有一行数据库、不认识任何领域概念,却被 `ai/providers/contracts/generation.py`
引用。放在 domain 会让整棵适配器树为了一个字符串统计而依赖领域层。

名字不叫 `tokens`:那个已经被**认证 token** 占着(core/tokens.py 的 token_digest)。
两个「token」在这个仓库里是完全不同的两件事,重名会让下一个人 import 错那一个。

它是估算不是账单:调用方用 token_estimate=true 标出来,足够画首页图表和看趋势,不能当成
供应商的计费记录。
"""

from __future__ import annotations

import re


def estimate_text_tokens(text: str) -> int:
    """Cheap local token estimate for providers that do not return token usage.

    This is intentionally marked by callers with token_estimate=true: it is good enough for
    home charts and usage auditing trends, but not a substitute for provider billing records.
    """
    stripped = text.strip()
    if not stripped:
        return 0
    cjk_chars = len(re.findall(r"[\u3400-\u9fff\uf900-\ufaff]", stripped))
    non_cjk = re.sub(r"[\u3400-\u9fff\uf900-\ufaff\s]", "", stripped)
    latinish_tokens = len(non_cjk) / 4
    return max(1, round(cjk_chars + latinish_tokens))
