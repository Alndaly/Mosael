"""Text Toolkit — Mosael 插件 entry 脚本示例。

协议:stdin 读一个 JSON 请求 {"tool": name, "input": {...}, "locale": "zh"},stdout 写一个
JSON 响应 {"ok": true, "output": {...}} 或 {"ok": false, "error": "..."}。
纯标准库、纯函数:不碰网络、文件系统或数据库。

**跑出来的字由插件自己定语言**:清单里的文案由 Mosael 按界面语言挑,而这里产出的摘要、
失败原因只有插件写得出 —— 所以每次调用都告诉它读的人在用哪种语言(请求体里的 `locale`,
或环境变量 `MOSAEL_LOCALE`)。
"""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata

#: 朗读速度:中文每秒约 4.5 字,英文每分钟约 150 词(每秒 2.5 词)。**两种语言各按各的单位算** ——
#: 按字符算的话,英文的一个词有五六个字符,念完的时间被估长两三倍。
CJK_PER_SECOND = 4.5
WORDS_PER_SECOND = 2.5

#: 一个「词」:字母数字连成的一段,中间可以有撇号、连字符、小数点(`It's`、`well-known`、`3.14`)。
_WORD = re.compile(r"[^\W_]+(?:['’.\-][^\W_]+)*")


class ToolError(ValueError):
    """说得出口的失败,原样交回。"""


def _line(locale: str, zh: str, en: str) -> str:
    """一句给人看的话。按主语言挑 —— `zh-CN` 和 `zh` 是同一件事。"""
    return zh if locale.replace("_", "-").split("-")[0].lower() == "zh" else en


def _is_wide(ch: str) -> bool:
    """全角宽度的字符:汉字、假名、谚文,以及全角标点。"""
    return unicodedata.east_asian_width(ch) in ("W", "F")


def _is_cjk(ch: str) -> bool:
    """中日韩的「字」:全角宽度的文字(标点不算,它们不是字也不念)。"""
    return unicodedata.east_asian_width(ch) in ("W", "F") and ch.isalnum()


def word_count(payload: dict, locale: str) -> dict:
    """字数、词数、念完要多久。

    词数:中日韩文**一个字算一个词**(没有空格可切,Word、WPS 也是这么数的),其余按词。此前 `[\\w一-鿿]+`
    会把一整串汉字连成一个词 —— `\\w` 本来就包含汉字 —— 于是「你好世界」是 1 个词。
    """
    text = str(payload.get("text", ""))
    chars = sum(1 for ch in text if not ch.isspace())
    cjk = sum(1 for ch in text if _is_cjk(ch))
    words = len(_WORD.findall("".join(" " if _is_cjk(ch) else ch for ch in text)))
    seconds = round(cjk / CJK_PER_SECOND + words / WORDS_PER_SECOND, 1)
    return {
        "chars": chars,
        "words": cjk + words,
        "estimated_seconds": seconds,
        "summary": _line(locale, f"{chars} 字,念完约 {seconds} 秒", f"{chars} characters, about {seconds}s to read"),
    }


#: 成对的话题:微博 / 抖音的 `#话题#`。中间不能有空白 —— 否则 `#AI and #ML` 会被当成一个叫「AI and 」的话题。
_PAIRED = re.compile(r"(?<![A-Za-z0-9_&/])#([^#\s]{1,30})#")
#: 单个井号的标签:`#sunset`、`#旅行`。到第一个非字母数字处为止(`#sunset!` 是 sunset)。
#: 前面紧挨着英文字母数字、`&`、`/` 的不算:`C#`、`&#123;`、`https://x.com/a#frag`。
_SINGLE = re.compile(r"(?<![A-Za-z0-9_&/#])#(\w{1,50})")


def _is_tag(tag: str) -> bool:
    """全是数字的不算(`#1`、`#2024` 是编号,不是话题)。"""
    return bool(re.search(r"[^\W\d_]", tag))


