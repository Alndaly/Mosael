"""配音领域的错误类型。

叶子模块:合成(`voices`)和远端副本(`remote`)都要抛它,而 `voices.speak_to_file` 要调 `remote` —— 错误类型放在
`voices` 里的话,`remote` 要回头 import 它,成了环。
"""

from __future__ import annotations

from app.core.i18n import LocalizedError


class VoiceError(LocalizedError, RuntimeError):
    """配音/声音克隆的领域错误。带文案 key(`voiceErr_*`),按读的人的语言翻(见 core/i18n)。

    这几句会原样显示在界面上 —— 文案里只写纯文本,不要 markdown。
    """


__all__ = ["VoiceError"]
