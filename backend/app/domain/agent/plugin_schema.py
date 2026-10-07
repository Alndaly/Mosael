"""发给智能体的插件工具入参收紧成什么样(ADR 0044 修订 2026-10-08)。

插件报的 `input_schema` 是给表单的:工作流节点、画板、插件页「试一下」都按它渲染,下拉要整张(ComfyUI 一个 LoRA 下拉几百项),
`x-*` 是给界面的提示,上下限、步长照着节点定义原样抄。工具定义每轮重发,这些对智能体是一个字一个字的开销 —— 维护者那台
ComfyUI 上一张工作流的工具 8 万多字符。所以**只在发给智能体的那一份上**收紧,插件存的那份不动:

- 选项超过 `ENUM_INLINE` 个的下拉换成一句「N 个可选值」,指向查可选值的工具(`LOOKUP_TOOL`);
- 去掉 `x-*`、步长和没有意义的上下限(±1.8e19 那种,节点没给范围时抄来的);说明和标题说的是同一件事时只留标题;
- 收紧之后入参还超过 `SPEC_CAP` 字符,就按「必填的 → 非高级的 → 高级的」挑,挑到上限为止,剩下的数一个数交回去 ——
  工具说明里说一句,`LOOKUP_TOOL` 看得到全部,照样能传。

只用在 `comfyui` 那一份的插件工具上(见 tool_manifest):查可选值的工具在那一份里,两样总是一起发。
"""

from __future__ import annotations

import json
from typing import Any

#: 下拉的选项多于这么多,就不进定义(16 项的调度器、采样器那种短表留着;几十上百项的模型、LoRA 换成一句)。
ENUM_INLINE = 16
#: 一个工具的入参(收紧之后)最多这么多字符。维护者那台上收紧后中位数约 3.8K,一张 117 个可调项的图约 2 万。
SPEC_CAP = 4000
#: 查一张工作流的全部入参、某个下拉的可选值。
LOOKUP_TOOL = "comfy_workflow_inputs"
#: 比这还大的上下限当没给(ComfyUI 的节点没写范围时,前端抄的是 64 位整数的边)。
_UNBOUNDED = 1e15


def _plain(text: Any) -> str:
    return "".join(char for char in str(text or "").lower() if char.isalnum())


def options_note(count: int) -> str:
    return f"{count} options — {LOOKUP_TOOL} lists them"


def compact_property(spec: Any) -> Any:
    """一格入参收紧之后的样子(见模块说明)。不是对象的原样交回。"""
    if not isinstance(spec, dict):
        return spec
    out: dict[str, Any] = {}
    for key, value in spec.items():
        if key.startswith("x-") or key == "multipleOf":
            continue
        if key in ("minimum", "maximum") and isinstance(value, (int, float)) and abs(value) >= _UNBOUNDED:
            continue
        out[key] = value
    title, description = _plain(out.get("title")), _plain(out.get("description"))
    if description and title and (description == title or description in title):
        out.pop("description")
    enum = out.get("enum")
    if isinstance(enum, list) and len(enum) > ENUM_INLINE:
        out.pop("enum")
        note = options_note(len(enum))
        out["description"] = f"{out['description']} ({note})" if out.get("description") else note
    return out


def _advanced(spec: Any) -> bool:
    return isinstance(spec, dict) and spec.get("x-advanced") is True


def agent_parameters(schema: Any, *, cap: int = SPEC_CAP) -> tuple[dict[str, Any], int]:
    """发给智能体的入参和**没列出的有几项**。按「必填 → 非高级 → 高级」挑到 `cap` 字符为止,列出来的照原来的先后排。"""
    if not isinstance(schema, dict) or not isinstance(schema.get("properties"), dict):
        return schema if isinstance(schema, dict) else {"type": "object", "properties": {}}, 0
    raw: dict[str, Any] = schema["properties"]
    required = [key for key in schema.get("required") or [] if isinstance(key, str) and key in raw]
    compacted = {key: compact_property(spec) for key, spec in raw.items()}
    rest = {key: value for key, value in schema.items() if key not in ("properties", "required")}
    whole = {**rest, "properties": compacted, **({"required": required} if required else {})}
    if len(json.dumps(whole, ensure_ascii=False)) <= cap:
        return whole, 0
    order = list(compacted)
    priority = ([key for key in order if key in required] + [key for key in order if key not in required and not _advanced(raw[key])]
                + [key for key in order if key not in required and _advanced(raw[key])])
    budget = cap - len(json.dumps({**rest, "properties": {}, **({"required": required} if required else {})}, ensure_ascii=False))
    kept: set[str] = set()
    for key in priority:
        size = len(json.dumps({key: compacted[key]}, ensure_ascii=False)) + 1
        if key in required or size <= budget:
            kept.add(key)
            budget -= size
    listed = {key: compacted[key] for key in order if key in kept}
    return {**rest, "properties": listed, **({"required": required} if required else {})}, len(order) - len(listed)


def omitted_note(count: int) -> str:
    return (f"{count} more inputs (advanced) aren't listed here — {LOOKUP_TOOL} shows them all; "
            "they can still be passed.")


__all__ = ["ENUM_INLINE", "LOOKUP_TOOL", "SPEC_CAP", "agent_parameters", "compact_property", "omitted_note", "options_note"]
