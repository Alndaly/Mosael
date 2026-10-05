"""智能体技能(Agent Skills,ADR 0040):一个文件夹,里面一份 `SKILL.md`(YAML 头 + Markdown 正文)和随意的文件。

格式是开放的那一份([agentskills.io/specification](https://agentskills.io/specification)),Claude Code、Claude API
和别家的智能体都认。**这里是唯一一份规则**:桌面后端读写工作区技能、导入 `.zip` / 文件夹、插件包带的 `skills/`、
社区收稿,过的都是它 —— 和插件清单同一个理由(ADR 0026):这边收得下的,那边也认。

## 头里有什么

| 字段 | 必填 | 规则 |
| --- | --- | --- |
| `name` | 是 | 1–64 个字符,`a-z0-9` 和连字符,不以连字符开头或结尾,不连着两个;和文件夹同名 |
| `description` | 是 | 1–1024 个字符:做什么、什么时候用 |
| `license` | 否 | 许可证名字或随附文件 |
| `compatibility` | 否 | ≤500 个字符 |
| `metadata` | 否 | 字符串到字符串的映射。Mosael 自己的扩展放这里:`mosael-title`(显示名) |
| `allowed-tools` | 否 | 实验性。**Mosael 读出来给人看,不预先批准任何东西**(ADR 0040 §6) |

`name` 按 Anthropic 的写法收(只认 ASCII),比参考校验器 skills-ref(收 Unicode 小写字母)严一档 —— Mosael 导出的技能
拿到 Claude 那边也认。规范之外的顶层字段(Claude Code 的 `disable-model-invocation` 等)**原样留着**:读的时候把那几行
原文收进 `extra`,写回时一字不改地放回去。

## 只认 YAML 的一个子集

这个包没有依赖(它要被系统 python3 直接 import),所以头由这里自己读:普通 / 单引号 / 双引号标量、`|` 与 `>` 块、
嵌套映射、块列表和流式列表 / 映射。锚点、别名、标签、多文档一律拒,并说是第几行。顺带挡住了 YAML 炸弹 ——
这份头来自别人发来的压缩包。真实世界的 SKILL.md 头都在这个子集里;backend 的测试拿 PyYAML 逐个对过。

所有标量都读成**字符串**(`version: 1.0` 是 `"1.0"`):规范要的就是字符串,而 YAML 1.1 那套把 `no` 读成 False 的
规矩在这里只会帮倒忙。`~` / `null` 读成空串。
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field, replace
from pathlib import PurePosixPath
from typing import Any

from mosael_formats.i18n import FormatError

SKILL_FILENAME = "SKILL.md"

#: `name`:小写字母、数字,中间用单个连字符隔开。
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_NAME_CHARS = 64
MAX_DESCRIPTION_CHARS = 1024
MAX_COMPATIBILITY_CHARS = 500
MAX_LICENSE_CHARS = 500
#: Mosael 的显示名(`metadata.mosael-title`)。列表一行、「/」菜单一行放得下。
TITLE_KEY = "mosael-title"
MAX_TITLE_CHARS = 80
KNOWN_FIELDS = ("name", "description", "license", "compatibility", "metadata", "allowed-tools")

#: 大小上限(ADR 0040 §6)。`SKILL.md` 用到时整份进上下文,所以它最紧。
MAX_SKILL_MD_BYTES = 64 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_SKILL_BYTES = 10 * 1024 * 1024
MAX_SKILL_FILES = 200
MAX_PATH_DEPTH = 8
#: 一个 `.zip` 解开后最多多大(挡压缩炸弹)、一次最多导入几个技能。
MAX_ARCHIVE_UNPACKED_BYTES = 20 * 1024 * 1024
MAX_SKILLS_PER_IMPORT = 20

#: 导入时悄悄丢掉的东西:系统和压缩软件塞进来的,不是作者写的。
JUNK_NAMES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini"})
JUNK_DIRS = frozenset({"__MACOSX", ".git"})

_DRIVE = re.compile(r"^[A-Za-z]:")


class SkillError(FormatError):
    """一份技能不合格。只带 key 和参数(见 i18n.MESSAGES 的 `skillErr_*`)。"""


# ---------------------------------------------------------------- 文档


@dataclass(frozen=True)
class SkillDoc:
    """读出来的一份 SKILL.md。`extra` 是规范之外的顶层字段:键 → 那几行**原文**(写回时原样放回)。"""

    name: str
    description: str
    body: str = ""
    license: str = ""
    compatibility: str = ""
    metadata: dict[str, str] = field(default_factory=dict)
    allowed_tools: str = ""
    #: `allowed-tools` 那几行原文。Mosael 不编辑它(它不批准任何东西),写回时原样放回。
    allowed_tools_raw: str = ""
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def title(self) -> str:
        """显示名:`metadata.mosael-title`,没写就是空串(界面退到 name)。"""
        return self.metadata.get(TITLE_KEY, "")

    def with_title(self, title: str) -> SkillDoc:
        metadata = {key: value for key, value in self.metadata.items() if key != TITLE_KEY}
        if title.strip():
            metadata = {TITLE_KEY: title.strip(), **metadata}
        return replace(self, metadata=metadata)


def parse_skill_md(text: str, *, folder: str | None = None) -> SkillDoc:
    """一份 SKILL.md → SkillDoc,并照规范校验。`folder` 给了就要求和 `name` 一致(插件包里的技能);
    导入时不给 —— 导入的技能按 `name` 落进同名文件夹,外层叫什么无所谓。"""
    if len(text.encode("utf-8")) > MAX_SKILL_MD_BYTES:
        raise SkillError("skillErr_skillMdTooLarge", limit=MAX_SKILL_MD_BYTES // 1024)
    head, body = split_frontmatter(text)
    data, raw_blocks = load_frontmatter(head)
    doc = _doc_from(data, raw_blocks, body)
    validate(doc, folder=folder)
    return doc


def split_frontmatter(text: str) -> tuple[str, str]:
    """`---` 包起来的头和后面的正文。头必须在第一行开始(前面只许有 BOM)。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    lines = text.split("\n")
    if not lines or lines[0].rstrip() != "---":
        raise SkillError("skillErr_noFrontmatter")
    for index in range(1, len(lines)):
        if lines[index].rstrip() in ("---", "..."):
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1:]).lstrip("\n")
    raise SkillError("skillErr_frontmatterUnclosed")


