"""蒙版的形状运算 —— 和前端跑**同一份**语料(contracts/mask-cases.json),逐字节比。

前端 `frontend/src/lib/maskPixels.parity.test.ts` 读同一个文件,把同一串源图小样、同一组参数
(阈值 / 反选 / 扩张 / 羽化)再算一遍,拿**同一串期望字节**对。这里不看 `masks.py` 里写了哪一句
取整,只看同一份输入两侧算出来的是不是同一串字节 —— 语料里那几条 `.5` 的羽化就是入口。

为什么会漏掉:两侧各写了一句「逐位相等」(后端 `masks.py` 的文件头、前端 `maskPixels.ts` 的
`Math.round`),却各测各的 —— 后端那处的半径是 `int(round(radius))`(半数取偶:`round(0.5) == 0`),
前端是 `Math.round`(半数进位):`feather = 0.5` 时后端一格都不羽化、编辑器羽化了一格;`2.5` 一边
2 格一边 3 格。两侧的单元测试当时都是绿的。经过见语料的 `why`。

`grow` 那一组(扩张 / 收缩)两侧都跑:ADR 0057 起编辑器也有这一步(`maskPixels.growMask`)。

**同一个形状的第二处**:`grow_mask` 那一句此前是 `int(radius)`(向零截断:`0.5 → 0`、`2.5 → 2`、
`-1.7 → 1`),而契约定的规则是**半数进位** —— 用户侧三条入口今天都送不进小数(grow 在 HTTP schema 与
MCP 签名上都是 `int`、素材库对话框那格先 `Math.round`;确认卡那条路能送进来,那处的 `int()` 是同一个
形状的第三处,见语料的 `why`),所以那几条 `grow` 小数用例是**预先钉住**的:哪天有人把 grow 放成
float,规则与用例都已经在那儿。取整表分两张:`rounding`(按 feather 读)与 `grow_rounding`(按 grow 读),
条目同形,两侧都读。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from app.media.masks import feather_mask, grow_mask, invert_mask, mask_from_alpha, mask_from_luminance

CONTRACT = json.loads((Path(__file__).parents[2] / "contracts" / "mask-cases.json").read_text(encoding="utf-8"))

WIDTH, HEIGHT = CONTRACT["frame"]["width"], CONTRACT["frame"]["height"]
SIZE = (WIDTH, HEIGHT)


def test_语料在_且带版本() -> None:
    assert CONTRACT["contract"] == "mask-cases"
    assert CONTRACT["version"] == 1
    assert CONTRACT["cases"] and CONTRACT["sources"]


def _source(case: dict) -> bytes:
    return bytes.fromhex(CONTRACT["sources"][case["source"]]["rgba_hex"])


def _pipeline(case: dict) -> bytes:
    """语料说的那四步,按定死的先后:阈值 → 反选 → 扩张/收缩 → 羽化。"""
    pixels = _source(case)
    mask = (
        mask_from_alpha(pixels, SIZE, case["threshold"])
        if case["source_kind"] == "alpha"
        else mask_from_luminance(pixels, SIZE, case["threshold"])
    )
    if case["invert"]:
        mask = invert_mask(mask)
    if case["grow"]:
        mask = grow_mask(mask, SIZE, case["grow"])
    return feather_mask(mask, SIZE, case["feather"])


def _first_difference(case: dict, got: bytes) -> str:
    want = bytes.fromhex(case["expected_hex"])
    at = next((index for index, (a, b) in enumerate(zip(got, want)) if a != b), None)
    #: 两处半径都写进失败信息里:这一条红的时候,先要知道它是被取整的哪一处拽偏的。
    radii = f"羽化 {case['feather']} 该取整成 {case['expected_reach']} 格"
    if case["grow"]:
        radii += f"、扩张/收缩 {case['grow']} 该取整成 {case['expected_grow_reach']} 格"
    if at is None:
        return f"{case['name']}:长度 {len(got)} ≠ 语料 {len(want)}"
    return (
        f"{case['name']}:第 {at} 格(第 {at // WIDTH} 行第 {at % WIDTH} 列)语料是 {want[at]},这里算出 {got[at]}"
        f" —— {radii}"
    )


@pytest.mark.parametrize("case", CONTRACT["cases"], ids=[case["name"] for case in CONTRACT["cases"]])
def test_逐字节和语料一致(case: dict) -> None:
    got = _pipeline(case)
    assert got.hex() == case["expected_hex"], _first_difference(case, got)


def test_半径按半数进位取整_不是半数取偶() -> None:
    """语料那张取整表两侧各跑一遍:`feather = 0.5` 必须**和 1 格同一张图**(半数取偶会算成 0 格)。"""
    tabled = {one["feather"]: one["reach"] for one in CONTRACT["rounding"]}
    #: 用一条真实的边当被羽化的底(语料的第一条用例)。
    base = _pipeline({**CONTRACT["cases"][0], "feather": 0})
    for radius, reach in tabled.items():
        assert feather_mask(base, SIZE, radius) == feather_mask(base, SIZE, reach), (
            f"半径 {radius} 没有取整成 {reach} 格 —— 语料的意思是 reach = floor(feather + 0.5)"
        )
    #: 这几条是**真的分岔**:半数取偶在它们上面给的是另一格,所以语料能红(见下一条测试)。
    assert feather_mask(base, SIZE, 0.5) != base, "0.5 也该羽化一格(半数取偶是 0 格 = 原样)"
    assert feather_mask(base, SIZE, 2.5) == feather_mask(base, SIZE, 3)
    assert feather_mask(base, SIZE, 2.5) != feather_mask(base, SIZE, 2)


def test_语料里那几条半数用例真的能分出两种取整() -> None:
    """一条永远绿的语料比没有更糟:半数进位与半数取偶给出**不同**格的那几条,必须真有用例。"""
    divergent = [one for one in CONTRACT["rounding"] if round(one["feather"]) != math.floor(one["feather"] + 0.5)]
    assert divergent, "取整表里一条分岔的都没有 —— 这张表钉不住任何东西"
    used = {case["feather"] for case in CONTRACT["cases"]}
    assert {one["feather"] for one in divergent} <= used, "分岔的半径没有对应用例,等于没测"
    #: 每一条用例都写明了它该取整成几格,别让它跟取整表各说各话。
    for case in CONTRACT["cases"]:
        assert case["expected_reach"] == math.floor(case["feather"] + 0.5), case["name"]


def test_两侧都跑四步_扩张和收缩都有用例() -> None:
    """ADR 0057 起编辑器也做扩张 / 收缩:`sides` 两侧是同一张表,扩张、收缩各自至少一条用例。"""
    assert CONTRACT["sides"]["backend/app/media/masks.py"] == ["threshold", "invert", "grow", "feather"]
    assert CONTRACT["sides"]["frontend/src/lib/maskPixels.ts"] == CONTRACT["sides"]["backend/app/media/masks.py"]
    grows = [case["grow"] for case in CONTRACT["cases"] if case["grow"] != 0]
    assert any(value > 0 for value in grows), "没有一条扩张用例"
    assert any(value < 0 for value in grows), "没有一条收缩用例"


def test_扩张半径也按半数进位取整_和羽化同一条规则() -> None:
    """`grow_rounding` 那张表(前端那份读同一张)跑一遍:`grow` 此前是 `int(radius)`,向零截断。

    `reach` 是窗口半宽(取绝对值),方向看 `grow` 的符号 —— 所以负半径拿 `-reach` 去比。
    """
    tabled = {one["grow"]: one["reach"] for one in CONTRACT["grow_rounding"]}
    #: 用一条真实的硬边当被扩张 / 收缩的底(语料的第一条用例):缩一格与缩两格在它上面看得出分别。
    base = _pipeline({**CONTRACT["cases"][0], "grow": 0, "feather": 0})
    for radius, reach in tabled.items():
        signed = -reach if radius < 0 else reach
        assert grow_mask(base, SIZE, radius) == grow_mask(base, SIZE, signed), (
            f"半径 {radius} 没有取整成 {signed} 格 —— 语料的意思是 reach = floor(x + 0.5)"
        )
    #: 这几条是**真的分岔**:截断那条规则(`int(radius)`)在它们上面给的是另一格。
    for radius in (0.5, 1.5, 2.5, -1.7):
        assert grow_mask(base, SIZE, radius) != grow_mask(base, SIZE, float(int(radius))), (
            f"{radius} 在向零截断与半数进位下是同一张图 —— 这条用例钉不住那次分岔"
        )
    assert grow_mask(base, SIZE, 0.5) != base, "0.5 该扩一格(截断是 0 格 = 原样)"
    assert grow_mask(base, SIZE, 0.4) == base, "取整后不足一格,原样返回"


def test_语料里那几条扩张小数用例真的能分出两种取整() -> None:
    """一条永远绿的语料比没有更糟:截断与半数进位给出**不同**格的那几条,必须真有用例。"""
    for one in CONTRACT["grow_rounding"]:
        assert one["reach"] == abs(math.floor(one["grow"] + 0.5)), f"取整表这一行和规则各说各话:{one}"
    divergent = [one for one in CONTRACT["grow_rounding"] if int(one["grow"]) != math.floor(one["grow"] + 0.5)]
    assert divergent, "扩张取整表里一条分岔的都没有 —— 这张表钉不住任何东西"
    used = {case["grow"] for case in CONTRACT["cases"]}
    assert {one["grow"] for one in divergent} <= used, "分岔的半径没有对应用例,等于没测"
    #: 每一条扩张用例都写明了它该取整成几格(带符号:`Math.round(-1.7) == -2`),别让它跟表各说各话。
    for case in CONTRACT["cases"]:
        if case["grow"] == 0:
            continue
        assert case["expected_grow_reach"] == math.floor(case["grow"] + 0.5), case["name"]
