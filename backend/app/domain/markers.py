"""画布上的**标记**:一个位置书签,不是节点。

标记不执行、不连线、不产出。它唯一会做的事是「把视口带到这儿」—— 一张几十个节点的图铺开
之后,找回上次在改的那块地方要靠拖和缩放,而标记把它变成按一下键。

## 为什么它不是节点、也不是画板项

工作流的节点必须在 `NODE_TYPES` 里、要被运行时执行、要过就绪检查;画板的项是**生成单元**
(空槽 → 排队 → 有产出)。标记两样都不是:把它做成节点,运行时就要在每个分支上专门绕开它,
而漏掉的那一次就是一次「未知节点类型」的运行失败。所以它自成一份列表,和 nodes / items 平级。

用户自己也是这么说的:「其实不像是节点 更像是标记」。

## 为什么校验放在这一层

两个页面(画板、工作流)各存各的 JSON,而**冲突规则必须只有一份** —— 同一份文档里两个标记
绑同一个键,后按的那个永远跳不到,用户看到的是「这个快捷键坏了」。两边各写一遍的话,漂掉的
那一半就是没挡住的那条路。

快捷键怎么归一,由 `contracts/marker-shortcut-cases.json` 钉住 —— 前端在配置时也要归一次
(它得当场判断能不能配),两边归出不同的串时谁都不报错,只会悄悄错开。

至于「和应用自己的快捷键撞了」,那一条不在这里:应用有哪些快捷键是**界面**那一侧的事实,
后端既不知道也不该知道(见 frontend/src/lib/shortcuts.ts)。这里守的是数据本身的不变量。
"""

from __future__ import annotations

import math
from typing import Any

#: 一份文档里最多几个标记。上限存在的理由不是性能,是**键不够用** —— 能绑的组合就那么多,
#: 几十个之后标记本身就变成了另一件要找的东西。
MAX_MARKERS = 64

MAX_NAME_CHARS = 80

#: 允许绑的功能键。除了这些就只能是单个可打印字符(字母统一存大写,见 _normalize_key)。
#:
#: 这份名单**故意不含** Enter / Escape / Tab / Space / 方向键 / Backspace / Delete ——
#: 它们在画布上已经各有各的意思(确认、取消、移动焦点、平移、删除选中),而一个跳转标记
#: 不该把它们抢走。挡在这里而不是只在界面里挡:后端放行的形状,总有一天会有第二个客户端写进来。
NAMED_KEYS = (
    "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
    "Home", "End", "PageUp", "PageDown",
)

#: 修饰键。`Mod` 是 macOS 的 ⌘ 和 Windows/Linux 的 Ctrl **合并成的一个** —— 应用里每一处
#: 快捷键判的都是 `metaKey || ctrlKey`,分成两个存的话,同一份画板在两个系统上就会有两套绑定。
MODIFIERS = ("Mod", "Alt", "Shift")


class MarkerError(ValueError):
    """标记本身不合法。调用方(画板 / 工作流)负责翻译成自己那一侧的错误。"""


def _normalize_key(raw: str) -> str:
    if raw in NAMED_KEYS:
        return raw
    if len(raw) == 1 and raw.isprintable() and not raw.isspace():
        # 字母统一大写:`a` 和 `A` 按下去是同一个键(Shift 单独占一个修饰位),
        # 分开存的话「已经绑了 A」这条判断会漏掉一半。
        return raw.upper()
    raise MarkerError(f"快捷键里不能用 {raw!r} 这个键")


def normalize_shortcut(raw: Any) -> str:
    """把一个快捷键归一成 `Mod+Alt+Shift+K` 这样的规范串。

    归一而不是原样收下:`Shift+Mod+k` 和 `Mod+Shift+K` 是同一个绑定,不归一的话查重查不出来。
    """
    if not isinstance(raw, str):
        raise MarkerError("标记的 shortcut 必须是字符串")
    parts = [part.strip() for part in raw.split("+") if part.strip()]
    if not parts:
        raise MarkerError("标记的 shortcut 不能为空")
    key = _normalize_key(parts[-1])
    seen: set[str] = set()
    for part in parts[:-1]:
        canonical = {"mod": "Mod", "cmd": "Mod", "meta": "Mod", "ctrl": "Mod", "control": "Mod",
                     "alt": "Alt", "option": "Alt", "shift": "Shift"}.get(part.lower())
        if canonical is None:
            raise MarkerError(f"快捷键里不认识的修饰键:{part}")
        if canonical in seen:
            raise MarkerError(f"快捷键里重复的修饰键:{canonical}")
        seen.add(canonical)
    return "+".join([m for m in MODIFIERS if m in seen] + [key])


def _finite(value: Any, field: str, marker_id: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MarkerError(f"标记 {marker_id} 的 {field} 必须是数字,收到 {value!r}")
    number = float(value)
    # NaN / Infinity 存得进去,但 `JSON.parse` 读不回来 —— 存进一个就是整份画布再也打不开。
    if not math.isfinite(number):
        raise MarkerError(f"标记 {marker_id} 的 {field} 不是有限数")
    return number


def normalize_markers(raw: Any) -> list[dict[str, Any]]:
    """校验并归一一份标记列表。缺省(None / 没这个键)= 一份都没有。"""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise MarkerError("markers 必须是数组")
    if len(raw) > MAX_MARKERS:
        raise MarkerError(f"一份文档最多 {MAX_MARKERS} 个标记,收到 {len(raw)} 个")

    markers: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    bound: dict[str, str] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            raise MarkerError("标记必须是对象")
        marker_id = str(entry.get("id") or "").strip()
        if not marker_id:
            raise MarkerError("标记的 id 不能为空")
        if len(marker_id) > 64:
            raise MarkerError(f"标记的 id 过长:{marker_id[:16]}…")
        if marker_id in seen_ids:
            raise MarkerError(f"标记 id 重复:{marker_id}")
        seen_ids.add(marker_id)

        name = entry.get("name")
        if name is not None and not isinstance(name, str):
            raise MarkerError(f"标记 {marker_id} 的 name 必须是字符串")
        marker: dict[str, Any] = {
            "id": marker_id,
            "name": (name or "").strip()[:MAX_NAME_CHARS],
            "x": _finite(entry.get("x"), "x", marker_id),
            "y": _finite(entry.get("y"), "y", marker_id),
        }

        shortcut = entry.get("shortcut")
        if shortcut is not None and str(shortcut).strip():
            combo = normalize_shortcut(shortcut)
            # 同一份文档里两个标记绑同一个键 —— 存得下,但按下去只会跳到其中一个,
            # 另一个从此再也跳不到。这不是界面的偏好,是这份数据的不变量。
            if combo in bound:
                raise MarkerError(f"快捷键 {combo} 已经绑给了标记「{bound[combo]}」")
            bound[combo] = marker["name"] or marker_id
            marker["shortcut"] = combo

        markers.append(marker)
    return markers


def marker_errors(raw: Any) -> list[str]:
    """同一份规则的「返回错误列表」形态,给工作流的 validate_graph 用(它不抛,它收集)。"""
    try:
        normalize_markers(raw)
    except MarkerError as exc:
        return [str(exc)]
    return []
