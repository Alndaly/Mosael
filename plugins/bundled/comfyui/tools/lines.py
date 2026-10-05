"""插件自己说的话:按读的人的语言挑一句,以及「做不成」的那种错。

清单里的文案宿主替我们挑;**运行时**说的话(失败原因、进度)只有插件写得出,宿主在每次调用里
告诉我们读的人用哪种语言(请求体的 `locale`,环境变量 `MOSAEL_LOCALE`)。

失败原因还多一层:宿主会把它**存下来**(连接卡片上的出错原因),而存它的那一刻(后台刷新、另一种界面语言)
不是读它的人的语言。所以失败时两种语言都交出去(`{"zh": …, "en": …}`),宿主给人看时再挑。
"""

from __future__ import annotations


class Line(str):
    """一句话:它本身就是按读的人的语言挑好的那句(当场念给人听的进度、摘要直接用),
    另外记着两种语言各怎么说(`texts`)—— 落进 ComfyError 时整份交给宿主。

    拼接、格式化之后得到的是普通的 str(只剩挑好的那一种),那样的失败原因宿主照单显示。
    """

    texts: dict[str, str]

    def __new__(cls, picked: str, zh: str, en: str) -> Line:
        line = super().__new__(cls, picked)
        line.texts = {"zh": zh, "en": en}
        return line


class ComfyError(Exception):
    """做不成。消息已经是给人看的那一句(按语言挑好了);是 `say` 说的,两种语言都带着(见 `said`)。"""

    def __init__(self, message: str, *, status: int = 0, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body
        self.texts: dict[str, str] | None = getattr(message, "texts", None)

    @property
    def said(self) -> dict[str, str] | str:
        """交给宿主的失败原因:两种语言都在就按语言分着交,否则就是这一句。"""
        return dict(self.texts) if self.texts else str(self)


def say(locale: str, zh: str, en: str) -> Line:
    return Line(zh if (locale or "zh").lower().startswith("zh") else en, zh, en)
