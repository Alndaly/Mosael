"""ComfyUI UI 图 → API 格式转换 + 提示词自动注入的回归测试(合成 fixture,不连实例)。

核心逻辑已用真实 ComfyUI(controlnet.json + /prompt 校验)端到端验证过;这里锁住几个易碎点:
control_after_generate 隐藏项跳过、连接解析、Reroute 透传、muted 跳过、注入递归穿过中间节点。"""

from __future__ import annotations

from app.ai.providers.comfyui_client import (
    extract_workflow_params,
    graph_to_api_prompt,
    inject_generation_params,
)

OBJECT_INFO = {
    "KSampler": {"input": {"required": {
        "seed": ["INT", {"control_after_generate": True}],  # 关键:标了 control_after_generate
        "steps": ["INT", {"min": 1, "max": 10000}],
        "cfg": ["FLOAT", {"min": 0.0, "max": 100.0}],
        "sampler_name": [["euler", "dpmpp_2m"]],  # COMBO
        "scheduler": [["normal", "karras"]],
        "denoise": ["FLOAT", {"min": 0.0, "max": 1.0}],
        "model": ["MODEL"], "positive": ["CONDITIONING"], "negative": ["CONDITIONING"], "latent_image": ["LATENT"],
    }}},
    "CLIPTextEncode": {"input": {"required": {"text": ["STRING", {"multiline": True}], "clip": ["CLIP"]}}},
    "EmptyLatentImage": {"input": {"required": {"width": ["INT"], "height": ["INT"], "batch_size": ["INT"]}}},
    "CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": ["STRING"]}}},
    "ControlNetApplyAdvanced": {"input": {"required": {"positive": ["CONDITIONING"], "negative": ["CONDITIONING"]}}},
}


def _widget(name):
    return {"name": name, "widget": {"name": name}, "link": None}


def _conn(name, link):
    return {"name": name, "link": link}


def test_control_after_generate_is_skipped_and_links_resolve() -> None:
    ui = {
        "nodes": [
            {"id": 3, "type": "KSampler", "widgets_values": [42, "randomize", 20],
             "inputs": [_conn("model", 1), _widget("seed"), _widget("steps")]},
            {"id": 4, "type": "CheckpointLoaderSimple", "widgets_values": ["m.safetensors"],
             "inputs": [_widget("ckpt_name")]},
        ],
        "links": [[1, 4, 0, 3, 0, "MODEL"]],
    }
    api = graph_to_api_prompt(ui, OBJECT_INFO)
    assert api["3"]["inputs"]["seed"] == 42
    assert api["3"]["inputs"]["steps"] == 20  # 'randomize' 是 seed 的隐藏项,必须跳过
    assert api["3"]["inputs"]["model"] == ["4", 0]  # 连接 → [源节点id, 槽位]


def test_muted_and_ui_only_nodes_skipped() -> None:
    ui = {
        "nodes": [
            {"id": 1, "type": "CLIPTextEncode", "mode": 0, "widgets_values": ["hi"], "inputs": [_widget("text")]},
            {"id": 2, "type": "CLIPTextEncode", "mode": 2, "widgets_values": ["muted"], "inputs": [_widget("text")]},
            {"id": 3, "type": "Note", "widgets_values": ["note"], "inputs": []},
        ],
        "links": [],
    }
    api = graph_to_api_prompt(ui, OBJECT_INFO)
    assert set(api.keys()) == {"1"}  # muted(mode=2)与 Note 都不进 prompt


def test_reroute_is_transparent() -> None:
    # CheckpointLoader(4) → Reroute(9) → KSampler(3).model
    ui = {
        "nodes": [
            {"id": 3, "type": "KSampler", "widgets_values": [1, "fixed", 20], "inputs": [_conn("model", 2), _widget("seed"), _widget("steps")]},
            {"id": 9, "type": "Reroute", "inputs": [_conn("", 1)]},
            {"id": 4, "type": "CheckpointLoaderSimple", "widgets_values": ["m.safetensors"], "inputs": [_widget("ckpt_name")]},
        ],
        "links": [[1, 4, 0, 9, 0, "MODEL"], [2, 9, 0, 3, 0, "MODEL"]],
    }
    api = graph_to_api_prompt(ui, OBJECT_INFO)
    assert "9" not in api  # Reroute 不进 prompt
    assert api["3"]["inputs"]["model"] == ["4", 0]  # 透传到真实源


