"""同一张大表在一次回答里只搬一次。

ComfyUI 的节点输入里有一类**几百项的下拉**(LoRA、大模型、VAE、文本编码器、放大模型……)。一张图里好几个节点
共用同一张(四个 LoRA 加载器各一格 `lora_name`),每张工作流又各是宿主的一条工具,每条工具的**每一格**都带着
自己那张表 —— 于是同一张表在一次回答里能出现几十次。

一次回答的上限是 1MB(宿主 `runtime.MAX_OUTPUT_BYTES`)。对着真机量,36 个工具的工具清单 1,055,758 字节 ——
维护者那台报 42 个工具,早就撞上了这条线,而里面 58 万字节是**重复的同一批表**:403 份、只有 77 张不同的表
(模型清单 892,325 字节也贴着线)。撞线的后果不是少几张下拉,而是整份清单不收 —— 插件页那一行是「插件输出超过
大小限制 (1MB)」,工具清单保留上一份。

所以把**重复出现**的表挪到回答顶层的 `shared_tables` 里一次,格子上写 `{"x-shared-table": "<id>"}` 指过去。
宿主在收的时候展平回每一格(见 docs/PLUGIN_MANIFEST「一两张大表在一次回答里只搬一次」),下游 —— 工作流节点、
画板、插件页「试一下」的表单、发给智能体的那一份 —— 看到的形状和逐格写全时**一个字节都不差**:下拉照样是整张
(ADR 0044 修订:插件交的这份 `input_schema` 就是表单读的那一份,长下拉不能在这里删)。

**只在宿主说了它收得下时才这么交**(请求里的 `accepts` 有 `shared_tables`)。没说的宿主(应用是旧版、插件从
市场升上来了)拿到的还是逐格写全的那一份:清单照旧撞线、照旧响亮地报错 —— 而不是收到一堆指不到的表、
悄悄少几张下拉。
"""

from __future__ import annotations

import json
from typing import Any

#: 宿主在请求的 `accepts` 里说它收得下这个(见模块说明)。
ACCEPTS = "shared_tables"
#: 回答顶层的表:`{"<id>": [值, …]}`。
TABLE_KEY = "shared_tables"
#: 格子上指过去的那一格。
REF_KEY = "x-shared-table"
#: 一张表重复两次以上、而且不止一两个值,才值得指一次 —— 两项的表指过去的开销比表本身还大。
_MIN_TABLE_BYTES = 64


def accepted(request: Any) -> bool:
    """宿主在请求里说了它收得下(见模块说明)。没说的照旧逐格写全。"""
    accepts = request.get("accepts") if isinstance(request, dict) else None
    return isinstance(accepts, list) and ACCEPTS in accepts


def _canonical(values: list[Any]) -> str:
    """一张表的身份:值一样就是同一张(和格子上那几格的字面量无关)。"""
    return json.dumps(values, ensure_ascii=False)


def _enum(one: Any) -> list[Any] | None:
    """这一格带着一张可选值表吗。只认**全是标量**的表 —— 别的 `enum` 不是我们在说的那种大表。"""
    if not isinstance(one, dict):
        return None
    values = one.get("enum")
    if not isinstance(values, list) or not values:
        return None
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            return None
    return values


def _count(node: Any, found: dict[str, int]) -> None:
    """整份回答里每张表各出现几次。"""
    values = _enum(node)
    if values is not None:
        key = _canonical(values)
        found[key] = found.get(key, 0) + 1
    for child in (node.values() if isinstance(node, dict) else node if isinstance(node, list) else ()):
        _count(child, found)


def _share(node: Any, seen: dict[str, int], names: dict[str, str], tables: dict[str, list[Any]]) -> None:
    """重复的表挪进 `tables`(第一次见到的顺序),格子上写引用;只出现一次的原地留着。"""
    if isinstance(node, dict):
        values = _enum(node)
        if values is not None:
            key = _canonical(values)
            if seen.get(key, 0) >= 2 and len(key.encode("utf-8")) >= _MIN_TABLE_BYTES:
                if key not in names:
                    names[key] = f"t{len(names) + 1}"
                    tables[names[key]] = values
                del node["enum"]
                node[REF_KEY] = names[key]
        for child in node.values():
            _share(child, seen, names, tables)
    elif isinstance(node, list):
        for child in node:
            _share(child, seen, names, tables)


def share(output: Any) -> Any:
    """回答里重复的大表只留一次(见模块说明)。没有重复的一律原样交回,一个字节都不动。"""
    if not isinstance(output, dict):
        return output
    seen: dict[str, int] = {}
    _count(output, seen)
    names: dict[str, str] = {}
    tables: dict[str, list[Any]] = {}
    _share(output, seen, names, tables)
    if tables:
        output[TABLE_KEY] = tables
    return output


__all__ = ["ACCEPTS", "REF_KEY", "TABLE_KEY", "accepted", "share"]