def _doc_from(data: dict[str, Any], raw_blocks: dict[str, str], body: str) -> SkillDoc:
    for key in ("name", "description", "license", "compatibility"):
        if key in data and not isinstance(data[key], str):
            raise SkillError("skillErr_fieldNotText", field=key)
    metadata = data.get("metadata", {})
    if metadata == "":
        metadata = {}
    if not isinstance(metadata, dict) or not all(isinstance(value, str) for value in metadata.values()):
        raise SkillError("skillErr_metadataNotStrings")
    tools = data.get("allowed-tools", "")
    if isinstance(tools, list):
        tools = " ".join(str(one) for one in tools if isinstance(one, str))
    elif not isinstance(tools, str):
        tools = ""
    return SkillDoc(
        name=str(data.get("name", "")).strip(),
        description=str(data.get("description", "")).strip(),
        body=body.rstrip() + "\n" if body.strip() else "",
        license=str(data.get("license", "")).strip(),
        compatibility=str(data.get("compatibility", "")).strip(),
        metadata={str(key): value for key, value in metadata.items()},
        allowed_tools=tools.strip(),
        allowed_tools_raw=raw_blocks.get("allowed-tools", ""),
        extra={key: raw for key, raw in raw_blocks.items() if key not in KNOWN_FIELDS},
    )


def check_name(name: str) -> None:
    if not name:
        raise SkillError("skillErr_missingField", field="name")
    if len(name) > MAX_NAME_CHARS or not NAME_RE.match(name):
        raise SkillError("skillErr_badName", name=name[:80], max=MAX_NAME_CHARS)


