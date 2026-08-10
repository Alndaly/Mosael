"""给人看的文字上的小工具。叶子模块 —— 不 import 任何 app 内部的东西。"""

from __future__ import annotations

import re

#: CSI 序列(颜色、光标移动)以及 OSC 序列(设置标题之类)。
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


def strip_ansi(text: str) -> str:
    """去掉终端转义序列。

    子进程(pip、huggingface_hub、rich 的彩色 traceback)默认当自己在终端里,输出带颜色码。
    这些文字的去处常常是**浏览器**:任务的 error 字段、下载失败的提示、日志页。转义序列在
    那里不会变成颜色,只会变成 `[1;35m` 这样的乱码画在句子中间 —— 用户截图里就是这样。

    所以凡是"子进程说的话 → 界面"这条路上,都要先过这里一次。
    """
    return _ANSI.sub("", text)
