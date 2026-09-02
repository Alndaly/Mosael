from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from app.core.http_retry import RetryingClient

"""
ComfyUI 深度接入的隔离层:所有「ComfyUI 内部格式」知识只在这一个模块里。

ComfyUI 保存的工作流是 UI 图格式(nodes/links/widgets_values),而 /prompt 只吃 API 格式
(node_id → {class_type, inputs}),两者的转换在 ComfyUI 前端的 graphToPrompt 里、没有后端端点。
这里复现那套转换,并自动把 Mosael 的 prompt/seed/尺寸注入到识别出的节点。

耦合都收在此处:ComfyUIGenerationAdapter 只调这里的函数,core(runner / GenerationAdapter 协议)对
ComfyUI 的 graph/widget/object_info 一无所知。转换是「尽力适配」——认不出的非常规工作流由
调用方回退到手动 API 模板,不会让整个功能塌掉。
"""

#: 纯 UI / 不进 API prompt 的节点类型(注释、分组标记、透传)。Reroute 单独在连线里透传。
_SKIP_NODE_TYPES = frozenset(
    {"Note", "MarkdownNote", "Reroute", "PrimitiveNode", "PrimitiveString", "PrimitiveInt", "PrimitiveFloat", "GetNode", "SetNode"}
)
#: ComfyUI 节点 mode:2=muted、4=bypassed —— 都不该进 prompt。
_INACTIVE_MODES = frozenset({2, 4})
#: 采样器类节点:自动注入 seed、并顺 positive/negative 追溯提示词节点。
_SAMPLER_TYPES = frozenset({"KSampler", "KSamplerAdvanced", "SamplerCustom", "SamplerCustomAdvanced"})


def _has_control_after_generate(input_def: Any) -> bool:
    """object_info 里某输入是否带 control_after_generate(seed 类 INT)——它在 widgets_values 里
    多占一个隐藏项(randomize/fixed/…),转换时必须跳过,否则后续 widget 全部错位。"""
    return (
        isinstance(input_def, list)
        and len(input_def) > 1
        and isinstance(input_def[1], dict)
        and bool(input_def[1].get("control_after_generate"))
    )


def graph_to_api_prompt(ui_graph: dict[str, Any], object_info: dict[str, Any]) -> dict[str, Any]:
    """ComfyUI UI 图 → /prompt 的 API 格式。复现前端 graphToPrompt 的核心语义。

    - 连接输入(node.inputs 里带 link)→ [源节点id, 源槽位];Reroute 节点透传到真实源。
    - widget 输入(带 widget 标记)→ 顺序取 widgets_values,并据 object_info 的
      control_after_generate 跳过隐藏项。
    - 跳过 UI-only 节点与 muted/bypass 节点。
    """
    nodes = [n for n in (ui_graph.get("nodes") or []) if isinstance(n, dict)]
    links_by_id: dict[Any, list] = {}
    for link in ui_graph.get("links") or []:
        if isinstance(link, list) and len(link) >= 5:
            links_by_id[link[0]] = link
    nodes_by_id = {n.get("id"): n for n in nodes}

    def resolve_source(link_id: Any) -> list | None:
        """顺连线找到真实源(节点id, 槽位),透传 Reroute;防环。"""
        seen: set[Any] = set()
        while link_id is not None and link_id not in seen:
            seen.add(link_id)
            link = links_by_id.get(link_id)
            if not link:
                return None
            from_node, from_slot = link[1], link[2]
            src = nodes_by_id.get(from_node)
            if src is not None and src.get("type") == "Reroute":
                first_input = (src.get("inputs") or [{}])[0]
                link_id = first_input.get("link")
                continue
            return [str(from_node), from_slot]
        return None

    api: dict[str, Any] = {}
    for node in nodes:
        node_id, node_type = node.get("id"), node.get("type")
        if node_id is None or not node_type:
            continue
        if node.get("mode") in _INACTIVE_MODES or node_type in _SKIP_NODE_TYPES:
            continue
        type_input = (object_info.get(node_type) or {}).get("input") or {}
        input_defs = {**(type_input.get("required") or {}), **(type_input.get("optional") or {})}
        widgets = node.get("widgets_values")
        widgets = widgets if isinstance(widgets, list) else []
        inputs: dict[str, Any] = {}
        value_index = 0
        for inp in node.get("inputs") or []:
            name = inp.get("name")
            if not name:
                continue
            has_widget = "widget" in inp
            if inp.get("link") is not None:
                source = resolve_source(inp["link"])
                if source is not None:
                    inputs[name] = source
                # converted-to-input:widget 被拉成了连接,但它在 widgets_values 里仍占位置——
                # 必须照样步进索引,否则后续 widget 全部对错(如 batch_size 取到 width 的旧值)。
                if has_widget and value_index < len(widgets):
                    value_index += 1
                    if _has_control_after_generate(input_defs.get(name)):
                        value_index += 1
            elif has_widget:
                if value_index < len(widgets):
                    inputs[name] = widgets[value_index]
                    value_index += 1
                    if _has_control_after_generate(input_defs.get(name)):
                        value_index += 1
        api[str(node_id)] = {"class_type": node_type, "inputs": inputs}
    return api


