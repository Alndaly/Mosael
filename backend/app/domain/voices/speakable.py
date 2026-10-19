"""把「屏幕上那一份文字」变成「念出来是那个意思的文字」。

**为什么需要这一层。** 每个入口交给配音引擎的都是**屏幕上那一份 markdown**:助手回复、笔记正文、
画板提示词、工作流里拼出来的稿子。引擎不认识 markdown —— 它只看见一串标点,于是 `*` 念「星号」、
`#` 念「井号」、`|` 念「竖线」,URL 被逐字符念成一串字母。用户听到的是排版,不是话(维护者原话:
「现在所有地方的语音为何会将部分符号念出来 —— 比如 `*` 会念成「星号」」)。

**为什么在这里、只在这里。** 域里到引擎的路只有两扇门:`start_synthesis`(建任务那条:配音、画板音、
工作流合成词、字幕逐句配音)和 `speak_to_file`(直接拿音频那条:对话朗读、免提、试听、笔记朗读)。
两个门都在**把文本交给任何人之前**调这一个函数 —— 在调用点各加一遍的话,漏掉的那一处不会报错,
只会在用户耳朵里出现一次「星号」。函数是**幂等**的:任务那条路会经过两扇门,第二遍必须什么都不改。

**只删标记,不删字。** `**粗体**` → 「粗体」;表格竖线去掉、格子里的字留着;标题只去 `#`。
该念的照旧:数字、单位、百分号、中英文标点一个不动。URL 整条跳过 —— 要么念域名、要么不念,
逐字符念是最糟的那种。洗完什么都不剩(只剩标记)就交回空串,由两扇门按「没话可念」退回去,
而不是合成一串符号。
"""

from __future__ import annotations

import re

#: 转义的反斜杠不是文字:`\*` 就是一颗星。
_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!>~|])")

#: 代码围栏:**只去掉围栏那一行**,里面的字照念(让人听见代码里写了什么,总比听见一串反引号好)。
_FENCED = re.compile(r"(?ms)^[ \t]*(?:```|~~~)[^\n]*\n(.*?)^[ \t]*(?:```|~~~)[ \t]*$")
#: 没配对的围栏(流式回复到一半就送来了):去掉那一行,后面的内容留着。
_FENCE_LINE = re.compile(r"(?m)^[ \t]*(?:```|~~~)[^\n]*$")
#: 图片 / 链接:`![说明](地址)`、`[文档](地址)` → 说明 / 文档。地址本身不念。
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)\s]*(?:\s+\"[^\"]*\")?\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)\s]*(?:\s+\"[^\"]*\")?\)")
_AUTOLINK = re.compile(r"<(?:https?|ftp)://[^>\s]+>|<mailto:[^>\s]+>", re.I)

#: 裸地址:**整条跳过**。到空白、括号、引号、中文标点、汉字为止 —— 中文后面紧跟的字是话,不是地址。
_URL = re.compile(
    r"(?:https?://|ftp://|www\.)[^\s<>()（）\[\]\"'“”‘’「」\u3000-\u303f\u3400-\u9fff\uff00-\uffef]+",
    re.I,
)

#: 表格的分隔行(`|---|---|`、`:---:`):整行没有要念的字。
_TABLE_RULE = re.compile(r"(?m)^[ \t]*\|?[ \t]*:?-{1,}:?[ \t]*(?:\|[ \t]*:?-{1,}:?[ \t]*)*\|?[ \t]*$")
#: 分隔线(`---`、`***`、`___`):同上。
_HORIZONTAL_RULE = re.compile(r"(?m)^[ \t]*(?:(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})$")
_HEADING = re.compile(r"(?m)^[ \t]{0,3}#{1,6}[ \t]*")
_BLOCKQUOTE = re.compile(r"(?m)^[ \t]{0,3}>[ \t]?")
_TASK = re.compile(r"(?m)^[ \t]{0,3}\[[ xX]\][ \t]*")
#: 列表符:**只去符号,条目的话全留着**(列表是助手最常写的东西)。
_LIST = re.compile(r"(?m)^[ \t]{0,3}(?:[-*+]|\d{1,9}[.)])[ \t]+")

