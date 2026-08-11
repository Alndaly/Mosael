"""一句「另一侧还有一份,必须跟我一致」,必须**点名它归哪个契约**。

`contracts/` 这套机制是对的,但一件事要不要进契约,此前完全取决于**有没有人正好读到那句
注释**。而注意力不是机制:

- 第一遍复查时我 grep 的是「两处回答」「两份实现」,于是漏掉了写成 `Mirrors the frontend`、
  「锁步一致」、「必须与 sidecar 一致」的那三处 —— **换个说法就漏一个**;
- 其中一处(`_read_transform` ↔ `readTransform`)当时语义已经不同了:后端把 scale 钳到
  [0.01,10]、接受数字字符串,前端两样都不做。没发作只是因为唯一的写入路径在写时已经钳过,
  属于"上游恰好挡住",不是两侧一致。

所以这条棘轮盯的不是某一处重复,而是**"作者自己已经知道有两份"这件事**:凡是写下这类话的
地方,要么在同一段注释里点名 `contracts/xxx.json`,要么进下面的豁免名单并写清为什么不需要。

**它挡不住什么**(说清楚,免得当成万能):这是一条**措辞扫描**,有人用一个全新说法写下同样的
意思时它不会响。它的价值不在穷尽,而在于把"得有人记得"降级成"得有人换个词" —— 而每一次
换词被发现时,把新说法加进 `CLAIMS` 就又收紧一格。七处历史证据里,作者**每一次都自己写下了
这句话**,只是没人负责去查。
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]

#: 扫这些目录里的源码(node_modules / 生成物除外)。
ROOTS = [
    REPO / "backend" / "app",
    REPO / "frontend" / "src",
    REPO / "agent-sidecar" / "src",
    REPO / "electron",
]

SUFFIXES = {".py", ".ts", ".tsx", ".cjs", ".mjs"}

#: 打包产物里当然会带上源码的注释 —— 扫它等于把同一处数两遍,而且改不动。
GENERATED = (".bundle.cjs", ".d.ts")

#: 「另一侧还有一份」的说法。全部来自仓库里实际出现过的措辞,不是我想象的。
CLAIMS = [
    "Mirrors the frontend",
    "镜像预览",
    "镜像前端",
    "锁步一致",
    "必须一致",
    "必须与",
    "保持同一套",
    "逐条对齐",
    "改一处就要改另一处",
    "两边拼的是同一个",
]

#: 认定"已经点名契约"的写法。
CONTRACT_HINT = re.compile(r"contracts/[\w.-]+\.json")

#: 豁免:写下这类话但**确实不需要**契约的地方,以及为什么。
#: 名单短而有名有姓 —— 一张越写越长的名单等于没有名单。
ALLOWED: dict[str, str] = {}

#: 契约自己的测试与语料里当然会提到这些词,不必再点名。
SKIP_NAME_PARTS = ("parity", "contract")


def _claims() -> list[tuple[pathlib.Path, int, str, str]]:
    found: list[tuple[pathlib.Path, int, str, str]] = []
    for root in ROOTS:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.suffix not in SUFFIXES or "node_modules" in path.parts:
                continue
            if path.name.endswith(GENERATED) or "dist" in path.parts or "generated" in path.parts:
                continue
            if any(part in path.name.lower() for part in SKIP_NAME_PARTS):
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
            for index, line in enumerate(lines):
                for claim in CLAIMS:
                    if claim in line:
                        # 同一段注释:上下各看 12 行,够覆盖一个 docstring / 注释块。
                        block = "\n".join(lines[max(0, index - 12) : index + 13])
                        found.append((path, index + 1, claim, block))
    return found


def test_every_cross_runtime_claim_names_its_contract() -> None:
    naked: list[str] = []
    for path, line, claim, block in _claims():
        rel = str(path.relative_to(REPO))
        if rel in ALLOWED or CONTRACT_HINT.search(block):
            continue
        naked.append(f"{rel}:{line}  「{claim}」")

    assert naked == [], (
        "这些地方写着「另一侧还有一份、必须跟我一致」,却没说归哪个契约 —— "
        "于是它是否真的一致,全靠有人正好读到这句话:\n  " + "\n  ".join(naked)
    )


def test_the_allowlist_does_not_quietly_grow() -> None:
    assert len(ALLOWED) <= 3, f"豁免名单在变长:{sorted(ALLOWED)}"


def test_the_scan_actually_finds_things() -> None:
    """措辞表和目录写错了会让这条测试永远绿 —— 一条永远绿的棘轮比没有更糟。"""
    assert len(_claims()) >= 5, "一处都没扫到,措辞表或扫描目录八成写错了"
