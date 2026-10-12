"""重复的大表只搬一次(`shared_tables` + `x-shared-table`)—— 插件那一侧搬,宿主这一侧展平;宿主自己发出去的
那一份(插件页接口)也照同一套收一次。

## 插件 → 宿主(这套东西原来只做这一跳)

一次回答的上限是 1MB(`runtime.MAX_OUTPUT_BYTES`),而 ComfyUI 一张工作流的工具带着好几张几百项的下拉表,而且
同一张表在图里每多一个节点就多一份:对着真机量,36 个工具的清单 1,055,758 字节,其中 58 万字节是重复的同一批表
(403 份、只有 77 张不同的表;维护者那台报 42 个工具)。插件因此把**重复的**表放在回答顶层一次、格子上指过去
(见 docs/PLUGIN_MANIFEST「一两张大表在一次回答里只搬一次」),而且**只在宿主说了收得下时才这么交**
(请求的 `accepts`,见 runtime)。

展平放在 `runtime._final_response` 里,而不是每个入口各做一次:一问一答和流式两条路共用那一段判读,再往下的
每一处 —— 存进 `plugin_instances.discovered_tools`、工作流节点的 config、画板、插件页「试一下」、发给智能体的
那一份 —— 看到的都是**展平之后**的形状,和插件逐格写全时一模一样:下拉照样是整张(ADR 0044 修订)。

## 宿主 → 浏览器(插件页接口那一份)

展平之后,同一批表在**宿主交出去的那份回答**里又各占一格:46 个工具的工具清单 2,929,540 字节,其中
`input_schema` 832,308 字节里 555,529 是重复的同一批表(一个工具里同一张 LoRA 表贴 4 份、46 个工具里同一张
贴 25 份)。工具条目的 `form`(界面真正读的那一份)不能这么收 —— 界面按 `options` 直接画下拉,格子上换成引用
它就画不出来(那是 UI 侧接缝,见 ADR 0045 §5「文件清单按需取」)。`input_schema` 是同一份声明的原始形态,
**界面一个字段都不读它**(`PluginsTable` 只读 `form`),所以宿主按同一套收一次:`share()` 把重复的 `enum`
挪进这个 schema 顶层的 `shared_tables`、格子上写引用,**键用内容指纹** —— 五个字段名不同、内容逐字节相同
(`lora_name_105` … `lora_name_109`)本来就该只搬一次。

`expand()` 对这两跳是同一个函数:一份回答进、每一格都带整张表的那份出。**展平之后逐字节相同**,连键的顺序
都一样(引用占的是 `enum` 原来的位置)—— 拿它当断言的那条测试在 `tests/test_plugin_page_payload_shared_tables.py`。

**不改行为**:插件那一侧的 `accepts` 协商、`x-shared-table` 的语义、答不上来的表就拒收整份,一条都没动;
`share()` 不改传进来的那一份(库里那份 `discovered_tools` 不被它碰),没重复的一个字节都不动。
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from app.domain.plugins.errors import PluginDomainError

#: 插件在回答里说它共享了哪些表(见模块说明)。
TABLE_KEY = "shared_tables"
#: 格子上指过去的那一格。
REF_KEY = "x-shared-table"
#: 宿主在请求的 `accepts` 里说它收得下这个(插件据此决定要不要共享)。
ACCEPTS = "shared_tables"
#: 一张表重复两次以上、而且不止一两个值,才值得指一次 —— 两项的表指过去的开销比表本身还大(和插件那一侧同一条线)。
MIN_TABLE_BYTES = 64
#: **一张表能进共享表的上限。** 超过它的表不进共享表,照旧逐格写全 —— 不截断、不丢选项(截断会让用户在下拉里
#: 找不到自己刚下的那个模型,而界面上不会有半句解释)。256KB = 插件那一侧整份回答上限(1MB)的四分之一:
#: 一张自己就吃掉整个上限四分之一的"下拉"其实是**一份文件清单**,该走的是按需取 + 服务端搜索(ADR 0045 §5),
#: 不是让它在每一条回答里整份搬一次。上限只决定「这张表值不值得共享」,不决定「给用户看几项」。
MAX_TABLE_BYTES = 256 * 1024


def expand(output: dict[str, Any]) -> dict[str, Any]:
    """一份回答 → 每一格都带着整张表的那一份(`shared_tables` 收走)。没共享过的原样交回,不做深拷贝。

    指到一张没交上来的表是**交回的东西不对**:照实说,不收这一份 —— 收下的话那一格就没有可选值了,
    而表单要的是整张下拉。别悄悄留一个指不到的引用。

    引用占的是 `enum` 原来的位置:所以展平回来的那一份和逐格写全时**连键的顺序都一样**(逐字节可比)。
    """
    if TABLE_KEY not in output:
        return output
    tables = output.get(TABLE_KEY)
    if not isinstance(tables, dict):
        raise PluginDomainError("pluginErr_sharedTablesBadShape", shape='{"<id>": [value, …]}')
    # 表自己那一格也得走一遍 `_inline`:别让它留在展平后的形状里(`expand` 交出去的从不带 `shared_tables`)。
    body = {key: value for key, value in output.items() if key != TABLE_KEY}
    return _inline(body, tables)


def _inline(node: Any, tables: dict[str, Any]) -> Any:
    """把引用换成整张表。没有任何引用的子树**原样交回**(不复制)—— 没共享过的那一份一个字节都不动。"""
    if isinstance(node, dict):
        name = node.get(REF_KEY)
        if name is not None:
            values = tables.get(name) if isinstance(name, str) else None
            if not isinstance(values, list):
                raise PluginDomainError("pluginErr_sharedTableMissing", table=str(name)[:40])
            out: dict[str, Any] = {}
            for key, value in node.items():
                # 引用那一格换成 `enum`,**位置不变**(见 expand 的说明)。
                out["enum" if key == REF_KEY else key] = values if key == REF_KEY else _inline(value, tables)
            return out
        changed = False
        rebuilt: dict[str, Any] = {}
        for key, value in node.items():
            child = _inline(value, tables)
            changed = changed or child is not value
            rebuilt[key] = child
        return rebuilt if changed else node
    if isinstance(node, list):
        changed = False
        rebuilt_list: list[Any] = []
        for child in node:
            new_child = _inline(child, tables)
            changed = changed or new_child is not child
            rebuilt_list.append(new_child)
        return rebuilt_list if changed else node
    return node


def share(output: dict[str, Any]) -> dict[str, Any]:
    """一份回答 → 重复的大表挪进顶层 `shared_tables`、格子上写 `x-shared-table` 的那一份(见模块说明)。

    **不改传进来的那一份**:重建带着引用的那一棵树,原来那棵(库里存的、调用方手里的)原样不动。
    键用**内容指纹**(值逐字节相同就是同一张表),id 就是那张表内容的指纹 —— 和遇到它的先后、字段叫什么无关。
    没重复的表、太小的表(见 `MIN_TABLE_BYTES`)、太大的表(见 `MAX_TABLE_BYTES`)一律原地不动。
    """
    if not isinstance(output, dict):
        return output
    counts: Counter[str] = Counter()
    contents: dict[str, list[Any]] = {}
    _survey(output, counts, contents)
    #: 内容 → 表 id。**按内容判等、按内容指纹起 id**:指纹撞了(两份不同的内容同一个 id)就不共享那一张 ——
    #: 宁可多搬几份,也不能把两张不同的表悄悄合成一张。
    names: dict[str, str] = {}
    taken: set[str] = set()
    for content, count in sorted(counts.items()):
        size = len(content.encode("utf-8"))
        if count < 2 or not MIN_TABLE_BYTES <= size <= MAX_TABLE_BYTES:
            continue
        name = _fingerprint(content)
        if name in taken:
            continue
        taken.add(name)
        names[content] = name
    if not names:
        return output
    rebuilt = _refer(output, names)
    if not isinstance(rebuilt, dict):  # pragma: no cover — 传进来的就是个 dict,重建成的一定也是
        return output
    rebuilt[TABLE_KEY] = {names[content]: contents[content] for content in sorted(names)}
    return rebuilt


def _fingerprint(content: str) -> str:
    """一张表的 id:内容指纹。值一样就是同一张,和字段叫什么、在哪见到无关(截 12 位十六进制)。"""
    return "t" + hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


def _canonical(values: list[Any]) -> str:
    """一张表的身份:值一样就是同一张(和格子上那几格的字面量无关)。"""
    return json.dumps(values, ensure_ascii=False)


def _enum(node: Any) -> list[Any] | None:
    """这一格带着一张可选值表吗。只认**全是标量**的表 —— 别的 `enum` 不是我们在说的那种大表。"""
    if not isinstance(node, dict):
        return None
    values = node.get("enum")
    if not isinstance(values, list) or not values:
        return None
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            return None
    return values


def _survey(node: Any, counts: Counter[str], contents: dict[str, list[Any]]) -> None:
    """整份回答里每张表各出现几次(按内容),以及每张表的内容各是哪一份。"""
    values = _enum(node)
    if values is not None:
        content = _canonical(values)
        counts[content] += 1
        contents.setdefault(content, values)
    for child in (node.values() if isinstance(node, dict) else node if isinstance(node, list) else ()):
        _survey(child, counts, contents)


def _refer(node: Any, names: dict[str, str]) -> Any:
    """共享的那几张表换成引用(引用占 `enum` 原来的位置);别的原样交回。按**内容**认表,不按指纹。"""
    if isinstance(node, dict):
        values = _enum(node)
        if values is not None:
            name = names.get(_canonical(values))
            if name is not None:
                out: dict[str, Any] = {}
                for key, value in node.items():
                    out[REF_KEY if key == "enum" else key] = name if key == "enum" else _refer(value, names)
                return out
        changed = False
        rebuilt: dict[str, Any] = {}
        for key, value in node.items():
            child = _refer(value, names)
            changed = changed or child is not value
            rebuilt[key] = child
        return rebuilt if changed else node
    if isinstance(node, list):
        changed = False
        rebuilt_list: list[Any] = []
        for child in node:
            new_child = _refer(child, names)
            changed = changed or new_child is not child
            rebuilt_list.append(new_child)
        return rebuilt_list if changed else node
    return node


__all__ = ["ACCEPTS", "MAX_TABLE_BYTES", "MIN_TABLE_BYTES", "REF_KEY", "TABLE_KEY", "expand", "share"]