#: 行内代码的反引号:去符号、留内容。
_INLINE_CODE = re.compile(r"`+([^`]*)`+")
#: 强调 / 删除线:`**粗体**`、`*斜体*`、`__粗体__`、`~~删除~~` → 里面的字。
_EMPHASIS = re.compile(r"(\*\*\*|\*\*|___|__|\*|_|~~)(?=\S)(.+?)(?<=\S)\1")

_CJK = "\u3400-\u9fff\u3000-\u303f\uff00-\uffef"
#: 中文之间的破折号是一个停顿,换成逗号;拉丁词之间的是一个空格。
_EM_DASH_BETWEEN_CJK = re.compile(rf"(?<=[{_CJK}])[—–―]+(?=[{_CJK}])")
_DASH = re.compile(r"[—–―]+")
#: 省略号:语气,不是字。不去的话有的引擎会念「省略号」。
_ELLIPSIS = re.compile(r"…+")
#: 表格竖线:去符号,格子之间留一个空格。
_TABLE_PIPE = re.compile(r"[ \t]*\|[ \t]*")
#: 漏网的标记字符(`*`、`#`、反引号、`~`、`^`):没有任何一个是「话」。
_NOISE = re.compile(r"[*`~#^]+")
#: 下划线:mardown 的强调符,也是 `snake_case` 的分隔 —— 换成空格,念出来是「snake case」。
_UNDERSCORE = re.compile(r"_+")

_SPACES = re.compile(r"[ \t\u00a0]+")
_SPACE_AROUND_NEWLINE = re.compile(r"[ \t]*\n[ \t]*")
_BLANK_LINES = re.compile(r"\n{3,}")
#: 「还有字可念吗」:字母、数字、汉字算字;只剩标点、emoji、空白就是没话可念。
_HAS_WORDS = re.compile(r"[^\W_]")


def speakable_text(text: str) -> str:
    """一段给人看的文字 → 一段念出来是那个意思的文字。**幂等**:洗第二遍不会再变。"""
    if not text:
        return ""
    spoken = text.replace("\r\n", "\n").replace("\r", "\n")
    spoken = _ESCAPE.sub(r"\1", spoken)
    # 顺序有讲究:围栏 / 链接先处理(它们的标记里含有别的标记),列表符在表格分隔行之后
    # (否则 `|---|---|` 会被当成列表删剩 `---|`)。
    spoken = _FENCED.sub(lambda match: match.group(1), spoken)
    spoken = _FENCE_LINE.sub("", spoken)
    spoken = _IMAGE.sub(lambda match: match.group(1), spoken)
    spoken = _LINK.sub(lambda match: match.group(1), spoken)
    spoken = _AUTOLINK.sub("", spoken)
    spoken = _URL.sub("", spoken)
    spoken = _TABLE_RULE.sub("", spoken)
    spoken = _HORIZONTAL_RULE.sub("", spoken)
    spoken = _HEADING.sub("", spoken)
    spoken = _BLOCKQUOTE.sub("", spoken)
    spoken = _TASK.sub("", spoken)
    spoken = _LIST.sub("", spoken)
    spoken = _INLINE_CODE.sub(lambda match: match.group(1), spoken)
    spoken = _EMPHASIS.sub(lambda match: match.group(2), spoken)
    spoken = _TABLE_PIPE.sub(" ", spoken)
    spoken = _EM_DASH_BETWEEN_CJK.sub("，", spoken)
    spoken = _DASH.sub(" ", spoken)
    spoken = _ELLIPSIS.sub("", spoken)
    spoken = _NOISE.sub("", spoken)
    spoken = _UNDERSCORE.sub(" ", spoken)
    spoken = _SPACE_AROUND_NEWLINE.sub("\n", spoken)
    spoken = _SPACES.sub(" ", spoken)
    spoken = _BLANK_LINES.sub("\n\n", spoken).strip()
    return spoken if _HAS_WORDS.search(spoken) else ""


__all__ = ["speakable_text"]