def test_inject_recurses_through_controlnet() -> None:
    """KSampler.positive 连的是 ControlNetApply,提示词在更上游 —— 注入要递归穿过它,正负不混。"""
    api = {
        "3": {"class_type": "KSampler", "inputs": {"seed": 0, "positive": ["11", 0], "negative": ["11", 1]}},
        "11": {"class_type": "ControlNetApplyAdvanced", "inputs": {"positive": ["6", 0], "negative": ["7", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old pos"}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "old neg"}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512}},
    }
    inject_generation_params(api, {"prompt": "P", "negative": "N", "seed": 99, "width": 768, "height": 768})
    assert api["6"]["inputs"]["text"] == "P"  # 正向穿过 ControlNet
    assert api["7"]["inputs"]["text"] == "N"  # 负向不混
    assert api["3"]["inputs"]["seed"] == 99
    assert api["5"]["inputs"]["width"] == 768 and api["5"]["inputs"]["height"] == 768


def test_converted_widget_keeps_index_aligned() -> None:
    """widget 被拉成连接输入(converted-to-input)后仍占 widgets_values 一个位置——不步进就会错位:
    width/height 转连接后,batch_size 会误取 width 的旧值(真实 controlnet 工作流踩过这个坑)。"""
    ui = {
        "nodes": [
            {"id": 5, "type": "EmptyLatentImage", "widgets_values": [512, 768, 1],
             "inputs": [
                 {"name": "width", "widget": {"name": "width"}, "link": 1},   # converted:widget + link
                 {"name": "height", "widget": {"name": "height"}, "link": 2},
                 {"name": "batch_size", "widget": {"name": "batch_size"}, "link": None},
             ]},
            {"id": 8, "type": "CheckpointLoaderSimple", "widgets_values": ["m"], "inputs": [_widget("ckpt_name")]},
        ],
        "links": [[1, 8, 0, 5, 0, "INT"], [2, 8, 1, 5, 1, "INT"]],
    }
    api = graph_to_api_prompt(ui, OBJECT_INFO)
    assert api["5"]["inputs"]["batch_size"] == 1  # 不是 512
    assert api["5"]["inputs"]["width"] == ["8", 0]  # 连接


def test_extract_params_types_roles_and_ranges() -> None:
    ui = {
        "nodes": [
            {"id": 3, "type": "KSampler", "widgets_values": [42, "randomize", 20, 7.0, "euler", "normal", 1.0],
             "inputs": [
                 _conn("model", 1), _conn("positive", 2), _conn("negative", 3), _conn("latent_image", 4),
                 _widget("seed"), _widget("steps"), _widget("cfg"), _widget("sampler_name"), _widget("scheduler"), _widget("denoise"),
             ]},
            {"id": 6, "type": "CLIPTextEncode", "widgets_values": ["hello"], "inputs": [_conn("clip", 5), _widget("text")]},
        ],
        "links": [[2, 6, 0, 3, 1, "CONDITIONING"]],
    }
    params = {(p["class_type"], p["name"]): p for p in extract_workflow_params(ui, OBJECT_INFO)}
    assert params[("KSampler", "seed")]["type"] == "INT" and params[("KSampler", "seed")]["role"] == "seed"
    assert params[("KSampler", "cfg")]["type"] == "FLOAT" and params[("KSampler", "cfg")]["max"] == 100.0
    combo = params[("KSampler", "sampler_name")]
    assert combo["type"] == "COMBO" and combo["options"] == ["euler", "dpmpp_2m"]
    assert params[("CLIPTextEncode", "text")]["role"] == "prompt"  # KSampler.positive 追溯到它
    assert ("KSampler", "model") not in params  # 连接输入不出现在可调参数里


def test_inject_does_not_touch_connected_inputs() -> None:
    """text 若是连接(值来自上游 primitive),不能被字面量覆盖。"""
    api = {
        "3": {"class_type": "KSampler", "inputs": {"seed": 0, "positive": ["6", 0], "negative": ["7", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": ["8", 0]}},  # text 是连接
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "neg"}},
    }
    inject_generation_params(api, {"prompt": "P", "negative": "N", "seed": 1, "width": 512, "height": 512})
    assert api["6"]["inputs"]["text"] == ["8", 0]  # 连接输入不动
    assert api["7"]["inputs"]["text"] == "N"