def extract_hashtags(payload: dict, locale: str) -> dict:
    """提取 `#话题#` 与 `#hashtag`,按出现的先后;大小写不同的算同一个(留第一次的写法)。"""
    text = str(payload.get("text", ""))
    found: list[tuple[int, str]] = [(m.start(), m.group(1)) for m in _PAIRED.finditer(text)]
    # 成对的那一段挖掉再找单个的:`#好物#` 不该再被认成一个 `#好物`。换成空格,不让前后两段粘在一起。
    rest = _PAIRED.sub(lambda m: " " * len(m.group(0)), text)
    found += [(m.start(), m.group(1)) for m in _SINGLE.finditer(rest)]
    tags: dict[str, str] = {}
    for _, tag in sorted(found):
        if _is_tag(tag):
            tags.setdefault(tag.casefold(), tag)
    listed = list(tags.values())
    return {
        "hashtags": listed,
        "count": len(listed),
        "summary": _line(locale, f"找到 {len(listed)} 个话题标签", f"Found {len(listed)} hashtags"),
    }


def _whole_number(payload: dict, key: str, default: int, locale: str) -> int:
    """表单、工作流节点送来的数字可能是字符串(`"16"`)。留空用缺省;不是正整数就直说。"""
    raw = payload.get(key)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(float(str(raw).strip()))
    except ValueError:
        value = 0
    if value <= 0:
        raise ToolError(_line(locale, f"{key} 要是一个正整数,收到的是 {raw!r}。", f"{key} must be a positive whole number, got {raw!r}."))
    return value


def _flag(payload: dict, key: str, default: bool) -> bool:
    """开关:true / false,也认表单送来的 "true" / "false"。"""
    raw = payload.get(key)
    if raw is None or str(raw).strip() == "":
        return default
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in ("true", "1", "yes", "on")


# ---------------- 断句成字幕行 ----------------

#: 一句话到这里结束。连着的(`?!`、`……`)和紧跟的右引号、右括号跟着上一句走。
_ENDS = "。！？!?…"
_CLOSERS = "”’」』）)》】"
#: 句子太长时优先在这些标点后面切。
_PAUSES = "，,、；;：:" + _ENDS
#: 字幕行尾不留的标点(字幕的惯例:逗号、句号省掉;问号、叹号、省略号带语气,留着)。
_TRIM_AT_END = "，,。、；;：:"


def _width(text: str) -> float:
    """一行有多宽:中日韩的字(和全角标点)算 1,英文字母、数字、半角标点算半个 —— 两个字母大约占一个汉字的宽。"""
    return sum(1.0 if unicodedata.east_asian_width(ch) in ("W", "F") else 0.5 for ch in text)


def _sentences(text: str) -> list[str]:
    """按句切;换行本身也是一次断开。英文的 `.` `;` 要后面跟空白才算句末 —— `3.14`、`v1.2` 不切。"""
    out: list[str] = []
    buf = ""
    i = 0
    while i < len(text):
        ch = text[i]
        i += 1
        if ch == "\n":
            out.append(buf)
            buf = ""
            continue
        buf += ch
        if ch in _ENDS or (ch in ".;" and (i == len(text) or text[i].isspace())):
            while i < len(text) and (text[i] in _ENDS or text[i] in _CLOSERS):
                buf += text[i]
                i += 1
            out.append(buf)
            buf = ""
    out.append(buf)
    return [one.strip() for one in out if one.strip()]


def _atoms(sentence: str) -> list[tuple[str, bool]]:
    """切成不能再拆的小段:一个汉字一段、一个英文词一段,标点粘在前一段上(行首不会是一个逗号)。
    → [(文字, 前面有没有空格)]"""
    atoms: list[list] = []
    spaced = False
    for ch in sentence:
        if ch.isspace():
            spaced = True
            continue
        last = atoms[-1][0][-1] if atoms else ""
        if atoms and not spaced and unicodedata.category(ch).startswith("P"):
            atoms[-1][0] += ch
        elif atoms and not spaced and not _is_wide(ch) and not _is_wide(last):
            # 半角的字连着就是一段,中间的标点也算在里面:`3.14`、`e.g.`、一个网址都不从中间断开。
            atoms[-1][0] += ch
        else:
            atoms.append([ch, spaced])
        spaced = False
    return [(text, space) for text, space in atoms]


def _join(atoms: list[tuple[str, bool]]) -> str:
    return "".join((" " if space and i else "") + text for i, (text, space) in enumerate(atoms))


