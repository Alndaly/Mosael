#!/usr/bin/env python3
"""仓库里被跟踪的文本文件不许留着合并冲突的标记。挂在根目录的 `pnpm lint` 里(CI「快的检查」那一组跑的就是它)。

**为什么要有这一道。** e36342248 合并时把一行 diff3 的 `||||||| parent of 10d262dcf …` 留进了 CHANGELOG.md:
lint 只看代码、测试不读 CHANGELOG,一路绿着进了 main。冲突标记留在代码里,多半会让那个文件语法错、当场被别的检查拦下;
留在文档、数据、配置里就没人发现 —— 读的人看到一行乱码,官网把它渲染出来。

查的是:以 `<<<<<<<` / `>>>>>>>` / `|||||||`(七个,后面是空格或行尾)开头的行,和单独一行的七个 `=`。
lock 文件、二进制不查。Markdown(.md / .mdx)里单独的 `=======` 要是紧跟在一行段落文字后面,那是 setext 标题的下划线,
放过;跟在列表项、引用、表格行、空行后面,或在代码块里,照样算(此时它不是标题)。

用法:
    python3 scripts/check-conflict-markers.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: 冲突标记:git 写的都是正好七个,后面跟一个空格和说明,或者什么都不跟。
_MARKER = re.compile(r"^(?:<{7}|>{7}|\|{7})(?: |$)")
_SEPARATOR = re.compile(r"^={7}$")
#: lock 文件:生成的,里面的内容不归人写,也不该在这里报。
_LOCK_FILES = re.compile(r"(?:^|/)(?:[^/]+\.lock|pnpm-lock\.yaml|package-lock\.json)$")
_MARKDOWN = (".md", ".mdx")
#: 段落文字以外的行:接在它们后面的 `=======` 不是 setext 标题。
_NOT_A_PARAGRAPH = re.compile(r"^\s*(?:$|[-*+] |\d+[.)] |>|\||#|```|~~~)")


def offending_lines(name: str, text: str) -> list[int]:
    """这个文件里哪几行(从 1 数)是冲突标记。"""
    found: list[int] = []
    in_fence = False
    previous = ""
    markdown = name.endswith(_MARKDOWN)
    for number, line in enumerate(text.splitlines(), start=1):
        if markdown and re.match(r"^\s*(?:```|~~~)", line):
            in_fence = not in_fence
        if _MARKER.match(line):
            found.append(number)
        elif _SEPARATOR.match(line):
            setext = markdown and not in_fence and not _NOT_A_PARAGRAPH.match(previous)
            if not setext:
                found.append(number)
        previous = line
    return found


#: 检查器自己的数法,每次跑之前先过一遍:数错了就是检查器坏了,不能让它报一个「全仓干净」。
_SELF_CHECK: list[tuple[str, str, list[int]]] = [
    ("a.py", "x = 1\n<<<<<<< HEAD\ny = 2\n=======\ny = 3\n>>>>>>> topic\n", [2, 4, 6]),
    ("CHANGELOG.md", "- 一条\n||||||| parent of 10d262dcf (docs: …)\n- 另一条\n", [2]),
    ("CHANGELOG.md", "- 一条\n=======\n- 另一条\n", [2]),
    ("guide.md", "标题\n=======\n\n正文\n", []),
    ("guide.md", "```\n标题\n=======\n```\n", [3]),
    ("notes.txt", "标题\n=======\n", [2]),
    ("guide.md", "标题\n==========\n<<<<<<<< 八个不算\n", []),
]


def _self_check() -> list[str]:
    return [
        f"{name}: 应报 {expected},实际报 {offending_lines(name, text)}"
        for name, text, expected in _SELF_CHECK
        if offending_lines(name, text) != expected
    ]


def _tracked_text_files() -> list[str]:
    #: -I:git 自己判二进制,二进制不出现在结果里;只列可能有问题的文件,再逐个细看
    pattern = r"^(<{7}|>{7}|\|{7})( |$)|^={7}$"
    result = subprocess.run(
        ["git", "grep", "-I", "-l", "-E", pattern, "--", "."],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
    )
    if result.returncode not in (0, 1):  # 1 = 一处都没有
        raise SystemExit(f"git grep 失败:{result.stderr.strip()}")
    return [name for name in result.stdout.splitlines() if not _LOCK_FILES.search(name)]


def main() -> int:
    broken = _self_check()
    if broken:
        print("冲突标记检查器自己数错了:\n" + "\n".join(f"  {line}" for line in broken), file=sys.stderr)
        return 2
    problems: list[str] = []
    for name in _tracked_text_files():
        text = (ROOT / name).read_text(encoding="utf-8", errors="replace")
        problems += [f"  {name}:{number}" for number in offending_lines(name, text)]
    if problems:
        print("这些地方留着合并冲突的标记(合并时没收拾干净):\n" + "\n".join(problems), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
