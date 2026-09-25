"""插件自己说的话:按读的人的语言挑一句,以及「做不成」的那种错。

清单里的文案宿主替我们挑;**运行时**说的话(失败原因、进度)只有插件写得出,宿主在每次调用里
告诉我们读的人用哪种语言(请求体的 `locale`,环境变量 `MOSAEL_LOCALE`)。
"""

from __future__ import annotations


class ComfyError(Exception):
    """做不成。消息已经是给人看的那一句(按语言挑好了),插件入口原样交给宿主。"""

    def __init__(self, message: str, *, status: int = 0, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def say(locale: str, zh: str, en: str) -> str:
    return zh if (locale or "zh").lower().startswith("zh") else en
