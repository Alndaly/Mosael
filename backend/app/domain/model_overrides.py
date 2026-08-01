"""按模型的手动覆盖。

**为什么需要**:模型的上下文窗口、是不是推理模型、认不认图片,这些决定了我们怎么发请求;
而唯一的来源是供应商 `/models` 目录 —— 它经常不给(自定义模型名、别名、私有部署),给了也
可能不准。取不到时只能退回一个保守的 32000,于是 128k 的模型被按 32k 用,早早开始压缩。

**只存用户显式改过的键**,不存整份元数据。全量落库会让目录更新永远追不上这份快照:端点把
某模型的窗口从 32k 提到 128k,库里那份旧值仍按 32k 用,而用户根本没改过任何东西。

**分基本与高级**:上下文长度是唯一一个大多数人真会去动的(它直接决定"能聊多久"),其余三个
是排障用的开关,平时不该出现在眼前。
"""

from __future__ import annotations

from typing import Any

#: 上下文窗口的下限与上限。下限挡的是手滑填成 0 或 100 —— 那会让每一轮都触发压缩;
#: 上限只是防离谱输入,真有更大窗口的模型时改这里即可。
MIN_CONTEXT_WINDOW = 1024
MAX_CONTEXT_WINDOW = 10_000_000

#: 允许覆盖的键 → 类型。不在表里的键一律丢弃 —— 前端传什么就存什么会让这张表变成
#: 一个什么都能塞的口袋,下游读的时候永远不知道能指望里面有什么。
FIELDS: dict[str, str] = {
    # 基本
    "context_window": "int",
    # 高级(都对应 pi 里真实生效的开关,不是摆设):
    #   reasoning        → 推理模型,决定是否走各家的 thinking 格式
    #   vision           → model.input 是否含 image,决定图片能不能发给它
    #   reasoning_effort → compat.supportsReasoningEffort,决定发不发 reasoning_effort
    #   developer_role   → compat.supportsDeveloperRole,决定 system 用不用 developer 角色
    "reasoning": "bool",
    "vision": "bool",
    "reasoning_effort": "bool",
    "developer_role": "bool",
}

ADVANCED_FIELDS = ("reasoning", "vision", "reasoning_effort", "developer_role")


def normalize(raw: Any) -> dict[str, Any]:
    """把一份提交上来的覆盖清洗成可入库的形状。

    值为 None 表示**清除这一项**(回到跟随目录),所以 None 与"没传"必须区别对待:
    前者要落成删除,后者保持原样。这里返回的是"最终该存的那份",调用方直接替换。
    """
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key, kind in FIELDS.items():
        if key not in raw:
            continue
        value = raw[key]
        if value is None or value == "":
            continue  # 清除
        if kind == "bool":
            out[key] = bool(value)
            continue
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if key == "context_window":
            number = max(MIN_CONTEXT_WINDOW, min(number, MAX_CONTEXT_WINDOW))
        out[key] = number
    return out


def for_model(overrides: Any, model_id: str) -> dict[str, Any]:
    """某个模型当前生效的覆盖。没有就是空字典。"""
    if not isinstance(overrides, dict) or not model_id:
        return {}
    entry = overrides.get(model_id)
    return dict(entry) if isinstance(entry, dict) else {}


def put(overrides: Any, model_id: str, values: dict[str, Any]) -> dict[str, Any]:
    """写入某个模型的覆盖;values 为空则把这条整个删掉(而不是留一个空对象)。

    留空对象会让"有没有覆盖"这个判断变成"有键但里面是空的",下游每处都要多写一次判空。
    """
    base = dict(overrides) if isinstance(overrides, dict) else {}
    if values:
        base[model_id] = values
    else:
        base.pop(model_id, None)
    return base