def inject_generation_params(api_prompt: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """把 Mosael 的 prompt/negative/seed/width/height 注入到转换出的 API prompt(就地改并返回)。

    自动识别:从采样器的 positive/negative 出发**递归追溯**到 CLIPTextEncode.text 写提示词——
    穿过 ControlNet/条件拼接等中间节点(优先追同名条件槽,正负不混);采样器 seed/noise_seed 写
    随机种;EmptyLatentImage 的 width/height 写尺寸。只覆盖「字面量」输入,连接来的输入不动。
    识别不到就不改——调用方仍可用 {{prompt}} 占位符兜底。
    """
    def set_literal(node_inputs: dict[str, Any], key: str, value: Any) -> None:
        if key in node_inputs and not isinstance(node_inputs[key], list):
            node_inputs[key] = value

    def find_text_encode(ref: Any, prefer_slot: str, seen: set[str]) -> dict[str, Any] | None:
        """从 [node,slot] 引用追溯到 CLIPTextEncode(穿过 ControlNetApply 等条件处理节点)。"""
        if not isinstance(ref, list) or not ref:
            return None
        node_id = str(ref[0])
        if node_id in seen:
            return None
        seen.add(node_id)
        node = api_prompt.get(node_id)
        if node is None:
            return None
        if str(node.get("class_type", "")).startswith("CLIPTextEncode"):
            return node
        inputs = node.get("inputs", {})
        for key in (prefer_slot, "conditioning", "positive", "negative"):  # 优先同名槽,正负不混
            found = find_text_encode(inputs.get(key), prefer_slot, seen)
            if found is not None:
                return found
        return None

    for node in api_prompt.values():
        class_type = node.get("class_type", "")
        inputs = node.get("inputs", {})
        if class_type in _SAMPLER_TYPES:
            set_literal(inputs, "seed", values.get("seed"))
            set_literal(inputs, "noise_seed", values.get("seed"))
            for slot, value_key in (("positive", "prompt"), ("negative", "negative")):
                target = find_text_encode(inputs.get(slot), slot, set())
                if target is not None:
                    set_literal(target.setdefault("inputs", {}), "text", values.get(value_key))
        elif class_type == "EmptyLatentImage":
            set_literal(inputs, "width", values.get("width"))
            set_literal(inputs, "height", values.get("height"))
    return api_prompt


def _trace_text_encode_id(ref: Any, api_prompt: dict[str, Any], prefer_slot: str, seen: set[str]) -> str | None:
    """从 [node,slot] 追溯到 CLIPTextEncode 的节点 id(穿过 ControlNetApply 等),供角色标注。"""
    if not isinstance(ref, list) or not ref:
        return None
    node_id = str(ref[0])
    if node_id in seen:
        return None
    seen.add(node_id)
    node = api_prompt.get(node_id)
    if node is None:
        return None
    if str(node.get("class_type", "")).startswith("CLIPTextEncode"):
        return node_id
    inputs = node.get("inputs", {})
    for key in (prefer_slot, "conditioning", "positive", "negative"):
        found = _trace_text_encode_id(inputs.get(key), api_prompt, prefer_slot, seen)
        if found is not None:
            return found
    return None


def _text_encode_roles(api_prompt: dict[str, Any]) -> dict[str, str]:
    """{CLIPTextEncode 节点id → "prompt"/"negative"},由采样器 positive/negative 追溯得到。"""
    roles: dict[str, str] = {}
    for node in api_prompt.values():
        if node.get("class_type") in _SAMPLER_TYPES:
            for slot, role in (("positive", "prompt"), ("negative", "negative")):
                target = _trace_text_encode_id(node.get("inputs", {}).get(slot), api_prompt, slot, set())
                if target is not None:
                    roles.setdefault(target, role)
    return roles


def _describe_param(
    node_id: str, class_type: str, title: str | None, name: str, value: Any, input_def: Any, role: str | None
) -> dict[str, Any] | None:
    """把一个字面量输入描述成前端可渲染的参数(类型 + 约束)。未知类型/无定义 → None(跳过)。"""
    if not isinstance(input_def, list) or not input_def:
        return None
    type_spec = input_def[0]
    constraints = input_def[1] if len(input_def) > 1 and isinstance(input_def[1], dict) else {}
    param: dict[str, Any] = {"node_id": node_id, "class_type": class_type, "title": title, "name": name, "value": value, "role": role}
    if isinstance(type_spec, list):
        param["type"] = "COMBO"
        param["options"] = [str(option) for option in type_spec]
    elif type_spec in ("INT", "FLOAT"):
        param["type"] = type_spec
        for key in ("min", "max", "step"):
            if key in constraints:
                param[key] = constraints[key]
    elif type_spec == "BOOLEAN":
        param["type"] = "BOOLEAN"
    elif type_spec == "STRING":
        param["type"] = "STRING"
        param["multiline"] = bool(constraints.get("multiline"))
    else:
        return None
    return param


def extract_workflow_params(ui_graph: dict[str, Any], object_info: dict[str, Any]) -> list[dict[str, Any]]:
    """从工作流提取「可调的字面量输入」,供前端动态生成参数表单。每项含节点/输入名/类型/当前值/
    取值范围(INT/FLOAT 的 min/max/step、COMBO 的 options),并标出语义角色(prompt/negative/seed/
    width/height)让前端把 Mosael 的主提示词/尺寸对上去。连接来的输入(值来自上游节点)不可调,跳过。"""
    api = graph_to_api_prompt(ui_graph, object_info)
    titles: dict[str, str] = {}
    for node in ui_graph.get("nodes") or []:
        if isinstance(node, dict):
            titles[str(node.get("id"))] = str(
                node.get("title") or (node.get("properties") or {}).get("Node name for S&R") or node.get("type") or ""
            )
    roles = _text_encode_roles(api)
    params: list[dict[str, Any]] = []
    for node_id, node in api.items():
        class_type = str(node["class_type"])
        type_input = (object_info.get(class_type) or {}).get("input") or {}
        defs = {**(type_input.get("required") or {}), **(type_input.get("optional") or {})}
        for name, value in node["inputs"].items():
            if isinstance(value, list):  # 连接输入不可调
                continue
            role: str | None = None
            if name in ("seed", "noise_seed"):
                role = "seed"
            elif name == "width":
                role = "width"
            elif name == "height":
                role = "height"
            elif class_type.startswith("CLIPTextEncode") and name == "text":
                role = roles.get(node_id)
            described = _describe_param(node_id, class_type, titles.get(node_id), name, value, defs.get(name), role)
            if described is not None:
                params.append(described)
    return params


def apply_workflow_params(api_prompt: dict[str, Any], overrides: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """把动态表单里用户改过的值({node_id: {input_name: value}})覆盖回 API prompt(就地)。只改字面量
    输入,连接输入不动;节点/输入不存在则忽略(工作流可能已变,不该因此报错)。"""
    for node_id, inputs in (overrides or {}).items():
        node = api_prompt.get(str(node_id))
        if not isinstance(node, dict):
            continue
        node_inputs = node.get("inputs", {})
        for name, value in (inputs or {}).items():
            if name in node_inputs and not isinstance(node_inputs[name], list):
                node_inputs[name] = value
    return api_prompt


class ComfyUIClient:
    """ComfyUI HTTP 接入。短生命周期,随生成/列举请求创建。"""

    def __init__(self, base_url: str, timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _client(self) -> httpx.Client:
        return RetryingClient(base_url=self.base_url, timeout=self.timeout)

    def list_workflows(self) -> list[dict[str, Any]]:
        """ComfyUI 里保存的工作流列表(名字 + 修改时间),供前端下拉。"""
        with self._client() as client:
            response = client.get(
                "/api/userdata", params={"dir": "workflows", "recurse": "true", "split": "false", "full_info": "true"}
            )
            response.raise_for_status()
            items = response.json()
        result: list[dict[str, Any]] = []
        for item in items if isinstance(items, list) else []:
            path = item.get("path") if isinstance(item, dict) else item
            if isinstance(path, str) and path.endswith(".json"):
                result.append({"path": path, "name": path[:-5], "modified": (item or {}).get("modified") if isinstance(item, dict) else None})
        result.sort(key=lambda entry: entry["name"].lower())
        return result

    def fetch_workflow(self, path: str) -> dict[str, Any]:
        """按 path 拉取单个工作流的 UI 图 JSON。"""
        with self._client() as client:
            response = client.get(f"/api/userdata/{quote('workflows/' + path, safe='')}")
            response.raise_for_status()
            return response.json()

    def fetch_object_info(self) -> dict[str, Any]:
        """全量节点定义(转换对齐 widgets 需要它的 control_after_generate 等元数据)。"""
        with self._client() as client:
            response = client.get("/api/object_info")
            response.raise_for_status()
            return response.json()

    def workflow_to_api_prompt(self, path: str) -> dict[str, Any]:
        """拉取工作流 + object_info,转成 API prompt(未注入参数)。"""
        ui_graph = self.fetch_workflow(path)
        object_info = self.fetch_object_info()
        return graph_to_api_prompt(ui_graph, object_info)

    def fetch_workflow_params(self, path: str) -> list[dict[str, Any]]:
        """拉取工作流 + object_info,提取可调参数清单(供动态表单)。"""
        ui_graph = self.fetch_workflow(path)
        object_info = self.fetch_object_info()
        return extract_workflow_params(ui_graph, object_info)
