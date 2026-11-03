#!/usr/bin/env python3
"""拒绝只有一行标题的提交:正文必须写清背景、改动和验证。

由 `.githooks/commit-msg` 调用。规则来自仓库的提交约定:

    type(scope): 一句话说清这次改了什么

    ## 背景
    为什么改;不改会怎样。

    ## 改动
    具体动了哪些文件/行为。

    ## 验证
    真跑过什么;没跑什么、为什么。

只检查**能否提交**,不替人写内容。合并提交和 autosquash 的 `fixup!` / `squash!` 跳过 ——
它们的标题由 git 生成,最终仍会经过一次正常的 commit-msg。
"""

from __future__ import annotations

import sys
from pathlib import Path

REQUIRED_SECTIONS = ("## 背景", "## 改动", "## 验证")


def _message_lines(path: Path) -> list[str]:
    """读消息,去掉 git 自己加的注释行。"""

    return [
        line.rstrip()
        for line in path.read_text(encoding="utf-8").splitlines()
        #: git 的注释行以 `#` 开头,但正文的 Markdown 标题是 `##` —— 别把标题一起删掉。
        if not (line.lstrip().startswith("#") and not line.lstrip().startswith("##"))
    ]


def problems(text: str) -> list[str]:
    """返回所有问题;空列表表示可以提交。"""

    lines = text.splitlines()
    subject = next((line.strip() for line in lines if line.strip()), "")
    if not subject:
        return ["提交信息是空的。"]

    #: git 自己生成的标题:不归本钩子管。`revert:` / `Revert "..."` 也要能过。
    if subject.startswith(("Merge ", "Revert ", "revert:", "fixup!", "squash!", "amend!")):
        return []

    found: list[str] = []
    for section in REQUIRED_SECTIONS:
        indices = [index for index, line in enumerate(lines) if line.strip() == section]
        if not indices:
            found.append(f"缺少「{section}」一节。")
            continue
        start = indices[0] + 1
        end = next(
            (index for index in range(start, len(lines)) if lines[index].strip().startswith("## ")),
            len(lines),
        )
        if not any(line.strip() for line in lines[start:end]):
            found.append(f"「{section}」一节是空的。")

    if found:
        found.append(
            "提交信息格式:\n"
            "  type(scope): 一句话\n"
            "\n"
            "  ## 背景\n"
            "  ...\n"
            "\n"
            "  ## 改动\n"
            "  ...\n"
            "\n"
            "  ## 验证\n"
            "  ..."
        )
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_commit_message.py <commit-msg-file>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    try:
        text = "\n".join(_message_lines(path))
    except OSError as exc:
        print(f"读不到提交信息 {path}: {exc}", file=sys.stderr)
        return 2

    found = problems(text)
    if found:
        print("\n".join(found), file=sys.stderr)
        print("\n提交被拒绝:请把提交信息写完整再提交。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
