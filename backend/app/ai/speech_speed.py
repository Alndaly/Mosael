"""语速由谁来调。

这是 ``providers.contracts.speech`` 和 ``ai.runtime.tts_models`` 共用的一个**叶子类型**:
放在契约里会让 runtime 反向 import providers,而 providers 的本地适配器又要 import runtime,
形成包级循环。语速的两种实现方式不属于任何一方,放这里两边都能引。
"""

from __future__ import annotations

from typing import Literal

#: `native`:请求里带上语速,引擎自己念;`stretch`:引擎没有这个参数,宿主合成之后变速(音高不变)。
SpeedControl = Literal["native", "stretch"]

__all__ = ["SpeedControl"]