def _fit(atoms: list[tuple[str, bool]]) -> float:
    """一行占多宽。行尾的逗号、句号不算 —— 按字幕惯例它们会被省掉,留着也是悬在行外(中文排版的「标点悬挂」)。"""
    return _width(_join(atoms).rstrip(_TRIM_AT_END))


def _clauses(atoms: list[tuple[str, bool]]) -> list[list[tuple[str, bool]]]:
    """在停顿(逗号、顿号、分号……)后面切开。"""
    out: list[list[tuple[str, bool]]] = [[]]
    for atom in atoms:
        out[-1].append(atom)
        if atom[0][-1] in _PAUSES:
            out.append([])
    return [one for one in out if one]


def _even(clause: list[tuple[str, bool]], limit: int) -> list[list[tuple[str, bool]]]:
    """一个比整行还长的分句切成几段**差不多长**的,而不是先塞满一行、剩一两个字吊在下一行。
    一个比整行还长的英文词自己占一行。"""
    count = -(-_fit(clause) // limit)
    target = _fit(clause) / count
    parts: list[list[tuple[str, bool]]] = [[]]
    for atom in clause:
        grown = _fit([*parts[-1], atom])
        if parts[-1] and (grown > limit or (len(parts) < count and grown > target + 0.25)):
            parts.append([])
        parts[-1].append(atom)
    return parts


def _pack(atoms: list[tuple[str, bool]], limit: int) -> list[str]:
    """把一句话装进若干行,每行不超过 `limit` 宽:相邻的分句放得下就并成一行,放不下的分句均分。"""
    lines: list[list[tuple[str, bool]]] = []
    current: list[tuple[str, bool]] = []
    for clause in _clauses(atoms):
        if current and _fit([*current, *clause]) <= limit:
            current += clause
            continue
        if current:
            lines.append(current)
        if _fit(clause) <= limit:
            current = clause
            continue
        *full, current = _even(clause, limit)
        lines += full
    if current:
        lines.append(current)
    return [_join([(text, space if i else False) for i, (text, space) in enumerate(line)]) for line in lines]


def split_lines(payload: dict, locale: str) -> dict:
    """把一段口播稿断成字幕行:一句一句来,太长的句子在停顿处再切,每行不超过 `max_chars` 个字宽。"""
    text = str(payload.get("text", ""))
    limit = _whole_number(payload, "max_chars", 16, locale)
    keep = _flag(payload, "keep_punctuation", False)
    lines: list[str] = []
    for sentence in _sentences(text):
        for line in _pack(_atoms(sentence), limit):
            if not keep:
                line = line.rstrip(_TRIM_AT_END)
                if line.endswith(".") and not line.endswith(".."):
                    line = line[:-1]
            if line.strip():
                lines.append(line.strip())
    return {
        "lines": lines,
        "count": len(lines),
        "text": "\n".join(lines),
        "summary": _line(locale, f"断成 {len(lines)} 行,每行不超过 {limit} 字", f"{len(lines)} lines, at most {limit} characters wide each"),
    }


# ---------------- 截短 ----------------


def truncate(payload: dict, locale: str) -> dict:
    """截到 `max_chars` 个字以内(省略号也算在里面)。尽量停在一个停顿或词的边界上 —— 但不为了找边界
    往回退超过四成,那样截出来的太短。"""
    text = " ".join(str(payload.get("text", "")).split())
    limit = _whole_number(payload, "max_chars", 20, locale)
    ellipsis = str(payload["ellipsis"]) if payload.get("ellipsis") is not None else "…"
    if len(text) <= limit:
        return {"text": text, "chars": len(text), "removed": 0,
                "summary": _line(locale, f"{len(text)} 字,没有超过 {limit},原样保留", f"{len(text)} characters, within {limit}; kept as is")}
    if len(ellipsis) >= limit:
        ellipsis = ""
    room = limit - len(ellipsis)
    head = text[:room]
    following = text[room]
    if not (following.isspace() or following in _PAUSES):
        for i in range(len(head) - 1, int(room * 0.6) - 1, -1):
            if head[i].isspace() or head[i] in _PAUSES:
                head = head[: i + 1]
                break
    head = head.rstrip().rstrip(_TRIM_AT_END + ".").rstrip()
    result = head + ellipsis
    return {
        "text": result,
        "chars": len(result),
        "removed": len(text) - len(head),
        "summary": _line(locale, f"从 {len(text)} 字截到 {len(result)} 字", f"Cut from {len(text)} to {len(result)} characters"),
    }


# ---------------- 清理文案 ----------------

#: 看不见、却会让「两段一样的字」比较不相等、让平台字数统计对不上的字符。
#: 零宽连接符(U+200D)不在里面:它把 👨‍👩‍👧 这种表情连成一个,删了就散成三个。
_INVISIBLE = re.compile("[\u200b\u2060\ufeff\u00ad]")
_CJK_CLASS = "\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af"
#: 中文字后面紧跟的半角标点 → 全角。`.` 只在后面不是字母数字时换(`版本1.2` 里那个不动)。
_HALF_TO_FULL = {",": "，", "?": "？", "!": "！", ":": "：", ";": "；", ".": "。"}
_CJK_THEN_PUNCT = re.compile(rf"(?<=[{_CJK_CLASS}])([,?!:;]|\.(?![0-9A-Za-z]))[ \t]*")
_EMOJI = re.compile(
    "[\U0001f000-\U0001faff\u2600-\u27bf\u2b00-\u2bff\u2300-\u23ff\ufe0f\u200d\U000e0020-\U000e007f]"
)


def _half_width(ch: str) -> str:
    """全角的字母、数字 → 半角(`ＡＢＣ１２３` → `ABC123`)。全角标点不动 —— 中文里它们本来就该是全角。"""
    code = ord(ch)
    if 0xFF10 <= code <= 0xFF19 or 0xFF21 <= code <= 0xFF3A or 0xFF41 <= code <= 0xFF5A:
        return chr(code - 0xFEE0)
    return ch


def clean_text(payload: dict, locale: str) -> dict:
    """清理一段文案:去掉看不见的字符、多余的空格和空行,全角字母数字换半角;可选把中文后面的半角标点
    换成全角、在中英文之间加空格、去掉表情。段落(一个空行隔开)保留。"""
    original = str(payload.get("text", ""))
    text = _INVISIBLE.sub("", original.replace("\r\n", "\n").replace("\r", "\n"))
    text = "".join(_half_width(ch) for ch in text).replace("　", " ")
    if _flag(payload, "remove_emoji", False):
        text = _EMOJI.sub("", text)
    if _flag(payload, "chinese_punctuation", True):
        text = _CJK_THEN_PUNCT.sub(lambda m: _HALF_TO_FULL[m.group(1)], text)
    if _flag(payload, "space_between", False):
        text = re.sub(rf"([{_CJK_CLASS}])([A-Za-z0-9])", r"\1 \2", text)
        text = re.sub(rf"([A-Za-z0-9])([{_CJK_CLASS}])", r"\1 \2", text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    removed = len(original) - len(text)
    return {
        "text": text,
        "chars": len(text),
        "summary": _line(locale, f"清理后 {len(text)} 字,去掉了 {max(removed, 0)} 个字符", f"{len(text)} characters after cleanup, {max(removed, 0)} removed"),
    }


# ---------------- 去掉 Markdown ----------------

_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_MD_AUTOLINK = re.compile(r"<(https?://[^>]+)>")
_MD_EMPHASIS = (
    re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1"),
    re.compile(r"~~(?=\S)(.+?)(?<=\S)~~"),
    re.compile(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?!\*)"),
    re.compile(r"(?<![\w_])_(?=\S)(.+?)(?<=\S)_(?![\w_])"),
)
_MD_CODE = re.compile(r"`([^`]+)`")
_HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>")


def _inline_plain(line: str, keep_urls: bool) -> str:
    line = _MD_IMAGE.sub(r"\1", line)
    line = _MD_LINK.sub((lambda m: f"{m.group(1)} ({m.group(2)})") if keep_urls else (lambda m: m.group(1)), line)
    line = _MD_AUTOLINK.sub(r"\1", line)
    line = _MD_CODE.sub(r"\1", line)
    for pattern in _MD_EMPHASIS:
        line = pattern.sub(lambda m: m.group(m.lastindex), line)
    line = re.sub(r"<br\s*/?>", "\n", line, flags=re.IGNORECASE)
    return _HTML_TAG.sub("", line)


def strip_markdown(payload: dict, locale: str) -> dict:
    """Markdown → 平台上能直接贴的纯文本:标题、加粗、链接、引用这些记号去掉,列表换成「• 」,代码块留代码。"""
    keep_urls = _flag(payload, "keep_urls", False)
    out: list[str] = []
    fenced = False
    for raw in str(payload.get("text", "")).replace("\r\n", "\n").split("\n"):
        if re.match(r"^\s*(```|~~~)", raw):
            fenced = not fenced
            continue
        if fenced:
            out.append(raw)
            continue
        line = raw
        if re.match(r"^\s*([-*_])(\s*\1){2,}\s*$", line):
            out.append("")
            continue
        if re.match(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$", line):
            continue
        line = re.sub(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$", r"\1", line)
        line = re.sub(r"^(\s*>\s?)+", "", line)
        line = re.sub(r"^(\s*)[-*+]\s+\[[ xX]\]\s+", r"\1• ", line)
        line = re.sub(r"^(\s*)[-*+]\s+", r"\1• ", line)
        if line.strip().startswith("|") and line.strip().endswith("|"):
            line = "  ".join(cell.strip() for cell in line.strip().strip("|").split("|"))
        out.append(_inline_plain(line, keep_urls).rstrip())
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    return {
        "text": text,
        "chars": len(text),
        "summary": _line(locale, f"去掉格式后 {len(text)} 字", f"{len(text)} characters of plain text"),
    }


# ---------------- 链接、@ 提及、邮箱 ----------------

#: 网址到空白或中日韩文字为止:文案里网址后面常常直接跟着中文(`见 https://x.com/a,谢谢`)。
_URL = re.compile(r"(?:https?://|www\.)[^\s<>\"'\u3000-\u9fff\uac00-\ud7af\uff00-\uffef]+", re.IGNORECASE)
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
#: `@` 前面紧挨着字母数字、`/`、`.` 的不算提及:邮箱(`a@b.com`)、网址里的(`medium.com/@me`)。
_MENTION = re.compile(r"(?<![\w/.@])@([\w\-]{1,30})")


def _unique(items: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    for item in items:
        seen.setdefault(item.casefold(), item)
    return list(seen.values())


def extract_links(payload: dict, locale: str) -> dict:
    """提取文案里的网址、@ 提及和邮箱,各按出现的先后,重复的只留第一次。网址末尾粘着的标点(`.` `)`)不算进去。"""
    text = str(payload.get("text", ""))
    urls = _unique([m.group(0).rstrip(".,;:!?)]'\"") for m in _URL.finditer(text)])
    emails = _unique([m.group(0).rstrip(".") for m in _EMAIL.finditer(text)])
    without = _URL.sub(" ", _EMAIL.sub(" ", text))
    mentions = _unique([m.group(1).rstrip(".-") for m in _MENTION.finditer(without)])
    count = len(urls) + len(mentions) + len(emails)
    return {
        "urls": urls,
        "mentions": mentions,
        "emails": emails,
        "count": count,
        "summary": _line(
            locale,
            f"{len(urls)} 个网址、{len(mentions)} 个 @ 提及、{len(emails)} 个邮箱",
            f"{len(urls)} links, {len(mentions)} mentions, {len(emails)} emails",
        ),
    }


TOOLS = {
    "word_count": word_count,
    "extract_hashtags": extract_hashtags,
    "split_lines": split_lines,
    "truncate": truncate,
    "clean_text": clean_text,
    "strip_markdown": strip_markdown,
    "extract_links": extract_links,
}


def main() -> None:
    locale = "zh"
    try:
        request = json.loads(sys.stdin.read())
        locale = str(request.get("locale") or os.environ.get("MOSAEL_LOCALE") or "zh")
        name = str(request.get("tool"))
        tool = TOOLS.get(name)
        if tool is None:
            raise ToolError(_line(locale, f"不认识的工具:{name}", f"Unknown tool: {name}"))
        payload = request.get("input") or {}
        if not isinstance(payload, dict):
            raise ToolError(_line(locale, "input 要是一个 JSON 对象。", "input must be a JSON object."))
        json.dump({"ok": True, "output": tool(payload, locale)}, sys.stdout, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 — report, don't crash silently
        json.dump({"ok": False, "error": str(exc)}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