def validate(doc: SkillDoc, *, folder: str | None = None) -> None:
    """规范的规矩,加上 Mosael 的显示名。"""
    check_name(doc.name)
    if folder is not None and folder != doc.name:
        raise SkillError("skillErr_folderMismatch", folder=folder[:80], name=doc.name)
    if not doc.description:
        raise SkillError("skillErr_missingField", field="description")
    if len(doc.description) > MAX_DESCRIPTION_CHARS:
        raise SkillError("skillErr_tooLong", field="description", max=MAX_DESCRIPTION_CHARS)
    if len(doc.compatibility) > MAX_COMPATIBILITY_CHARS:
        raise SkillError("skillErr_tooLong", field="compatibility", max=MAX_COMPATIBILITY_CHARS)
    if len(doc.license) > MAX_LICENSE_CHARS:
        raise SkillError("skillErr_tooLong", field="license", max=MAX_LICENSE_CHARS)
    if len(doc.title) > MAX_TITLE_CHARS or "\n" in doc.title:
        raise SkillError("skillErr_tooLong", field=f"metadata.{TITLE_KEY}", max=MAX_TITLE_CHARS)
    if len(render_skill_md(doc).encode("utf-8")) > MAX_SKILL_MD_BYTES:
        raise SkillError("skillErr_skillMdTooLarge", limit=MAX_SKILL_MD_BYTES // 1024)


def render_skill_md(doc: SkillDoc) -> str:
    """SkillDoc → SKILL.md。只写规范里的字段;不认识的那几行原样放回。字符串一律带双引号,读回来是同一个值。"""
    lines = ["---", f"name: {doc.name}", f"description: {_quote(doc.description)}"]
    if doc.license:
        lines.append(f"license: {_quote(doc.license)}")
    if doc.compatibility:
        lines.append(f"compatibility: {_quote(doc.compatibility)}")
    if doc.metadata:
        lines.append("metadata:")
        lines += [f"  {_quote_key(key)}: {_quote(value)}" for key, value in doc.metadata.items()]
    if doc.allowed_tools_raw:
        lines.append(doc.allowed_tools_raw.rstrip("\n"))
    elif doc.allowed_tools:
        lines.append(f"allowed-tools: {_quote(doc.allowed_tools)}")
    lines += [raw.rstrip("\n") for raw in doc.extra.values()]
    lines.append("---")
    body = doc.body.strip("\n")
    return "\n".join(lines) + "\n" + (f"\n{body}\n" if body else "")


def _quote(value: str) -> str:
    """YAML 双引号标量。JSON 的转义是它的子集;另把 YAML 不许裸写的字符也转义掉。"""
    out = ['"']
    for char in value:
        code = ord(char)
        if char == "\\":
            out.append("\\\\")
        elif char == '"':
            out.append('\\"')
        elif char == "\n":
            out.append("\\n")
        elif char == "\t":
            out.append("\\t")
        elif code < 0x20 or 0x7F <= code <= 0x9F or code in (0x2028, 0x2029, 0xFEFF) or 0xD800 <= code <= 0xDFFF:
            out.append(f"\\u{code:04x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _quote_key(key: str) -> str:
    return key if re.match(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$", key) else _quote(key)


# ---------------------------------------------------------------- YAML 子集


class _Lines:
    def __init__(self, text: str) -> None:
        self.lines = text.split("\n")
        #: 原文。`- key: value` 列表项读的时候会改写 `lines` 里那一行;不认识的键要原样写回,取的是这一份。
        self.original = list(self.lines)

    def __len__(self) -> int:
        return len(self.lines)

    def indent(self, index: int) -> int:
        line = self.lines[index]
        if "\t" in line[: len(line) - len(line.lstrip(" \t"))]:
            raise SkillError("skillErr_yamlTab", line=index + 2)
        return len(line) - len(line.lstrip(" "))

    def blank(self, index: int) -> bool:
        stripped = self.lines[index].strip()
        return not stripped or stripped.startswith("#")

    def next_content(self, index: int) -> int:
        while index < len(self.lines) and self.blank(index):
            index += 1
        return index


def load_frontmatter(text: str) -> tuple[dict[str, Any], dict[str, str]]:
    """头 → (值, 每个顶层键那几行原文)。行号按文件算(第 1 行是 `---`)。"""
    lines = _Lines(text)
    start = lines.next_content(0)
    if start >= len(lines):
        return {}, {}
    if lines.indent(start) != 0:
        raise SkillError("skillErr_yamlIndent", line=start + 2)
    data, end = _mapping(lines, start, 0, raw_blocks := {})
    end = lines.next_content(end)
    if end < len(lines):
        raise SkillError("skillErr_yamlSyntax", line=end + 2)
    if not isinstance(data, dict):
        raise SkillError("skillErr_yamlSyntax", line=start + 2)
    return data, raw_blocks


def _mapping(lines: _Lines, index: int, indent: int, raw_blocks: dict[str, str] | None = None) -> tuple[dict[str, Any], int]:
    out: dict[str, Any] = {}
    while True:
        index = lines.next_content(index)
        if index >= len(lines) or lines.indent(index) < indent:
            return out, index
        if lines.indent(index) > indent:
            raise SkillError("skillErr_yamlIndent", line=index + 2)
        content = lines.lines[index].strip()
        if content.startswith("- ") or content == "-":
            return out, index
        key, rest = _split_key(content, index)
        if key in out:
            raise SkillError("skillErr_yamlDuplicateKey", field=key[:80], line=index + 2)
        start = index
        out[key], index = _value(lines, index, indent, rest)
        if raw_blocks is not None:
            # 这个键的原文:到下一个键之前、去掉尾部的空行和注释。
            end = index
            while end > start + 1 and lines.blank(end - 1):
                end -= 1
            raw_blocks[key] = "\n".join(lines.original[start:end])


def _split_key(content: str, index: int) -> tuple[str, str]:
    if content[0] in "\"'":
        key, rest = _quoted_inline(content, index)
        rest = rest.lstrip()
        if not rest.startswith(":"):
            raise SkillError("skillErr_yamlSyntax", line=index + 2)
        return key, rest[1:].strip()
    if content[0] in "?&*!|>%@`{[":
        raise SkillError("skillErr_yamlUnsupported", line=index + 2)
    match = re.match(r"^([^:#]+?)\s*:(?:\s+(.*))?$", content)
    if not match:
        raise SkillError("skillErr_yamlSyntax", line=index + 2)
    return match.group(1).strip(), (match.group(2) or "").strip()


def _value(lines: _Lines, index: int, indent: int, rest: str, *, in_sequence: bool = False) -> tuple[Any, int]:
    """冒号(或 `- `)后面那一段,连同它可能跨的后续行。返回 (值, 下一行)。

    `in_sequence`:这是一个列表项的值。映射的值可以是和键同一缩进的列表(`key:` 下一行 `- a`),列表项不行 ——
    同一缩进的 `- ` 是下一项。"""
    rest = _strip_comment(rest)
    if rest == "":
        following = lines.next_content(index + 1)
        if following < len(lines):
            deeper = lines.indent(following)
            item = lines.lines[following].strip()
            if deeper > indent:
                if item.startswith("- ") or item == "-":
                    return _sequence(lines, following, deeper)
                return _mapping(lines, following, deeper)
            if deeper == indent and not in_sequence and (item.startswith("- ") or item == "-"):
                return _sequence(lines, following, deeper)
        return "", index + 1
    head = rest[0]
    if head in "&*!":
        raise SkillError("skillErr_yamlUnsupported", line=index + 2)
    if head in "|>":
        return _block_scalar(lines, index, indent, rest)
    if head in "\"'":
        return _quoted(lines, index, rest)
    if head in "[{":
        return _flow(lines, index, rest)
    if head in "%@`":
        raise SkillError("skillErr_yamlUnsupported", line=index + 2)
    return _plain(lines, index, indent, rest)


def _sequence(lines: _Lines, index: int, indent: int) -> tuple[list[Any], int]:
    out: list[Any] = []
    while True:
        index = lines.next_content(index)
        if index >= len(lines) or lines.indent(index) < indent:
            return out, index
        if lines.indent(index) > indent:
            raise SkillError("skillErr_yamlIndent", line=index + 2)
        content = lines.lines[index].strip()
        if not (content.startswith("- ") or content == "-"):
            return out, index
        rest = content[1:].lstrip()
        if rest and not rest.startswith(("\"", "'", "[", "{")) and re.match(r"^[^:#]+?:(\s|$)", rest):
            # `- key: value`:一个映射作为列表项。把这一行当成从 `- ` 之后那一列开始的映射。
            column = lines.indent(index) + (len(content) - len(rest))
            lines.lines[index] = " " * column + rest
            item, index = _mapping(lines, index, column)
            out.append(item)
            continue
        item, index = _value(lines, index, indent, rest, in_sequence=True)
        out.append(item)


_NULLS = frozenset({"~", "null", "Null", "NULL"})


def _plain(lines: _Lines, index: int, indent: int, rest: str) -> tuple[str, int]:
    """普通标量,可以跨行:后面缩进更深、又不是新键的行接在后面(换行折成空格,空行是换行)。"""
    parts = [rest]
    index += 1
    pending_breaks = 0
    while index < len(lines):
        line = lines.lines[index]
        if not line.strip():
            pending_breaks += 1
            index += 1
            continue
        if lines.indent(index) <= indent or line.strip().startswith("#"):
            break
        text = _strip_comment(line.strip())
        if re.match(r"^[^:#\s][^:#]*:(\s|$)", text):
            # 缩进更深的「键: 值」:多半是缩进写错了(PyYAML 在这里也报错),别把它悄悄并进上一个值。
            raise SkillError("skillErr_yamlIndent", line=index + 2)
        parts.append(("\n" * pending_breaks) if pending_breaks else " ")
        parts.append(text)
        pending_breaks = 0
        index += 1
    value = "".join(parts).strip()
    return ("" if value in _NULLS else value), index


def _strip_comment(text: str) -> str:
    """普通标量里 ` #` 之后是注释;引号里的不算(引号标量由各自的读法处理)。"""
    if text.startswith(("\"", "'")):
        return text.strip()
    match = re.search(r"(^|\s)#", text)
    return (text[: match.start()] if match else text).strip()


def _block_scalar(lines: _Lines, index: int, indent: int, header: str) -> tuple[str, int]:
    match = re.match(r"^([|>])([+-]?)([1-9]?)([+-]?)\s*(#.*)?$", header)
    if not match:
        raise SkillError("skillErr_yamlSyntax", line=index + 2)
    style, chomp = match.group(1), match.group(2) or match.group(4)
    explicit = int(match.group(3)) if match.group(3) else 0
    index += 1
    body: list[str] = []
    content_indent = indent + explicit if explicit else 0
    while index < len(lines):
        line = lines.lines[index]
        if not line.strip():
            body.append("")
            index += 1
            continue
        current = lines.indent(index)
        if not content_indent:
            if current <= indent:
                break
            content_indent = current
        if current < content_indent:
            break
        body.append(line[content_indent:])
        index += 1
    # 尾部空行:按 chomping 处理;它们不属于下一个键。
    trailing = 0
    while body and body[-1] == "":
        body.pop()
        trailing += 1
    if style == "|":
        text = "\n".join(body)
    else:
        text = _fold(body)
    if not body:
        text = ""
    elif chomp == "-":
        pass
    elif chomp == "+":
        text += "\n" * (trailing + 1)
    else:
        text += "\n"
    return text, index


def _fold(body: list[str]) -> str:
    """`>` 块:同缩进的相邻行折成一个空格;空行是换行;缩进更深的行(以空格开头)保留换行。"""
    out = ""
    previous_more = False
    for position, line in enumerate(body):
        more = line.startswith((" ", "\t"))
        if position == 0:
            out = line
        elif line == "":
            out += "\n"
        elif out.endswith("\n") or more or previous_more:
            out += ("" if out.endswith("\n") else "\n") + line
        else:
            out += " " + line
        previous_more = more and line != ""
    return out


def _quoted(lines: _Lines, index: int, rest: str) -> tuple[str, int]:
    """引号标量,可以跨行。读到收尾的引号为止,之后只许有空白和注释。"""
    text = rest
    start = index
    while True:
        try:
            value, after = _quoted_inline(text, start)
        except _Unterminated:
            index += 1
            if index >= len(lines):
                raise SkillError("skillErr_yamlUnterminated", line=start + 2) from None
            text += "\n" + lines.lines[index]
            continue
        if _strip_comment(after.strip()) and not after.strip().startswith("#"):
            raise SkillError("skillErr_yamlSyntax", line=index + 2)
        return value, index + 1


class _Unterminated(Exception):
    pass


_ESCAPES = {
    "0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n", "v": "\v", "f": "\f", "r": "\r",
    "e": "\x1b", " ": " ", '"': '"', "/": "/", "\\": "\\", "N": "\x85", "_": "\xa0", "L": " ", "P": " ",
}


def _quoted_inline(text: str, index: int) -> tuple[str, str]:
    """`text` 以引号开头:读出那个标量,返回 (值, 收尾引号之后的部分)。没收尾就抛 _Unterminated。"""
    quote = text[0]
    out: list[str] = []
    position = 1
    while position < len(text):
        char = text[position]
        if quote == "'" and char == "'":
            if text[position + 1: position + 2] == "'":
                out.append("'")
                position += 2
                continue
            return _fold_quoted("".join(out)), text[position + 1:]
        if quote == '"' and char == '"':
            return _fold_quoted("".join(out)), text[position + 1:]
        if quote == '"' and char == "\\":
            escape = text[position + 1: position + 2]
            if escape == "\n":
                # 行尾的反斜杠:续行,不留空格,下一行开头的空白也不算。
                position += 2
                while position < len(text) and text[position] in " \t":
                    position += 1
                out.append("\x00JOIN\x00")
                continue
            if escape in _ESCAPES:
                out.append(f"\x00ESC{ord(_ESCAPES[escape])}\x00")
                position += 2
                continue
            width = {"x": 2, "u": 4, "U": 8}.get(escape)
            if width:
                digits = text[position + 2: position + 2 + width]
                if len(digits) != width or not re.fullmatch(r"[0-9A-Fa-f]+", digits):
                    raise SkillError("skillErr_yamlSyntax", line=index + 2)
                out.append(f"\x00ESC{int(digits, 16)}\x00")
                position += 2 + width
                continue
            raise SkillError("skillErr_yamlSyntax", line=index + 2)
        out.append(char)
        position += 1
    raise _Unterminated


def _fold_quoted(raw: str) -> str:
    """引号标量跨行时的折叠:换行变空格,空行变换行,续行开头的空白去掉。转义出来的字符此时还是
    `\x00ESC<码位>\x00` 记号(里面没有换行和空白),折叠碰不到它们,最后才换回字符。"""
    if "\n" in raw:
        lines = raw.split("\n")
        folded = lines[0].rstrip(" \t")
        breaks = 0
        for line in lines[1:]:
            stripped = line.strip(" \t")
            if not stripped:
                breaks += 1
                continue
            folded += ("\n" * breaks) if breaks else (" " if not folded.endswith("\x00JOIN\x00") else "")
            folded += stripped
            breaks = 0
        folded += "\n" * breaks
        raw = folded
    raw = raw.replace("\x00JOIN\x00", "")
    return re.sub(r"\x00ESC(\d+)\x00", lambda match: chr(int(match.group(1))), raw)


def _flow(lines: _Lines, index: int, rest: str) -> tuple[Any, int]:
    """`[a, "b"]` / `{k: v}`,可以跨行:拼到括号配平为止。"""
    text = rest
    start = index
    while not _balanced(text):
        index += 1
        if index >= len(lines):
            raise SkillError("skillErr_yamlUnterminated", line=start + 2)
        text += " " + lines.lines[index].strip()
    parser = _FlowParser(text, start)
    value = parser.value()
    parser.skip_space()
    tail = text[parser.position:].strip()
    if tail and not tail.startswith("#"):
        raise SkillError("skillErr_yamlSyntax", line=start + 2)
    return value, index + 1


def _balanced(text: str) -> bool:
    depth = 0
    quote = ""
    position = 0
    while position < len(text):
        char = text[position]
        if quote:
            if char == "\\" and quote == '"':
                position += 2
                continue
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
            if depth == 0:
                return True
        elif char == "#" and (position == 0 or text[position - 1] in " \t"):
            return depth == 0
        position += 1
    return depth == 0 and not quote


class _FlowParser:
    def __init__(self, text: str, line: int) -> None:
        self.text = text
        self.position = 0
        self.line = line

    def fail(self) -> SkillError:
        return SkillError("skillErr_yamlSyntax", line=self.line + 2)

    def skip_space(self) -> None:
        while self.position < len(self.text) and self.text[self.position] in " \t\n":
            self.position += 1

    def value(self) -> Any:
        self.skip_space()
        if self.position >= len(self.text):
            raise self.fail()
        char = self.text[self.position]
        if char == "[":
            return self.sequence()
        if char == "{":
            return self.mapping()
        if char in "\"'":
            try:
                value, after = _quoted_inline(self.text[self.position:], self.line)
            except _Unterminated:
                raise self.fail() from None
            self.position = len(self.text) - len(after)
            return value
        if char in "&*!":
            raise SkillError("skillErr_yamlUnsupported", line=self.line + 2)
        match = re.compile(r"[^,\[\]{}]*").match(self.text, self.position)
        raw = match.group(0) if match else ""
        # `{k: v}` 里的普通标量到冒号为止(冒号后面跟空白才算)。
        colon = re.search(r":(\s|$)", raw)
        if colon:
            raw = raw[: colon.start()]
        self.position += len(raw)
        value = raw.strip()
        return "" if value in _NULLS else value

    def sequence(self) -> list[Any]:
        self.position += 1
        out: list[Any] = []
        while True:
            self.skip_space()
            if self.text[self.position: self.position + 1] == "]":
                self.position += 1
                return out
            out.append(self.value())
            self.skip_space()
            char = self.text[self.position: self.position + 1]
            if char == ",":
                self.position += 1
            elif char != "]":
                raise self.fail()

    def mapping(self) -> dict[str, Any]:
        self.position += 1
        out: dict[str, Any] = {}
        while True:
            self.skip_space()
            if self.text[self.position: self.position + 1] == "}":
                self.position += 1
                return out
            key = self.value()
            if not isinstance(key, str):
                raise self.fail()
            self.skip_space()
            if self.text[self.position: self.position + 1] != ":":
                raise self.fail()
            self.position += 1
            out[key] = self.value()
            self.skip_space()
            char = self.text[self.position: self.position + 1]
            if char == ",":
                self.position += 1
            elif char != "}":
                raise self.fail()


# ---------------------------------------------------------------- 文件与路径


def check_path(path: str) -> str:
    """技能里一个文件的相对路径 → 规整过的 posix 写法。越界、绝对路径、反斜杠、太深一律拒。"""
    raw = str(path or "")
    if not raw or "\\" in raw or "\x00" in raw or raw.startswith("/") or _DRIVE.match(raw):
        raise SkillError("skillErr_badPath", path=raw[:120])
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts) or len(parts) > MAX_PATH_DEPTH:
        raise SkillError("skillErr_badPath", path=raw[:120])
    if any(len(part) > 255 for part in parts):
        raise SkillError("skillErr_badPath", path=raw[:120])
    return "/".join(parts)


def is_junk(path: str) -> bool:
    parts = path.split("/")
    return parts[-1] in JUNK_NAMES or any(part in JUNK_DIRS for part in parts[:-1]) or parts[-1].startswith("._")


def check_files(files: dict[str, int]) -> None:
    """一个技能的文件(相对路径 → 字节数):有 SKILL.md、个数和大小在上限里。"""
    if SKILL_FILENAME not in files:
        raise SkillError("skillErr_noSkillMd")
    if len(files) > MAX_SKILL_FILES:
        raise SkillError("skillErr_tooManyFiles", limit=MAX_SKILL_FILES)
    for path, size in files.items():
        if size > MAX_FILE_BYTES:
            raise SkillError("skillErr_fileTooLarge", path=path[:120], limit=MAX_FILE_BYTES // (1024 * 1024))
    if sum(files.values()) > MAX_SKILL_BYTES:
        raise SkillError("skillErr_skillTooLarge", limit=MAX_SKILL_BYTES // (1024 * 1024))


def is_text(data: bytes) -> bool:
    """按内容判:能按 UTF-8 解、没有 NUL 的算文本。后缀会骗人(`.md` 里塞二进制,`.py` 是文本)。"""
    if b"\x00" in data[:8192]:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


@dataclass(frozen=True)
class SkillBundle:
    """读出来、还没落地的一个技能:SKILL.md 读好了,其余文件在内存里。"""

    doc: SkillDoc
    #: 相对技能根的路径 → 内容。含 SKILL.md。
    files: dict[str, bytes]
    #: 它在压缩包 / 文件夹里原来叫什么(那一层目录名;就在最外层时是空串)。
    folder: str = ""


def bundles_from_files(files: dict[str, bytes]) -> list[SkillBundle]:
    """一堆文件(相对路径 → 内容,来自一个 `.zip` 或用户选的文件夹)→ 里面的技能。

    认法:每一份 `SKILL.md` 所在的那一层是一个技能的根;嵌在另一个技能里面的 SKILL.md 不另算(那是它的参考文件)。
    路径先过 `check_path`,系统塞进来的垃圾(`__MACOSX`、`.DS_Store`)丢掉。
    """
    clean: dict[str, bytes] = {}
    for raw_path, data in files.items():
        path = check_path(raw_path)
        if not is_junk(path):
            clean[path] = data
    roots = sorted(
        {str(PurePosixPath(path).parent) if "/" in path else "" for path in clean if PurePosixPath(path).name == SKILL_FILENAME},
        key=lambda root: (root.count("/"), root),
    )
    roots = [root for root in roots if not any(other != root and _inside(root, other) for other in roots)]
    if not roots:
        raise SkillError("skillErr_noSkillMd")
    if len(roots) > MAX_SKILLS_PER_IMPORT:
        raise SkillError("skillErr_tooManySkills", limit=MAX_SKILLS_PER_IMPORT)
    bundles = []
    for root in roots:
        prefix = f"{root}/" if root else ""
        own = {path[len(prefix):]: data for path, data in clean.items() if path.startswith(prefix)}
        check_files({path: len(data) for path, data in own.items()})
        try:
            text = own[SKILL_FILENAME].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SkillError("skillErr_notUtf8", path=f"{prefix}{SKILL_FILENAME}") from exc
        bundles.append(SkillBundle(doc=parse_skill_md(text), files=own, folder=PurePosixPath(root).name if root else ""))
    names = [bundle.doc.name for bundle in bundles]
    duplicated = sorted({name for name in names if names.count(name) > 1})
    if duplicated:
        raise SkillError("skillErr_duplicateName", name=duplicated[0])
    return bundles


def _inside(path: str, root: str) -> bool:
    return root == "" or path.startswith(f"{root}/")


def read_skill_archive(data: bytes) -> list[SkillBundle]:
    """一个 `.zip` → 里面的技能。成员先查(符号链接、越界路径、声明的解压后大小),再读。"""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError) as exc:
        raise SkillError("skillErr_notZip") from exc
    with archive:
        members = [info for info in archive.infolist() if not info.is_dir()]
        if len(members) > MAX_SKILL_FILES * MAX_SKILLS_PER_IMPORT:
            raise SkillError("skillErr_tooManyFiles", limit=MAX_SKILL_FILES)
        total = 0
        for info in members:
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise SkillError("skillErr_symlink", path=info.filename[:120])
            check_path(info.filename)
            total += info.file_size
            if total > MAX_ARCHIVE_UNPACKED_BYTES:
                raise SkillError("skillErr_archiveTooLarge", limit=MAX_ARCHIVE_UNPACKED_BYTES // (1024 * 1024))
        try:
            files = {info.filename: archive.read(info) for info in members}
        except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
            raise SkillError("skillErr_notZip") from exc
    return bundles_from_files(files)


def write_skill_archive(skills: list[tuple[str, dict[str, bytes]]]) -> bytes:
    """[(技能名, {相对路径: 内容})] → 一个 `.zip`,每个技能一层同名文件夹(别家导入认的就是这个形状)。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, files in skills:
            check_name(name)
            for path in sorted(files):
                archive.writestr(f"{name}/{check_path(path)}", files[path])
    return buffer.getvalue()


def plugin_skill_files(files: dict[str, bytes], *, root: str = "skills") -> list[SkillBundle]:
    """插件包里的 `skills/<名字>/…` → 技能。插件包里的要求更严:每个子目录都得是一个技能、目录名就是 `name`
    (宿主照目录找它,改不了名)。没有 `skills/` 目录就是空列表。"""
    prefix = f"{root}/"
    inside = {path[len(prefix):]: data for path, data in files.items() if path.startswith(prefix)}
    by_folder: dict[str, dict[str, bytes]] = {}
    for path, data in inside.items():
        clean = check_path(path)
        if is_junk(clean):
            continue
        if "/" not in clean:
            raise SkillError("skillErr_pluginStrayFile", path=f"{prefix}{clean}"[:120])
        folder, rest = clean.split("/", 1)
        by_folder.setdefault(folder, {})[rest] = data
    bundles = []
    for folder in sorted(by_folder):
        own = by_folder[folder]
        check_files({path: len(data) for path, data in own.items()})
        try:
            text = own[SKILL_FILENAME].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SkillError("skillErr_notUtf8", path=f"{prefix}{folder}/{SKILL_FILENAME}") from exc
        bundles.append(SkillBundle(doc=parse_skill_md(text, folder=folder), files=own, folder=folder))
    return bundles


__all__ = [
    "KNOWN_FIELDS",
    "MAX_DESCRIPTION_CHARS",
    "MAX_FILE_BYTES",
    "MAX_NAME_CHARS",
    "MAX_SKILL_BYTES",
    "MAX_SKILL_FILES",
    "MAX_SKILL_MD_BYTES",
    "MAX_TITLE_CHARS",
    "NAME_RE",
    "SKILL_FILENAME",
    "SkillBundle",
    "SkillDoc",
    "SkillError",
    "TITLE_KEY",
    "bundles_from_files",
    "check_files",
    "check_name",
    "check_path",
    "is_junk",
    "is_text",
    "load_frontmatter",
    "parse_skill_md",
    "plugin_skill_files",
    "read_skill_archive",
    "render_skill_md",
    "split_frontmatter",
    "validate",
    "write_skill_archive",
]
