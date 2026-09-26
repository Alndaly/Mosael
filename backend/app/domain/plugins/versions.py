"""插件版本号的先后。

市场里「有新版」此前是字符串**不相等**:索引写 0.2.0、装着 0.1.0 就提示更新 —— 而下载地址给的
若仍是 0.1.0,点「更新」装回同一版,提示永远不消失。「不相等」回答不了「谁更新」:装着的比索引
新(从链接装了预发版)也会被说成「有新版」,点下去是降级。

所以按语义化版本(semver 2.0)比先后:`MAJOR.MINOR.PATCH[-预发标识][+构建信息]`,允许前缀 `v`、
允许少写几段(`1.2` = `1.2.0`)。数字段按数比(0.10.0 > 0.9.0);带预发标识的排在同号正式版之前
(1.0.0-beta < 1.0.0),预发标识逐段比:纯数字按数、其余按字面、数字段排在字母段之前、段多的在后;
构建信息不参与先后。

**比不出来的不硬比。** 插件作者写什么全凭自觉(`1.2.3.4`、`latest`),任何一边解析不了时
`compare` 返回 None,由调用方决定怎么办 —— 市场那一处退回「不相等」:宁可多提示一次,也不把
一个真的新版说成旧版。
"""

from __future__ import annotations

import re

_SEMVER = re.compile(
    r"^v?(?P<core>\d+(?:\.\d+){0,2})"
    r"(?:-(?P<pre>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)

#: 预发标识里的一段:数字段排在字母段之前(semver 2.0 第 11 条)。
_Ident = tuple[int, int, str]
_Parsed = tuple[tuple[int, int, int], tuple[_Ident, ...] | None]


def _parse(version: str) -> _Parsed | None:
    matched = _SEMVER.match(str(version or "").strip())
    if not matched:
        return None
    numbers = [int(part) for part in matched.group("core").split(".")]
    core = (numbers + [0, 0])[:3]
    pre = matched.group("pre")
    idents = (
        tuple((0, int(part), "") if part.isdigit() else (1, 0, part) for part in pre.split("."))
        if pre
        else None
    )
    return (core[0], core[1], core[2]), idents


def compare(left: str, right: str) -> int | None:
    """left 比 right 新返回 1、旧返回 -1、同一版返回 0;任何一边不是语义化版本返回 None。"""
    a, b = _parse(left), _parse(right)
    if a is None or b is None:
        return None
    if a[0] != b[0]:
        return 1 if a[0] > b[0] else -1
    pre_a, pre_b = a[1], b[1]
    if pre_a == pre_b:
        return 0
    # 同号时正式版比任何预发版新。
    if pre_a is None:
        return 1
    if pre_b is None:
        return -1
    # 元组逐段比正好是 semver 的规则:段相同时,段多的那个在后。
    return 1 if pre_a > pre_b else -1


def is_newer(candidate: str, installed: str) -> bool:
    """candidate 是不是比 installed 新。比不出先后时退回「不相等」(见模块说明)。"""
    order = compare(candidate, installed)
    if order is None:
        return str(candidate or "").strip() != str(installed or "").strip()
    return order > 0


__all__ = ["compare", "is_newer"]
