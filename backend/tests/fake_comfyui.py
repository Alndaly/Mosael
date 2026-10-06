"""一台假的 ComfyUI:本机随机端口上的 HTTP 服务(可选 WebSocket),给 ComfyUI 插件的测试用。

**测试套不连真的 ComfyUI。** 这台假的只实现插件用到的那几个接口,形状照 ComfyUI 0.3x 的真实回包:
`/object_info`、`/api/userdata`(列工作流 / 取工作流)、`/upload/image`(multipart)、`/prompt`、
`/history/{id}`、`/queue`、`/interrupt`、`/view`,以及 `/ws?clientId=…` 上的执行事件;模型库用到的
`/experiment/models*`、`/view_metadata/*`、ComfyUI-Custom-Scripts 的 `/pysssss/view/*`(按 Range 读文件头)、
`/pysssss/metadata/*`(按哈希找:算整个文件的 SHA256)、`/pysssss/save/*`(把 temp 里的一份拷成模型的预览图)、`/extensions`、
`/internal/logs/raw` 和 ComfyUI-Manager 的 `/v2/manager/*`;工作流库用到的
userdata 写 / 移动 / 删除(照 ComfyUI 源码 app/user_manager.py 的语义:`overwrite=false` 撞名回 409、写和移动时建目标的
父目录、移动的源可以是一个目录、删除是硬删)、连目录一起列的 `/api/v2/userdata`(空目录也在),和 Manager 的
`/v2/customnode/getmappings`、`/v2/customnode/installed`。

每次请求都记在 `server.calls` 里,测试据此断言插件发了什么(提交的图、上传的文件、停的是哪个任务)。
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import socket
import struct
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    b"\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)

#: 一份够用的节点定义(子集),形状照真实的 /object_info。
OBJECT_INFO: dict[str, Any] = {
    "KSampler": {"input": {"required": {
        "model": ["MODEL"],
        "seed": ["INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF, "control_after_generate": True}],
        "steps": ["INT", {"default": 20, "min": 1, "max": 10000}],
        "cfg": ["FLOAT", {"default": 8.0, "min": 0.0, "max": 100.0, "step": 0.1}],
        "sampler_name": [["euler", "dpmpp_2m"]],
        "scheduler": [["normal", "karras"]],
        "positive": ["CONDITIONING"], "negative": ["CONDITIONING"], "latent_image": ["LATENT"],
        "denoise": ["FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}],
    }}},
    "CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["sd_xl_base.safetensors", "v1-5.ckpt"]]}}},
    "CLIPTextEncode": {"input": {"required": {"text": ["STRING", {"multiline": True}], "clip": ["CLIP"]}}},
    "EmptyLatentImage": {"input": {"required": {
        "width": ["INT", {"default": 512, "min": 16, "max": 16384, "step": 8}],
        "height": ["INT", {"default": 512, "min": 16, "max": 16384, "step": 8}],
        "batch_size": ["INT", {"default": 1, "min": 1, "max": 4096}],
    }}},
    "VAEDecode": {"input": {"required": {"samples": ["LATENT"], "vae": ["VAE"]}}},
    "SaveImage": {"input": {"required": {"images": ["IMAGE"], "filename_prefix": ["STRING", {"default": "ComfyUI"}]}}},
    "LoadImage": {"input": {"required": {"image": [["example.png"], {"image_upload": True}]}}},
    "WanImageToVideo": {"input": {"required": {
        "positive": ["CONDITIONING"], "negative": ["CONDITIONING"], "vae": ["VAE"],
        "width": ["INT", {"default": 832, "min": 16, "max": 4096}],
        "height": ["INT", {"default": 480, "min": 16, "max": 4096}],
        "length": ["INT", {"default": 81, "min": 1, "max": 4096}],
        "batch_size": ["INT", {"default": 1, "min": 1, "max": 4096}],
    }, "optional": {"start_image": ["IMAGE"], "end_image": ["IMAGE"]}}},
    "VHS_VideoCombine": {"input": {"required": {"images": ["IMAGE"], "frame_rate": ["FLOAT", {"default": 8}]}},
                         "output_node": True},
    "LoadImageMask": {"input": {"required": {"image": [["mask.png"], {"image_upload": True}],
                                             "channel": [["alpha", "red", "green", "blue"]]}}},
    "LoadVideo": {"input": {"required": {"file": [["clip.mp4"], {"video_upload": True}]}}},
    "UpscaleModelLoader": {"input": {"required": {"model_name": [["4x-UltraSharp.pth", "RealESRGAN_x2.pth"]]}}},
    "ImageUpscaleWithModel": {"input": {"required": {"upscale_model": ["UPSCALE_MODEL"], "image": ["IMAGE"]}}},
    "LoraLoader": {"input": {"required": {
        "model": ["MODEL"], "clip": ["CLIP"], "lora_name": [["detail.safetensors", "anime.safetensors"]],
        "strength_model": ["FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.01}],
        "strength_clip": ["FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.01}],
    }}},
    "VAEEncode": {"input": {"required": {"pixels": ["IMAGE"], "vae": ["VAE"]}}},
    "PreviewImage": {"input": {"required": {"images": ["IMAGE"]}}, "output_node": True},
    "ShowText|pysssss": {"input": {"required": {"text": ["STRING", {"forceInput": True}]}}, "output_node": True},
    #: 参考图进模型的那一类(IP-Adapter):图接进来,交出改过的模型。
    "IPAdapter": {"input": {"required": {"model": ["MODEL"], "image": ["IMAGE"]}}, "output": ["MODEL"]},
    "VAEEncodeForInpaint": {"input": {"required": {
        "pixels": ["IMAGE"], "vae": ["VAE"], "mask": ["MASK"],
        "grow_mask_by": ["INT", {"default": 6, "min": 0, "max": 64, "step": 1}]}}, "output": ["LATENT"]},
    "Canny": {"input": {"required": {
        "image": ["IMAGE"], "low_threshold": ["FLOAT", {"default": 0.4, "min": 0.01, "max": 0.99, "step": 0.01}],
        "high_threshold": ["FLOAT", {"default": 0.8, "min": 0.01, "max": 0.99, "step": 0.01}]}}, "output": ["IMAGE"]},
    "ControlNetLoader": {"input": {"required": {"control_net_name": [["control_canny.safetensors"]]}},
                         "output": ["CONTROL_NET"]},
    "ControlNetApply": {"input": {"required": {
        "conditioning": ["CONDITIONING"], "control_net": ["CONTROL_NET"], "image": ["IMAGE"],
        "strength": ["FLOAT", {"default": 1.0, "min": 0.0, "max": 10.0, "step": 0.01}]}}, "output": ["CONDITIONING"]},
    "EmptyAceStepLatentAudio": {"input": {"required": {
        "seconds": ["FLOAT", {"default": 120.0, "min": 1.0, "max": 1000.0, "step": 0.1}],
        "batch_size": ["INT", {"default": 1, "min": 1, "max": 4096}]}}, "output": ["LATENT"]},
    "SaveAudio": {"input": {"required": {"audio": ["AUDIO"], "filename_prefix": ["STRING", {"default": "audio/ComfyUI"}]}},
                  "output_node": True},
}
for _name in ("SaveImage",):
    OBJECT_INFO[_name]["output_node"] = True


def widget(name: str) -> dict[str, Any]:
    return {"name": name, "widget": {"name": name}, "link": None}


def conn(name: str, link: int) -> dict[str, Any]:
    return {"name": name, "link": link}


#: 一张保存的**文生图 + 参考图**工作流(UI 格式),形状照 ComfyUI 前端保存下来的那种。参考图经 IP-Adapter 进模型
#: —— 它得真的接到出图那一路上:一个悬空的 LoadImage 什么都不影响,不是一格输入(graph.live)。
#: 新版 ComfyUI 前端保存工作流时写进去的 id(改名、挪目录都不变)。
PORTRAIT_ID = "3f2b1c9e-8d7a-4b6c-9e1f-0a1b2c3d4e5f"

PORTRAIT_UI: dict[str, Any] = {
    "id": PORTRAIT_ID,
    "nodes": [
        {"id": 3, "type": "KSampler", "title": "采样",
         "widgets_values": [42, "randomize", 20, 7.0, "euler", "normal", 1.0],
         "inputs": [conn("model", 1), conn("positive", 2), conn("negative", 3), conn("latent_image", 4),
                    widget("seed"), widget("steps"), widget("cfg"), widget("sampler_name"), widget("scheduler"),
                    widget("denoise")]},
        {"id": 4, "type": "CheckpointLoaderSimple", "widgets_values": ["sd_xl_base.safetensors"], "inputs": [widget("ckpt_name")]},
        {"id": 5, "type": "EmptyLatentImage", "widgets_values": [832, 1216, 1],
         "inputs": [widget("width"), widget("height"), widget("batch_size")]},
        {"id": 6, "type": "CLIPTextEncode", "widgets_values": ["a cat"], "inputs": [conn("clip", 5), widget("text")]},
        {"id": 7, "type": "CLIPTextEncode", "widgets_values": ["blurry"], "inputs": [conn("clip", 6), widget("text")]},
        {"id": 8, "type": "VAEDecode", "inputs": [conn("samples", 7), conn("vae", 8)]},
        {"id": 9, "type": "SaveImage", "widgets_values": ["mosael"], "inputs": [conn("images", 9), widget("filename_prefix")]},
        {"id": 10, "type": "LoadImage", "widgets_values": ["example.png", "image"], "inputs": [widget("image")]},
        {"id": 11, "type": "Note", "widgets_values": ["注释"], "inputs": []},
        {"id": 12, "type": "IPAdapter", "inputs": [conn("model", 10), conn("image", 11)]},
    ],
    "links": [
        [1, 12, 0, 3, 0, "MODEL"], [2, 6, 0, 3, 1, "CONDITIONING"], [3, 7, 0, 3, 2, "CONDITIONING"],
        [4, 5, 0, 3, 3, "LATENT"], [5, 4, 1, 6, 0, "CLIP"], [6, 4, 1, 7, 0, "CLIP"],
        [7, 3, 0, 8, 0, "LATENT"], [8, 4, 2, 8, 1, "VAE"], [9, 8, 0, 9, 0, "IMAGE"],
        [10, 4, 0, 12, 0, "MODEL"], [11, 10, 0, 12, 1, "IMAGE"],
    ],
}

#: 一张**多读图节点**的文生图(ADR 0038 的「YZ金鱼」那种:几个 LoadImage 都是参考图,在表单上分不出哪张是哪张):
#: 三张参考图各经一个 IP-Adapter 进模型(#10 起名「人物」,#13 没起名,#14 起名「背景」),再过一个 LoRA;两个保存节点
#: (#9 存成品、#17 存同一张的另一份)。节点上、图上带着别的扩展写的键(`ue_properties`、`extra.ue_links`):应用表单的
#: 标记写进去之后它们得原样还在。
def multi_reference_ui() -> dict[str, Any]:
    def node(node_id: int, kind: str, widgets: list[Any], inputs: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
        return {"id": node_id, "type": kind, "pos": [node_id * 40, 0], "size": [300, 120], "mode": 0,
                "widgets_values": widgets, "inputs": inputs,
                "properties": {"Node name for S&R": kind, "ue_properties": {"version": "7.1"}}, **extra}

    return {
        "id": "7c1d2e3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f",
        "revision": 0,
        "nodes": [
            node(3, "KSampler", [42, "fixed", 25, 6.5, "euler", "karras", 1.0],
                 [conn("model", 9), conn("positive", 10), conn("negative", 11), conn("latent_image", 12),
                  widget("seed"), widget("steps"), widget("cfg"), widget("sampler_name"), widget("scheduler"),
                  widget("denoise")], title="采样"),
            node(4, "CheckpointLoaderSimple", ["sd_xl_base.safetensors"], [widget("ckpt_name")]),
            node(5, "EmptyLatentImage", [1024, 1024, 1], [widget("width"), widget("height"), widget("batch_size")]),
            node(6, "CLIPTextEncode", ["a girl in a garden"], [conn("clip", 13), widget("text")]),
            node(7, "CLIPTextEncode", ["blurry"], [conn("clip", 14), widget("text")]),
            node(8, "VAEDecode", [], [conn("samples", 15), conn("vae", 16)]),
            node(9, "SaveImage", ["app"], [conn("images", 17), widget("filename_prefix")]),
            node(10, "LoadImage", ["face.png", "image"], [widget("image")], title="人物"),
            node(12, "IPAdapter", [], [conn("model", 1), conn("image", 2)]),
            node(13, "LoadImage", ["style.png", "image"], [widget("image")]),
            node(14, "LoadImage", ["bg.png", "image"], [widget("image")], title="背景"),
            node(15, "IPAdapter", [], [conn("model", 3), conn("image", 4)]),
            node(16, "IPAdapter", [], [conn("model", 5), conn("image", 6)]),
            node(17, "SaveImage", ["copy"], [conn("images", 18), widget("filename_prefix")]),
            node(20, "LoraLoader", ["detail.safetensors", 0.8, 1.0],
                 [conn("model", 7), conn("clip", 8), widget("lora_name"), widget("strength_model"), widget("strength_clip")]),
        ],
        "links": [
            [1, 4, 0, 12, 0, "MODEL"], [2, 10, 0, 12, 1, "IMAGE"], [3, 12, 0, 15, 0, "MODEL"], [4, 13, 0, 15, 1, "IMAGE"],
            [5, 15, 0, 16, 0, "MODEL"], [6, 14, 0, 16, 1, "IMAGE"], [7, 16, 0, 20, 0, "MODEL"], [8, 4, 1, 20, 1, "CLIP"],
            [9, 20, 0, 3, 0, "MODEL"], [10, 6, 0, 3, 1, "CONDITIONING"], [11, 7, 0, 3, 2, "CONDITIONING"],
            [12, 5, 0, 3, 3, "LATENT"], [13, 4, 1, 6, 0, "CLIP"], [14, 4, 1, 7, 0, "CLIP"], [15, 3, 0, 8, 0, "LATENT"],
            [16, 4, 2, 8, 1, "VAE"], [17, 8, 0, 9, 0, "IMAGE"], [18, 8, 0, 17, 0, "IMAGE"],
        ],
        "groups": [],
        "config": {},
        "extra": {"ds": {"scale": 1, "offset": [0, 0]}, "ue_links": [], "0246.VERSION": [0, 0, 4]},
        "version": 0.4,
    }


#: 一张保存的**图生视频**工作流(API 格式也能存进 workflows/ —— 用户「导出 (API)」后存的就是这样)。
WAN_API: dict[str, Any] = {
    "3": {"class_type": "KSampler", "inputs": {"seed": 1, "steps": 20, "cfg": 5.0, "sampler_name": "euler",
                                                "scheduler": "normal", "denoise": 1.0, "model": ["4", 0],
                                                "positive": ["20", 0], "negative": ["20", 1], "latent_image": ["20", 2]}},
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "v1-5.ckpt"}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "sea", "clip": ["4", 1]}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "bad", "clip": ["4", 1]}},
    "12": {"class_type": "LoadImage", "inputs": {"image": "start.png"}},
    "20": {"class_type": "WanImageToVideo", "inputs": {"positive": ["6", 0], "negative": ["7", 0], "vae": ["4", 2],
                                                       "width": 832, "height": 480, "length": 81, "batch_size": 1,
                                                       "start_image": ["12", 0]}},
    "30": {"class_type": "VHS_VideoCombine", "inputs": {"images": ["3", 0], "frame_rate": 16}},
}


#: 一张**放大**工作流:没有提示词、没有画布,读一张图 → 放大模型 → 存下来。
UPSCALE_API: dict[str, Any] = {
    "1": {"class_type": "LoadImage", "inputs": {"image": "example.png"}},
    "2": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "4x-UltraSharp.pth"}},
    "3": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["2", 0], "image": ["1", 0]}},
    "4": {"class_type": "SaveImage", "inputs": {"images": ["3", 0], "filename_prefix": "up"}},
    "5": {"class_type": "PreviewImage", "inputs": {"images": ["1", 0]}},
}

#: 一张 **ControlNet** 出图工作流:读一张图 → Canny 线稿 → 控制采样 → 存下来;线稿接了一个 PreviewImage
#: (看一眼预处理得对不对)。存下来的只有 SaveImage 那一张 —— 它和生成模型 controlnet.json 是同一件事。
CONTROLNET_API: dict[str, Any] = {
    "3": {"class_type": "KSampler", "inputs": {"seed": 5, "steps": 20, "cfg": 7.0, "sampler_name": "euler",
                                                "scheduler": "normal", "denoise": 1.0, "model": ["4", 0],
                                                "positive": ["21", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "v1-5.ckpt"}},
    "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a house", "clip": ["4", 1]}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry", "clip": ["4", 1]}},
    "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
    "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "cn"}},
    "11": {"class_type": "LoadImage", "inputs": {"image": "pose.png"}},
    "12": {"class_type": "Canny", "inputs": {"image": ["11", 0], "low_threshold": 0.4, "high_threshold": 0.8}},
    "13": {"class_type": "PreviewImage", "inputs": {"images": ["12", 0]}},
    "20": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": "control_canny.safetensors"}},
    "21": {"class_type": "ControlNetApply", "inputs": {"conditioning": ["6", 0], "control_net": ["20", 0],
                                                       "image": ["12", 0], "strength": 1.0}},
}

#: 用户那张 **inpainting.json** 的样子(转成 API 图之后):第一遍文生图的 KSampler 被静音了(mode 2,不进图),
#: 它前后的 EmptyLatentImage(#8)、VAEDecode(#10,samples 那根线随静音断了)、PreviewImage(#11)还在,
#: 另有一个没接到任何地方的 CLIPTextEncode(#6)。真正出图的是:读进来的图 → VAEEncode → SetLatentNoiseMask
#: (拿 LoadImage 的 alpha 当蒙版)→ KSampler → VAEDecode → PreviewImage(#16)。
INPAINT_MUTED_FIRST_PASS_API: dict[str, Any] = {
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base.safetensors"}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a beautiful girl, detailed face", "clip": ["4", 1]}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "text", "clip": ["4", 1]}},
    "8": {"class_type": "EmptyLatentImage", "inputs": {"width": 1280, "height": 1920, "batch_size": 1}},
    "10": {"class_type": "VAEDecode", "inputs": {"vae": ["4", 2]}},
    "11": {"class_type": "PreviewImage", "inputs": {"images": ["10", 0]}},
    "13": {"class_type": "KSampler", "inputs": {"seed": 1, "steps": 20, "cfg": 7.5, "sampler_name": "euler",
                                                 "scheduler": "normal", "denoise": 0.8, "model": ["4", 0],
                                                 "positive": ["14", 0], "negative": ["7", 0], "latent_image": ["24", 0]}},
    "14": {"class_type": "CLIPTextEncode", "inputs": {"text": "a red lantern", "clip": ["4", 1]}},
    "15": {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["4", 2]}},
    "16": {"class_type": "PreviewImage", "inputs": {"images": ["15", 0]}},
    "21": {"class_type": "LoadImage", "inputs": {"image": "painted-masked.png"}},
    "23": {"class_type": "VAEEncode", "inputs": {"pixels": ["21", 0], "vae": ["4", 2]}},
    "24": {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["23", 0], "mask": ["21", 1]}},
}
#: 上面那张图要的、OBJECT_INFO 里没有的节点定义。
INPAINT_NODE_INFO: dict[str, Any] = {
    "SetLatentNoiseMask": {"input": {"required": {"samples": ["LATENT"], "mask": ["MASK"]}}, "output": ["LATENT"]},
}


def _ml() -> list[Any]:
    return ["STRING", {"multiline": True}]


#: 没有 ComfyUI 认得的采样器的那几类视频图用到的节点(子集),输入名、类型照真实的 /object_info:
#:
#: - ComfyUI 自带的**合作方 API 节点**(comfy_api_nodes):提示词是节点自己的一格多行字符串 —— MiniMax / 海螺叫
#:   `prompt_text`,Kling、Veo 叫 `prompt`,反向提示词 `negative_prompt` 和它在同一个节点上;首帧叫
#:   `first_frame_image`(海螺)、`start_frame`(Kling)、`first_frame` / `last_frame`(Veo)、`image`(MiniMax 图生视频);
#: - kijai 的 **WanVideoWrapper**:采样器是 WanVideoSampler,正反两句都写在 WanVideoTextEncode 上;
#: - 本地的 **MiniMax H3**:BasicGuider 的条件来自 MiniMaxH3ImageToVideo,提示词是它的 `prompt`;
#: - **CreateVideo** 只是把帧和声音合成一段视频交给下游,不是输出节点 —— 存下来的是后面的 SaveVideo。
VIDEO_NODE_INFO: dict[str, Any] = {
    "MinimaxTextToVideoNode": {"input": {"required": {"prompt_text": _ml(), "model": [["T2V-01", "T2V-01-Director"]]},
                                         "optional": {"seed": ["INT", {"default": 0, "min": 0}]}},
                               "output": ["VIDEO"]},
    "MinimaxImageToVideoNode": {"input": {"required": {"image": ["IMAGE"], "prompt_text": _ml(),
                                                       "model": [["I2V-01", "I2V-01-live"]]},
                                          "optional": {"seed": ["INT", {"default": 0, "min": 0}]}},
                                "output": ["VIDEO"]},
    "MinimaxHailuoVideoNode": {"input": {"required": {"prompt_text": _ml()},
                                         "optional": {"seed": ["INT", {"default": 0, "min": 0}],
                                                      "first_frame_image": ["IMAGE"],
                                                      "prompt_optimizer": ["BOOLEAN", {"default": True}],
                                                      "duration": [[6, 10]], "resolution": [["768P", "1080P"]]}},
                               "output": ["VIDEO"]},
    "KlingImage2VideoNode": {"input": {"required": {
        "start_frame": ["IMAGE"], "prompt": _ml(), "negative_prompt": _ml(), "model_name": [["kling-v2-1", "kling-v1-6"]],
        "cfg_scale": ["FLOAT", {"default": 0.8, "min": 0.0, "max": 1.0}], "mode": [["std", "pro"]],
        "aspect_ratio": [["16:9", "9:16", "1:1"]], "duration": [["5", "10"]]}}, "output": ["VIDEO", "STRING", "STRING"]},
    "Veo3FirstLastFrameNode": {"input": {"required": {
        "prompt": _ml(), "negative_prompt": _ml(), "resolution": [["720p", "1080p"]], "aspect_ratio": [["16:9", "9:16"]],
        "duration": ["INT", {"default": 8, "min": 4, "max": 8}], "seed": ["INT", {"default": 0, "min": 0}],
        "first_frame": ["IMAGE"], "last_frame": ["IMAGE"], "model": [["veo-3.1-generate", "veo-3.1-fast-generate"]],
        "generate_audio": ["BOOLEAN", {"default": True}]}}, "output": ["VIDEO"]},
    "SaveVideo": {"input": {"required": {"video": ["VIDEO"], "filename_prefix": ["STRING", {"default": "video/ComfyUI"}],
                                         "format": [["auto", "mp4"]], "codec": [["auto", "h264"]]}},
                  "output_node": True, "output": ["VIDEO"]},
    "CreateVideo": {"input": {"required": {"images": ["IMAGE"], "fps": ["FLOAT", {"default": 30.0}]},
                              "optional": {"audio": ["AUDIO"]}},
                    "output_node": False, "output": ["VIDEO"]},
    "WanVideoTextEncode": {"input": {"required": {"positive_prompt": _ml(), "negative_prompt": _ml()},
                                     "optional": {"t5": ["WANTEXTENCODER"]}}, "output": ["WANVIDEOTEXTEMBEDS"]},
    "WanVideoImageToVideoEncode": {"input": {"required": {
        "width": ["INT", {"default": 832, "min": 64}], "height": ["INT", {"default": 480, "min": 64}],
        "num_frames": ["INT", {"default": 81, "min": 1}]},
        "optional": {"vae": ["WANVAE"], "start_image": ["IMAGE"], "end_image": ["IMAGE"]}}, "output": ["WANVIDIMAGE_EMBEDS"]},
    "WanVideoSampler": {"input": {"required": {
        "model": ["WANVIDEOMODEL"], "image_embeds": ["WANVIDIMAGE_EMBEDS"], "steps": ["INT", {"default": 30, "min": 1}],
        "cfg": ["FLOAT", {"default": 6.0, "min": 0.0, "max": 30.0}], "seed": ["INT", {"default": 0, "min": 0}]},
        "optional": {"text_embeds": ["WANVIDEOTEXTEMBEDS"]}}, "output": ["LATENT", "LATENT"]},
    "WanVideoDecode": {"input": {"required": {"vae": ["WANVAE"], "samples": ["LATENT"]}}, "output": ["IMAGE"]},
    "MiniMaxH3ImageToVideo": {"input": {"required": {
        "clip": ["CLIP"], "vae": ["VAE"], "prompt": ["STRING", {"multiline": True, "dynamicPrompts": True}],
        "width": ["INT", {"default": 1344, "min": 32, "step": 32}], "height": ["INT", {"default": 768, "min": 32, "step": 32}],
        "length": ["INT", {"default": 124, "min": 5, "step": 17}]},
        "optional": {"first_frame": ["IMAGE"], "last_frame": ["IMAGE"]}}, "output": ["CONDITIONING", "LATENT"]},
    "MiniMaxH3ReferenceToVideo": {"input": {"required": {
        "clip": ["CLIP"], "prompt": _ml(), "width": ["INT", {"default": 1344}], "height": ["INT", {"default": 768}],
        "length": ["INT", {"default": 124}]}}, "output": ["CONDITIONING", "LATENT"]},
    "UNETLoader": {"input": {"required": {"unet_name": [["minimax_h3.safetensors"]], "weight_dtype": [["default", "fp8"]]}}},
    "CLIPLoader": {"input": {"required": {"clip_name": [["qwen3vl.safetensors"]], "type": [["minimax", "wan"]]}}},
    "VAELoader": {"input": {"required": {"vae_name": [["minimax_h3_vae.safetensors"]]}}},
    "BasicGuider": {"input": {"required": {"model": ["MODEL"], "conditioning": ["CONDITIONING"]}}},
    "RandomNoise": {"input": {"required": {"noise_seed": ["INT", {"default": 0, "min": 0,
                                                                  "control_after_generate": True}]}}},
    "KSamplerSelect": {"input": {"required": {"sampler_name": [["euler", "res_multistep"]]}}},
    "BasicScheduler": {"input": {"required": {"model": ["MODEL"], "scheduler": [["simple", "beta"]],
                                              "steps": ["INT", {"default": 20, "min": 1}],
                                              "denoise": ["FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0}]}}},
    "SamplerCustomAdvanced": {"input": {"required": {"noise": ["NOISE"], "guider": ["GUIDER"], "sampler": ["SAMPLER"],
                                                     "sigmas": ["SIGMAS"], "latent_image": ["LATENT"]}}},
}


def _api_video(node: str, class_type: str, inputs: dict[str, Any]) -> dict[str, Any]:
    """一张最小的视频 API 图:`node` 交出一段视频,SaveVideo 存下来。"""
    return {node: {"class_type": class_type, "inputs": inputs},
            "90": {"class_type": "SaveVideo", "inputs": {"video": [node, 0], "filename_prefix": "video/out"}}}


#: MiniMax 文生视频(API 节点):提示词是 `prompt_text`。
MINIMAX_T2V_API = _api_video("1", "MinimaxTextToVideoNode", {"prompt_text": "a goldfish", "model": "T2V-01", "seed": 3})
#: MiniMax 图生视频(API 节点):读一张图接到 `image` 上 —— 首帧。
MINIMAX_I2V_API = {
    **_api_video("1", "MinimaxImageToVideoNode", {"image": ["5", 0], "prompt_text": "it swims", "model": "I2V-01"}),
    "5": {"class_type": "LoadImage", "inputs": {"image": "fish.png"}},
}
#: 海螺:首帧叫 `first_frame_image`。
HAILUO_API = {
    **_api_video("1", "MinimaxHailuoVideoNode", {"prompt_text": "", "first_frame_image": ["5", 0], "duration": 6}),
    "5": {"class_type": "LoadImage", "inputs": {"image": "start.png"}},
}
#: Kling 图生视频:正反两句在同一个节点上,首帧叫 `start_frame`。
KLING_I2V_API = {
    **_api_video("1", "KlingImage2VideoNode", {"start_frame": ["5", 0], "prompt": "a dancer", "negative_prompt": "blur",
                                                "model_name": "kling-v2-1", "cfg_scale": 0.8, "mode": "std",
                                                "aspect_ratio": "16:9", "duration": "5"}),
    "5": {"class_type": "LoadImage", "inputs": {"image": "dancer.png"}},
}
#: Veo 首尾帧。
VEO_FLF_API = {
    **_api_video("1", "Veo3FirstLastFrameNode", {"prompt": "sunrise", "negative_prompt": "", "resolution": "720p",
                                                  "aspect_ratio": "16:9", "duration": 8, "seed": 1,
                                                  "first_frame": ["5", 0], "last_frame": ["6", 0],
                                                  "model": "veo-3.1-generate", "generate_audio": True}),
    "5": {"class_type": "LoadImage", "inputs": {"image": "a.png"}},
    "6": {"class_type": "LoadImage", "inputs": {"image": "b.png"}},
}
#: WanVideoWrapper 图生视频:WanVideoTextEncode(正反两句)→ WanVideoSampler → WanVideoDecode → VHS 合成。
WAN_WRAPPER_API: dict[str, Any] = {
    "11": {"class_type": "WanVideoTextEncode", "inputs": {"positive_prompt": "a koi pond", "negative_prompt": "ugly"}},
    "12": {"class_type": "LoadImage", "inputs": {"image": "pond.png"}},
    "13": {"class_type": "WanVideoImageToVideoEncode", "inputs": {"width": 832, "height": 480, "num_frames": 81,
                                                                  "start_image": ["12", 0]}},
    "14": {"class_type": "WanVideoSampler", "inputs": {"model": ["20", 0], "image_embeds": ["13", 0], "steps": 30,
                                                       "cfg": 6.0, "seed": 7, "text_embeds": ["11", 0]}},
    "15": {"class_type": "WanVideoDecode", "inputs": {"vae": ["21", 0], "samples": ["14", 0]}},
    "16": {"class_type": "VHS_VideoCombine", "inputs": {"images": ["15", 0], "frame_rate": 16}},
}

def subgraph_promoting(picked: str) -> dict[str, Any]:
    """一张图:加载 checkpoint 的节点包在子图里,带着官方模板那样的下载声明(模板默认的文件);它那一格接的是子图的输入口,
    子图节点上提升出来的那一格选的是 `picked`。子图节点的 `inputs` 是前端导出时压过的样子(没连线的 widget 口删掉了)。"""
    sub = "5d1e2f3a-0000-4000-8000-0000000000aa"
    return {
        "nodes": [{"id": 30, "type": sub, "inputs": [], "outputs": [{"name": "MODEL", "type": "MODEL", "links": []}],
                   "widgets_values": [picked]}],
        "links": [],
        "definitions": {"subgraphs": [{
            "id": sub, "name": "加载",
            "inputNode": {"id": -10, "bounding": [0, 0, 1, 1]}, "outputNode": {"id": -20, "bounding": [0, 0, 1, 1]},
            "inputs": [{"id": "i0", "name": "ckpt_name", "type": "COMBO", "linkIds": [1]}],
            "outputs": [{"id": "o0", "name": "MODEL", "type": "MODEL", "linkIds": [2]}],
            "nodes": [{"id": 4, "type": "CheckpointLoaderSimple", "widgets_values": ["template_default.safetensors"],
                       "inputs": [{"name": "ckpt_name", "type": "COMBO", "widget": {"name": "ckpt_name"}, "link": 1}],
                       "properties": {"models": [{
                           "name": "template_default.safetensors", "directory": "checkpoints",
                           "url": "https://huggingface.co/Comfy-Org/x/resolve/main/template_default.safetensors"}]}}],
            "links": [{"id": 1, "origin_id": -10, "origin_slot": 0, "target_id": 4, "target_slot": 0, "type": "COMBO"},
                      {"id": 2, "origin_id": 4, "origin_slot": 0, "target_id": -20, "target_slot": 0, "type": "MODEL"}],
        }]},
    }


#: 本地 MiniMax H3 文生视频的那张图(照用户 ComfyUI 里的「video_minimax_h3_t2v.json」缩出来的):整条流程包在**子图**
#: 「Image to Video (MiniMax H3)」里,提示词是子图节点上提升出来的一格;子图里 BasicGuider 的条件来自
#: MiniMaxH3ImageToVideo(提示词就是它的 `prompt`),帧和声音由 CreateVideo 合成交出子图,外面的 SaveVideo 存下来。
#: 首帧 / 尾帧是子图的两个输入口,文生视频时空着。
MINIMAX_H3_SUBGRAPH = "4c314f31-ecda-4b08-ae98-faaba1bf613f"


def minimax_h3_ui(*, frames: bool = False) -> dict[str, Any]:
    """`frames`:外面接两张 LoadImage 到子图的首帧 / 尾帧口(图生视频的用法)。"""

    def sub_link(link_id: int, origin: int, origin_slot: int, target: int, target_slot: int, kind: str) -> dict[str, Any]:
        return {"id": link_id, "origin_id": origin, "origin_slot": origin_slot, "target_id": target,
                "target_slot": target_slot, "type": kind}

    loaders = [
        {"id": 201, "type": "LoadImage", "widgets_values": ["first.png", "image"], "inputs": [widget("image")],
         "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [301]}]},
        {"id": 202, "type": "LoadImage", "widgets_values": ["last.png", "image"], "inputs": [widget("image")],
         "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [302]}]},
    ] if frames else []
    return {
        "id": "8f6b0a52-6a0b-4c1e-9d55-1b2c3d4e5f60",
        "nodes": [
            {"id": 92, "type": "SaveVideo", "widgets_values": ["video/MiniMax_H3", "auto", "auto"],
             "inputs": [{"name": "video", "type": "VIDEO", "link": 194}, widget("filename_prefix"), widget("format"),
                        widget("codec")]},
            {"id": 105, "type": MINIMAX_H3_SUBGRAPH,
             "inputs": [{"name": "first_frame", "type": "IMAGE", "link": 301 if frames else None},
                        {"name": "last_frame", "type": "IMAGE", "link": 302 if frames else None},
                        {"name": "prompt", "type": "STRING", "widget": {"name": "prompt"}, "link": None},
                        {"name": "width", "type": "INT", "widget": {"name": "width"}, "link": None},
                        {"name": "height", "type": "INT", "widget": {"name": "height"}, "link": None},
                        {"name": "noise_seed", "type": "INT", "widget": {"name": "noise_seed"}, "link": None}],
             "outputs": [{"name": "VIDEO", "type": "VIDEO", "links": [194]}],
             "widgets_values": ["Realistic live-action cinematic look", 1344, 768, 556589502035082]},
            {"id": 116, "type": "MarkdownNote", "widgets_values": ["## MiniMax H3"], "inputs": []},
            *loaders,
        ],
        "links": [[194, 105, 0, 92, 0, "VIDEO"],
                  *([[301, 201, 0, 105, 0, "IMAGE"], [302, 202, 0, 105, 1, "IMAGE"]] if frames else [])],
        "definitions": {"subgraphs": [{
            "id": MINIMAX_H3_SUBGRAPH, "name": "Image to Video (MiniMax H3)",
            "inputNode": {"id": -10, "bounding": [0, 0, 1, 1]}, "outputNode": {"id": -20, "bounding": [0, 0, 1, 1]},
            "inputs": [{"id": "i0", "name": "first_frame", "type": "IMAGE", "linkIds": [195]},
                       {"id": "i1", "name": "last_frame", "type": "IMAGE", "linkIds": [196]},
                       {"id": "i2", "name": "prompt", "type": "STRING", "linkIds": [197]},
                       {"id": "i3", "name": "width", "type": "INT", "linkIds": [200]},
                       {"id": "i4", "name": "height", "type": "INT", "linkIds": [201]},
                       {"id": "i5", "name": "noise_seed", "type": "INT", "linkIds": [207]}],
            "outputs": [{"id": "o0", "name": "VIDEO", "type": "VIDEO", "linkIds": [168]}],
            "nodes": [
                {"id": 6, "type": "UNETLoader", "widgets_values": ["minimax_h3.safetensors", "default"],
                 "inputs": [widget("unet_name"), widget("weight_dtype")]},
                {"id": 11, "type": "VAELoader", "widgets_values": ["minimax_h3_vae.safetensors"],
                 "inputs": [widget("vae_name")]},
                {"id": 13, "type": "CLIPLoader", "widgets_values": ["qwen3vl.safetensors", "minimax"],
                 "inputs": [widget("clip_name"), widget("type")]},
                {"id": 104, "type": "MiniMaxH3ImageToVideo", "widgets_values": ["Vaporwave title sequence", 1344, 768, 124],
                 "inputs": [{"name": "clip", "type": "CLIP", "link": 189}, {"name": "vae", "type": "VAE", "link": 190},
                            {"name": "first_frame", "type": "IMAGE", "link": 195},
                            {"name": "last_frame", "type": "IMAGE", "link": 196},
                            {"name": "prompt", "type": "STRING", "widget": {"name": "prompt"}, "link": 197},
                            {"name": "width", "type": "INT", "widget": {"name": "width"}, "link": 200},
                            {"name": "height", "type": "INT", "widget": {"name": "height"}, "link": 201},
                            {"name": "length", "type": "INT", "widget": {"name": "length"}, "link": None}]},
                {"id": 15, "type": "RandomNoise", "widgets_values": [1, "randomize"],
                 "inputs": [{"name": "noise_seed", "type": "INT", "widget": {"name": "noise_seed"}, "link": 207}]},
                {"id": 16, "type": "BasicGuider", "inputs": [{"name": "model", "type": "MODEL", "link": 193},
                                                             {"name": "conditioning", "type": "CONDITIONING", "link": 187}]},
                {"id": 17, "type": "KSamplerSelect", "widgets_values": ["res_multistep"], "inputs": [widget("sampler_name")]},
                {"id": 9, "type": "BasicScheduler", "widgets_values": ["simple", 20, 1],
                 "inputs": [{"name": "model", "type": "MODEL", "link": 5}, widget("scheduler"), widget("steps"),
                            widget("denoise")]},
                {"id": 14, "type": "SamplerCustomAdvanced",
                 "inputs": [{"name": "noise", "type": "NOISE", "link": 40}, {"name": "guider", "type": "GUIDER", "link": 12},
                            {"name": "sampler", "type": "SAMPLER", "link": 16}, {"name": "sigmas", "type": "SIGMAS", "link": 18},
                            {"name": "latent_image", "type": "LATENT", "link": 188}]},
                {"id": 10, "type": "VAEDecode", "inputs": [{"name": "samples", "type": "LATENT", "link": 225},
                                                           {"name": "vae", "type": "VAE", "link": 8}]},
                {"id": 91, "type": "CreateVideo", "widgets_values": [24],
                 "inputs": [{"name": "images", "type": "IMAGE", "link": 167}, widget("fps")]},
            ],
            "links": [
                sub_link(5, 6, 0, 9, 0, "MODEL"), sub_link(8, 11, 0, 10, 1, "VAE"), sub_link(12, 16, 0, 14, 1, "GUIDER"),
                sub_link(16, 17, 0, 14, 2, "SAMPLER"), sub_link(18, 9, 0, 14, 3, "SIGMAS"), sub_link(40, 15, 0, 14, 0, "NOISE"),
                sub_link(167, 10, 0, 91, 0, "IMAGE"), sub_link(168, 91, 0, -20, 0, "VIDEO"),
                sub_link(187, 104, 0, 16, 1, "CONDITIONING"), sub_link(188, 104, 1, 14, 4, "LATENT"),
                sub_link(189, 13, 0, 104, 0, "CLIP"), sub_link(190, 11, 0, 104, 1, "VAE"),
                sub_link(193, 6, 0, 16, 0, "MODEL"), sub_link(195, -10, 0, 104, 2, "IMAGE"),
                sub_link(196, -10, 1, 104, 3, "IMAGE"), sub_link(197, -10, 2, 104, 4, "STRING"),
                sub_link(200, -10, 3, 104, 5, "INT"), sub_link(201, -10, 4, 104, 6, "INT"),
                sub_link(207, -10, 5, 15, 0, "INT"), sub_link(225, 14, 0, 10, 0, "LATENT"),
            ],
        }]},
    }


#: 「多参考生视频」那张(照「YZ金鱼-MiniMax+H3-多参考生视频」缩出来的):提示词写在一个自定义的 `Text` 节点上,
#: 连进 MiniMaxH3ReferenceToVideo 的 `prompt`;参考图、参考视频、参考音频接在 `ref_images.*` / `ref_videos.*` /
#: `ref_audios.*` 上;存下来的是 VHS 合成,另一个关了 save_output 的合成只是预览。
MINIMAX_H3_REFERENCE_API: dict[str, Any] = {
    "16": {"class_type": "BasicGuider", "inputs": {"model": ["6", 0], "conditioning": ["265", 0]}},
    "14": {"class_type": "SamplerCustomAdvanced", "inputs": {"guider": ["16", 0], "latent_image": ["265", 1]}},
    "6": {"class_type": "UNETLoader", "inputs": {"unet_name": "minimax_h3.safetensors", "weight_dtype": "default"}},
    "263": {"class_type": "Text", "inputs": {"text": "<Subject 1> walks into the clinic"}},
    "265": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {"prompt": ["263", 0], "width": 1344, "height": 768,
                                                                  "length": 124, "ref_images.ref_image_0": ["51", 0],
                                                                  "ref_videos.ref_video_0": ["27", 0],
                                                                  "ref_audios.ref_audio_0": ["48", 0]}},
    "51": {"class_type": "LoadImage", "inputs": {"image": "doctor.png"}},
    "27": {"class_type": "VHS_LoadVideo", "inputs": {"video": "", "force_rate": 0}},
    "48": {"class_type": "LoadAudio", "inputs": {"audio": "voice.wav"}},
    "116": {"class_type": "VAEDecode", "inputs": {"samples": ["14", 0]}},
    "214": {"class_type": "VHS_VideoCombine", "inputs": {"images": ["116", 0], "frame_rate": 24, "save_output": True}},
    "264": {"class_type": "VHS_VideoCombine", "inputs": {"images": ["116", 0], "frame_rate": 24, "save_output": False}},
}

#: 一张**两个保存节点**的出图工作流:一张原图(「原图」)、一张放大过的(「高清」),画布一次出两张(batch_size 2)。
#: 一次运行存下来的是 2 个节点 × 2 张 = 4 张。
TWO_SAVES_API: dict[str, Any] = {
    "3": {"class_type": "KSampler", "inputs": {"seed": 5, "steps": 20, "cfg": 7.0, "sampler_name": "euler",
                                                "scheduler": "normal", "denoise": 1.0, "model": ["4", 0],
                                                "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "v1-5.ckpt"}},
    "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 2}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a cat", "clip": ["4", 1]}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry", "clip": ["4", 1]}},
    "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
    "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "base"}, "_meta": {"title": "原图"}},
    "10": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "4x-UltraSharp.pth"}},
    "11": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["10", 0], "image": ["8", 0]}},
    "12": {"class_type": "SaveImage", "inputs": {"images": ["11", 0], "filename_prefix": "hd"}, "_meta": {"title": "高清"}},
}

#: 只接了**预览**节点的工作流:三个 PreviewImage 看的是同一张图,都没改标题。谁也不是谁的中间一步,生成交回的就是
#: 这三份预览。(维护者 ComfyUI 上真正的「古风女孩1」是两遍出图,见 `two_pass_hand_depth`。)
PREVIEWS_ONLY_API: dict[str, Any] = {
    **{key: value for key, value in TWO_SAVES_API.items() if key not in ("9", "10", "11", "12")},
    "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
    "13": {"class_type": "PreviewImage", "inputs": {"images": ["8", 0]}},
    "17": {"class_type": "PreviewImage", "inputs": {"images": ["8", 0]}},
    "18": {"class_type": "PreviewImage", "inputs": {"images": ["8", 0]}},
}

#: 两个**视频**保存节点的视频工作流(一段原速、一段补帧之后的):一次交回两段。
TWO_VIDEOS_API: dict[str, Any] = {
    **WAN_API,
    "30": {"class_type": "VHS_VideoCombine", "inputs": {"images": ["3", 0], "frame_rate": 16}, "_meta": {"title": "原速"}},
    "31": {"class_type": "VHS_VideoCombine", "inputs": {"images": ["3", 0], "frame_rate": 32}, "_meta": {"title": "补帧"}},
}

#: 从真实工作流脱敏来的夹具(模型名、提示词、种子、画布位置换掉了,图的结构原样):`<名字>.workflow.json` 是 ComfyUI
#: 存下来的界面格式,`<名字>.object_info.json` 是它用到的那几类节点的定义(下拉里只留夹具里用的那一项)。
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "comfyui"


def fixture_workflow(name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """(界面格式的工作流, 它用到的节点定义)。"""
    workflow = json.loads((FIXTURES / f"{name}.workflow.json").read_text(encoding="utf-8"))
    object_info = json.loads((FIXTURES / f"{name}.object_info.json").read_text(encoding="utf-8"))
    return workflow, object_info


#: 维护者 ComfyUI 上的「古风女孩1」(2026-10,1.9.1 时报的「张数 1 出了 3 张,一张几乎全黑」):两遍出图修手。
#: 第一遍 KSampler #5 → VAEDecode #6 → PreviewImage #8;MeshGraphormer #10 从第一遍的图里算出**手部深度图**
#: → PreviewImage #18(没认出手时整张是黑的),同时经 ControlNetApplyAdvanced #11 控制第二遍 KSampler #14
#: → VAEDecode #16 → PreviewImage #17(最终结果)。三个预览节点都没改标题。
TWO_PASS_HAND_DEPTH = "two_pass_hand_depth"


def comfyui_grants() -> dict[str, bool]:
    """随应用发的 ComfyUI 插件声明的全部权限,全都授予 —— 测试里接连接时用(照清单读,清单改了这里跟着变)。"""
    manifest = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui" / "mosael.plugin.json"
    return {permission: True for permission in json.loads(manifest.read_text(encoding="utf-8"))["permissions"]}


#: Manager 的安全策略拒绝装模型时写进日志的那句(原文,V4.2.1 的 SECURITY_MESSAGE_MIDDLE_P)。
MANAGER_POLICY_MESSAGE = (
    "ERROR: To use this action, security_level must be `normal or below`, and network_mode must be set to "
    "`personal_cloud`. Please contact the administrator.\nReference: https://github.com/ltdrdata/ComfyUI-Manager#security-policy"
)
WEBP = b"RIFF\x1a\x00\x00\x00WEBPVP8L\x0d\x00\x00\x00/\x00\x00\x00\x10\x07\x10\x11\x11\x88\x88\xfe\x07\x00"

#: 模型目录(`/models` 与 `/models/<目录>`)。
MODEL_FOLDERS: dict[str, list[str]] = {
    "checkpoints": ["sd_xl_base.safetensors", "v1-5.ckpt"],
    "loras": ["detail.safetensors"],
    "upscale_models": ["4x-UltraSharp.pth"],
    "vae": [],
    "custom_nodes": [],
}

SYSTEM_STATS: dict[str, Any] = {
    "system": {"os": "posix", "python_version": "3.12.4", "comfyui_version": "0.3.60",
               "pytorch_version": "2.7.1+cu128", "ram_total": 64 * 1024 ** 3, "ram_free": 40 * 1024 ** 3},
    "devices": [{"name": "cuda:0 NVIDIA GeForce RTX 4090 : cudaMallocAsync", "type": "cuda", "index": 0,
                 "vram_total": 24 * 1024 ** 3, "vram_free": 20 * 1024 ** 3}],
}


@dataclass
class State:
    workflows: dict[str, Any] = field(default_factory=lambda: {"portrait.json": PORTRAIT_UI, "video/wan.json": WAN_API})
    object_info: dict[str, Any] = field(default_factory=lambda: json.loads(json.dumps(OBJECT_INFO)))
    #: prompt_id → history 条目。提交时按 `outcome` 生成;None = 永远跑不完(测取消)。
    history: dict[str, Any] = field(default_factory=dict)
    outcome: str = "success"  # success | error | never | video
    #: 一次一次提交各自的结果(按先后取,取完了用 `outcome`):测「循环提交 N 次,其中一次失败」。
    outcomes: list[str] = field(default_factory=list)
    #: outcome == "error" 时 ComfyUI 说的是哪一类节点、什么原话(WebSocket 和历史里是同一句)。
    error_node: str = "KSampler"
    error_message: str = "CUDA out of memory"
    reject: dict[str, Any] | None = None
    #: 一部分输出节点校验不过、另一部分过了:ComfyUI 照样排上(回 200 和任务号),只跑过了的那几个,
    #: 校验不过的写在回包的 node_errors 里。任务先进排队。
    node_errors: dict[str, Any] | None = None
    running: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    uploads: list[tuple[str, bytes]] = field(default_factory=list)
    calls: list[tuple[str, str, Any]] = field(default_factory=list)
    websocket: bool = False
    #: 放在要登录的反向代理后面:每个请求(含 WebSocket 握手)都得带这个 Authorization 头,否则 401。
    authorization: str | None = None
    #: WebSocket 在提交之后被对面**重置**(ComfyUI 重启、网络抖一下、代理掐线):插件该退回轮询。
    websocket_reset: bool = False
    submitted: threading.Event = field(default_factory=threading.Event)
    next_id: int = 0
    #: 老版本 ComfyUI 没有 `/models`。
    models_api: bool = True
    model_folders: dict[str, list[str]] = field(default_factory=lambda: json.loads(json.dumps(MODEL_FOLDERS)))
    #: 这一次提交跑完时的产出;None = 按 `outcome` 给默认的那一份。
    outputs: dict[str, Any] | None = None
    #: 模型库(`/experiment/models*`,0.3.x 起有):每个目录在磁盘上的位置(测「和 Mosael 在同一台机器上」时指向临时
    #: 目录)、每个文件的大小(键是「目录/名字」)、文件头里的元数据、哪几个有预览图。
    experiment_models: bool = True
    folder_paths: dict[str, list[str]] = field(default_factory=dict)
    model_sizes: dict[str, int] = field(default_factory=dict)
    model_metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    model_previews: set[str] = field(default_factory=set)
    #: ComfyUI-Custom-Scripts 的 `/pysssss/view/{目录/名字}`(模型库按段读文件头):`range` = 装了、认 Range(回 206);
    #: `missing` = 没装(404);`ignore_range` = 不认 Range、回 200 把整个文件发过来。文件的字节在 `model_bytes`(键是
    #: 「目录/名字」);`range_bytes_sent` 记下 ignore_range 时实际发出去了多少(对面读完头就该挂断)。
    pysssss: str = "range"
    #: 装了 pysssss 时 `/extensions` 里列的它的前端脚本(betterCombos.js 和 /pysssss/save、/pysssss/view 是同一个模块,
    #: modelInfo.js 和 /pysssss/metadata 是同一个);删掉哪个就是那条路没有
    pysssss_scripts: tuple[str, ...] = ("betterCombos.js", "modelInfo.js")
    #: 按哈希找时那台机器算出的 SHA256(键是「目录/名字」);没写的按 model_bytes(再没有按键本身)算
    model_hashes: dict[str, str] = field(default_factory=dict)
    #: 算过哈希的文件(「目录/名字」)—— 测「一次一个、不重复算」
    hashed: list[str] = field(default_factory=list)
    #: 经 /pysssss/save 写到模型旁边的预览图:「目录/名字」→ (扩展名, 字节)
    saved_previews: dict[str, tuple[str, bytes]] = field(default_factory=dict)
    #: 每次 /upload/image 带的表单字段(type、subfolder、overwrite)
    upload_fields: list[dict[str, str]] = field(default_factory=list)
    model_bytes: dict[str, bytes] = field(default_factory=dict)
    range_bytes_sent: int = 0
    #: 每次读文件的 (目录/名字, Range 头)
    range_requests: list[tuple[str, str]] = field(default_factory=list)
    #: ComfyUI-Manager:None = 没装,否则是 `/v2/manager/version` 回的版本。`manager_outcome`:success(真的把文件
    #: 加进那个目录)| policy(安全策略拒绝:历史里只记 failed,原因只在日志里 —— 和 V4.2.1 一样)| error。
    manager: str | None = None
    manager_outcome: str = "success"
    manager_tasks: list[dict[str, Any]] = field(default_factory=list)
    manager_history: dict[str, Any] = field(default_factory=dict)
    log_entries: list[dict[str, str]] = field(default_factory=list)
    #: workflows/ 以外的 userdata(回收目录 `.mosael-trash/…`):键是相对用户目录的路径。
    userdata: dict[str, Any] = field(default_factory=dict)
    #: 每张工作流的改动时间(毫秒,和 ComfyUI 0.38 的 full_info 一样);没写过的是 1。每写一次往后走一格(`touch`),
    #: 测 `annotate` 带着读到时的改动时间、文件在这之间被改过就不写。
    workflow_modified: dict[str, int] = field(default_factory=dict)
    clock: int = 1791000000000
    #: Manager 的节点映射(`/v2/customnode/getmappings`):包 → [节点类型…, 附加信息];已装的包(`/v2/customnode/installed`)。
    manager_mappings: dict[str, Any] = field(default_factory=dict)
    manager_installed: dict[str, Any] = field(default_factory=dict)
    #: Manager 让不让重启(`/v2/manager/reboot`,安全等级 middle);重启之后 `/system_stats` 连着几次答不上(停下了)。
    manager_reboot_allowed: bool = True
    reboot_down_polls: int = 0
    down_left: int = 0
    #: 别的静态地址(测「链接指着一个网页」):路径 → (Content-Type, 正文)。
    static: dict[str, tuple[str, bytes]] = field(default_factory=dict)
    #: 用户目录里的目录(相对用户目录,如 `workflows/草稿`)。有文件的目录由文件路径推出来;这里记的是**写文件、移动时
    #: 建出来的**(os.makedirs)—— 里面的东西挪走以后目录还在,空目录只在这里。
    dirs: set[str] = field(default_factory=set)
    #: 老版本 ComfyUI 没有 `/api/v2/userdata`(列不出空目录)。
    userdata_v2: bool = True
    #: 磁盘不分大小写(那台 ComfyUI 在 Windows 上;macOS 默认也是):`Video` 和 `video` 是同一个,「目标已存在」照这个判。
    case_insensitive: bool = False

    def userdata_get(self, path: str) -> Any:
        if path.startswith("workflows/"):
            return self.workflows.get(path[len("workflows/"):])
        return self.userdata.get(path)

    def userdata_put(self, path: str, value: Any) -> None:
        self.makedirs(path)
        if path.startswith("workflows/"):
            self.workflows[path[len("workflows/"):]] = value
            self.touch(path[len("workflows/"):])
        else:
            self.userdata[path] = value

    def files(self) -> dict[str, Any]:
        """用户目录里的全部文件(相对用户目录)。"""
        return {**{f"workflows/{name}": value for name, value in self.workflows.items()}, **self.userdata}

    def all_dirs(self) -> set[str]:
        """全部目录:建出来的和每个文件所在的,连同它们的各级父目录。"""
        found: set[str] = set()
        for parts in [one.split("/") for one in self.dirs] + [name.split("/")[:-1] for name in self.files()]:
            found.update("/".join(parts[:depth]) for depth in range(1, len(parts) + 1))
        return found

    def makedirs(self, path: str) -> None:
        """写一份 / 挪一份之前 ComfyUI 建它的父目录(get_request_user_filepath 的 os.makedirs)。"""
        parts = path.split("/")[:-1]
        self.dirs.update("/".join(parts[:depth]) for depth in range(1, len(parts) + 1))

    def is_dir(self, path: str) -> bool:
        return path in self.all_dirs()

    def exists(self, path: str) -> bool:
        """`os.path.exists`:文件或目录;不分大小写的磁盘上 `Video` 也算 `video`。"""
        if not self.case_insensitive:
            return path in self.files() or self.is_dir(path)
        lowered = path.lower()
        return any(one.lower() == lowered for one in [*self.files(), *self.all_dirs()])

    def move_dir(self, source: str, dest: str) -> None:
        """`shutil.move` 一个目录:里面的文件、子目录连同它自己一起换上新的前缀。"""
        def moved(name: str) -> str:
            return dest + name[len(source):]

        for name in [one for one in self.files() if one.startswith(source + "/")]:
            value = self.userdata_pop(name)
            target = moved(name)
            if target.startswith("workflows/"):
                self.workflows[target[len("workflows/"):]] = value
            else:
                self.userdata[target] = value
        self.dirs = {moved(one) if one == source or one.startswith(source + "/") else one for one in self.dirs}
        self.dirs.add(dest)
        self.makedirs(dest)

    def touch(self, name: str) -> int:
        """这张工作流刚被存过(在 ComfyUI 里 Ctrl+S、别人改过):改动时间往后走一格。"""
        self.clock += 1234
        self.workflow_modified[name] = self.clock
        return self.clock

    def modified(self, name: str) -> int:
        return self.workflow_modified.get(name, 1)

    def userdata_pop(self, path: str) -> Any:
        if path.startswith("workflows/"):
            return self.workflows.pop(path[len("workflows/"):])
        return self.userdata.pop(path)

    def log(self, entry: dict[str, str]) -> None:
        """记一行日志。和 ComfyUI 一样只留最近 300 行(环形缓冲):行数到顶之后不再变,只能按时间认新旧。"""
        from datetime import datetime

        self.log_entries.append({"t": datetime.now().isoformat(), **entry})
        del self.log_entries[:-300]


class _Handler(BaseHTTPRequestHandler):
    server: "FakeComfyUI"

    def log_message(self, *args: Any) -> None:  # 安静
        return

    # --- 回包 -------------------------------------------------------------

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _model_bytes(self, key: str) -> None:
        """`/pysssss/view/{目录/名字}`:aiohttp 的 FileResponse 认 Range;`ignore_range` 时照样回 200、整个发(一块一块地,
        对面挂断就停,记下发了多少)。"""
        state = self.server.state
        wanted = self.headers.get("Range") or ""
        state.range_requests.append((key, wanted))
        body = state.model_bytes.get(key)
        if body is None:
            self._json({"error": "not found"}, 404)
            return
        found = re.fullmatch(r"bytes=(\d+)-(\d+)", wanted)
        if state.pysssss == "range" and found:
            start, end = int(found.group(1)), min(int(found.group(2)), len(body) - 1)
            if start >= len(body):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{len(body)}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            part = body[start:end + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(body)}")
            self.send_header("Content-Length", str(len(part)))
            self.end_headers()
            self.wfile.write(part)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            for at in range(0, len(body), 256 * 1024):
                self.wfile.write(body[at:at + 256 * 1024])
                self.wfile.flush()
                state.range_bytes_sent = at + len(body[at:at + 256 * 1024])
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _authorized(self) -> bool:
        wanted = self.server.state.authorization
        if wanted is None or self.headers.get("Authorization") == wanted:
            return True
        self._json({"error": "unauthorized"}, 401)
        return False

    # --- GET --------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 — http.server 的约定
        state = self.server.state
        parts = urlsplit(self.path)
        path, query = parts.path, parse_qs(parts.query)
        state.calls.append(("GET", path, query))
        if not self._authorized():
            return
        if path == "/ws":
            self._websocket(query.get("clientId", [""])[0])
            return
        if path in state.static:
            kind, body = state.static[path]
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/system_stats" and state.down_left > 0:
            state.down_left -= 1
            self._json({"error": "restarting"}, 503)
        elif path == "/object_info":
            self._json(state.object_info)
        elif path == "/api/v2/userdata" and state.userdata_v2:
            # 连目录一起列(os.walk,一层层走下去):`path` 相对用户目录;要列的目录不存在回 404
            base = (query.get("path") or [""])[0].strip("/")
            if base and not state.is_dir(base):
                self._json({"error": "Requested path not found"}, 404)
                return
            prefix = f"{base}/" if base else ""
            entries: list[dict[str, Any]] = [
                {"name": one.rsplit("/", 1)[-1], "path": one, "type": "directory"}
                for one in sorted(state.all_dirs()) if one.startswith(prefix)
            ]
            entries += [
                {"name": one.rsplit("/", 1)[-1], "path": one, "type": "file", "size": len(json.dumps(value)),
                 "modified": state.modified(one[len("workflows/"):]) / 1000}
                for one, value in sorted(state.files().items()) if one.startswith(prefix)
            ]
            self._json(entries)
        elif path == "/api/userdata" and query.get("dir") == ["workflows"] and not state.workflows:
            # 刚装好的 ComfyUI 还没存过工作流:workflows 目录不存在,ComfyUI 回 404 "Directory not found"
            self.send_response(404)
            self.send_header("Content-Length", "19")
            self.end_headers()
            self.wfile.write(b"Directory not found")
        elif path == "/api/userdata" and query.get("dir") == ["workflows"]:
            self._json([{"path": name, "size": len(json.dumps(graph)), "modified": state.modified(name)}
                        for name, graph in state.workflows.items()])
        elif path == "/api/userdata":
            prefix = (query.get("dir") or [""])[0].rstrip("/") + "/"
            found = [{"path": name[len(prefix):], "size": len(json.dumps(value)), "modified": 1791000000000}
                     for name, value in state.userdata.items() if name.startswith(prefix)]
            if not found:
                self._json({"error": "Directory not found"}, 404)
            else:
                self._json(found)
        elif path == "/v2/customnode/getmappings" and state.manager:
            self._json(state.manager_mappings)
        elif path == "/v2/customnode/installed" and state.manager:
            self._json(state.manager_installed)
        elif path == "/system_stats":
            self._json(SYSTEM_STATS)
        elif path == "/models" and state.models_api:
            self._json(list(state.model_folders))
        elif path.startswith("/models/") and state.models_api:
            folder = unquote(path[len("/models/"):])
            if folder in state.model_folders:
                self._json(state.model_folders[folder])
            else:
                self._json({"error": "not found"}, 404)
        elif path == "/experiment/models" and state.experiment_models:
            self._json([{"name": name, "folders": state.folder_paths.get(name) or [f"/srv/comfy/models/{name}"],
                         "extensions": [".safetensors", ".ckpt", ".pt", ".pth", ".bin"]}
                        for name in state.model_folders])
        elif path.startswith("/experiment/models/preview/") and state.experiment_models:
            folder, _index, name = unquote(path[len("/experiment/models/preview/"):]).split("/", 2)
            if f"{folder}/{name}" in state.model_previews:
                self.send_response(200)
                self.send_header("Content-Type", "image/webp")
                self.send_header("Content-Length", str(len(WEBP)))
                self.end_headers()
                self.wfile.write(WEBP)
            else:
                self._json({"error": "not found"}, 404)
        elif path.startswith("/experiment/models/") and state.experiment_models:
            folder = unquote(path[len("/experiment/models/"):])
            if folder not in state.model_folders:
                self._json({"error": "not found"}, 404)
            else:
                self._json([{"name": name, "pathIndex": 0, "modified": 1700000000.0 + index, "created": 1700000000.0,
                             "size": state.model_sizes.get(f"{folder}/{name}", 1000)}
                            for index, name in enumerate(state.model_folders[folder])])
        elif path.startswith("/pysssss/view/") and state.pysssss != "missing":
            self._model_bytes(unquote(path[len("/pysssss/view/"):]))
        elif path == "/extensions":
            scripts = state.pysssss_scripts if state.pysssss != "missing" else ()
            self._json(["/extensions/core/linkRenderMode.js",
                        *(f"/extensions/comfyui-custom-scripts/js/{name}" for name in scripts)])
        elif path.startswith("/pysssss/metadata/") and state.pysssss != "missing" and "modelInfo.js" in state.pysssss_scripts:
            key = unquote(path[len("/pysssss/metadata/"):])
            folder, _, name = key.partition("/")
            if name not in state.model_folders.get(folder, []):
                self._json({"error": "not found"}, 404)
                return
            state.hashed.append(key)
            digest = state.model_hashes.get(key) or hashlib.sha256(state.model_bytes.get(key, key.encode())).hexdigest()
            self._json({**(state.model_metadata.get(key) or {}), "pysssss.sha256": digest})
        elif path.startswith("/view_metadata/"):
            folder = unquote(path[len("/view_metadata/"):])
            name = query.get("filename", [""])[0]
            meta = state.model_metadata.get(f"{folder}/{name}")
            if not name.endswith(".safetensors") or name not in state.model_folders.get(folder, []) or meta is None:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self._json(meta)
        elif path == "/internal/logs/raw":
            self._json({"entries": state.log_entries, "size": {"cols": 120, "rows": 40}})
        elif path == "/v2/manager/version" and state.manager:
            body = state.manager.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/v2/manager/queue/history" and state.manager:
            ui_id = query.get("ui_id", [""])[0]
            entry = state.manager_history.get(ui_id)
            self._json({"history": entry} if entry else {"history": {}})
        elif path == "/v2/manager/queue/status" and state.manager:
            self._json({"total_count": 0, "done_count": len(state.manager_history), "in_progress_count": 0,
                        "pending_count": 0, "is_processing": False})
        elif path == "/history":
            items = list(state.history.items())
            limit = int(query.get("max_items", ["0"])[0] or 0)
            self._json(dict(items[-limit:] if limit else items))
        elif path.startswith("/api/userdata/"):
            name = unquote(path[len("/api/userdata/"):])
            found = state.userdata_get(name)
            if found is None:
                self._json({"error": "not found"}, 404)
            else:
                self._json(found)
        elif path.startswith("/history/"):
            prompt_id = path[len("/history/"):]
            entry = state.history.get(prompt_id)
            self._json({prompt_id: entry} if entry else {})
        elif path == "/queue":
            self._json({"queue_running": [[0, one] for one in state.running],
                        "queue_pending": [[1, one] for one in state.pending]})
        elif path == "/view":
            name = query.get("filename", [""])[0]
            body = b"mp4-bytes" if name.endswith(".mp4") else PNG
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._json({"error": "unknown"}, 404)

    # --- POST -------------------------------------------------------------

    def _userdata_write(self, path: str, query: dict[str, list[str]], raw: bytes) -> None:
        """`POST /api/userdata/{file}`(写)和 `POST /api/userdata/{file}/move/{dest}`(移动),照 ComfyUI 的语义。"""
        state = self.server.state
        overwrite = query.get("overwrite", ["true"])[0] != "false"
        rest = path[len("/api/userdata/"):]
        if "/move/" in rest:
            source_raw, dest_raw = rest.split("/move/", 1)
            source, dest = unquote(source_raw), unquote(dest_raw)
            state.calls.append(("MOVE", source, {"dest": dest, "overwrite": overwrite}))
            if ".." in source.split("/") or ".." in dest.split("/"):
                self._json({"error": "forbidden"}, 403)
                return
            directory = state.userdata_get(source) is None and state.is_dir(source)
            if state.userdata_get(source) is None and not directory:
                self._json({"error": "not found"}, 404)
                return
            if not overwrite and state.exists(dest):
                self.send_response(409)
                self.send_header("Content-Length", "19")
                self.end_headers()
                self.wfile.write(b"File already exists")
                return
            if directory:
                state.move_dir(source, dest)
            else:
                state.userdata_put(dest, state.userdata_pop(source))
            self._json({"path": dest, "size": 1, "modified": 1791000000000})
            return
        name = unquote(rest)
        state.calls.append(("WRITE", name, {"overwrite": overwrite, "body": raw.decode("utf-8", "replace")}))
        if ".." in name.split("/"):
            self._json({"error": "forbidden"}, 403)
            return
        if not overwrite and state.exists(name):
            self.send_response(409)
            self.send_header("Content-Length", "19")
            self.end_headers()
            self.wfile.write(b"File already exists")
            return
        state.userdata_put(name, json.loads(raw or b"null"))
        stamp = state.modified(name[len("workflows/"):]) if name.startswith("workflows/") else 1791000000000
        self._json({"path": name, "size": len(raw), "modified": stamp})

    def do_DELETE(self) -> None:  # noqa: N802
        state = self.server.state
        path = urlsplit(self.path).path
        if not self._authorized():
            return
        name = unquote(path[len("/api/userdata/"):]) if path.startswith("/api/userdata/") else path
        state.calls.append(("DELETE", name, None))
        if state.userdata_get(name) is None:
            self._json({"error": "not found"}, 404)
            return
        state.userdata_pop(name)
        self.send_response(204)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        state = self.server.state
        parts = urlsplit(self.path)
        path = parts.path
        raw = self._body()
        if not self._authorized():
            return
        if path.startswith("/api/userdata/"):
            self._userdata_write(path, parse_qs(parts.query), raw)
            return
        if path == "/upload/image":
            name, content = _multipart_file(self.headers.get("Content-Type", ""), raw)
            fields = _multipart_fields(self.headers.get("Content-Type", ""), raw)
            state.uploads.append((name, content))
            state.upload_fields.append(fields)
            state.calls.append(("POST", path, name))
            self._json({"name": name, "subfolder": fields.get("subfolder", ""), "type": fields.get("type", "input")})
            return
        if path.startswith("/pysssss/save/") and state.pysssss != "missing" and "betterCombos.js" in state.pysssss_scripts:
            # 照 ComfyUI-Custom-Scripts 的 save_preview:temp(或 type 说的目录)里那一份拷到模型旁边,名字换上它的扩展名,
            # 同名的覆盖
            key = unquote(path[len("/pysssss/save/"):])
            body = json.loads(raw or b"{}")
            state.calls.append(("POST", path, body))
            folder, _, name = key.partition("/")
            uploaded = next((content for stored, content in reversed(state.uploads) if stored == body.get("filename")), None)
            if name not in state.model_folders.get(folder, []) or uploaded is None:
                self._json({"error": "bad request"}, 400)
                return
            suffix = "." + str(body.get("filename")).rsplit(".", 1)[-1]
            state.saved_previews[key] = (suffix, uploaded)
            # 拷到模型旁边的是一个真文件:/pysssss/view 按名字读得到它;ComfyUI 自己的预览接口只认图
            state.model_bytes[f"{key.rsplit('.', 1)[0]}{suffix}"] = uploaded
            if suffix in (".png", ".jpg", ".jpeg", ".webp"):
                state.model_previews.add(key)
            self._json({"image": f"{folder}/{name.rsplit('.', 1)[0].replace(chr(92), '/').rsplit('/', 1)[-1]}{suffix}"})
            return
        body = json.loads(raw or b"{}")
        state.calls.append(("POST", path, body))
        if path == "/prompt":
            if state.reject is not None:
                self._json(state.reject, 400)
                return
            state.next_id += 1
            prompt_id = f"p{state.next_id}"
            if state.node_errors is not None:
                state.pending.append(prompt_id)
                state.submitted.set()
                self._json({"prompt_id": prompt_id, "number": state.next_id, "node_errors": state.node_errors})
                return
            outcome = state.outcomes.pop(0) if state.outcomes else state.outcome
            if state.outputs is not None and outcome == "success":
                state.history[prompt_id] = {
                    "prompt": [state.next_id, prompt_id, body.get("prompt") or {}, {}, []],
                    "status": {"status_str": "success", "completed": True, "messages": []},
                    "outputs": json.loads(json.dumps(state.outputs)),
                }
            elif outcome == "success":
                state.history[prompt_id] = {
                    "status": {"status_str": "success", "completed": True, "messages": []},
                    "outputs": {"9": {"images": [{"filename": "mosael_00001_.png", "subfolder": "", "type": "output"}],
                                      },
                                "12": {"images": [{"filename": "preview.png", "subfolder": "", "type": "temp"}]}},
                }
            elif outcome == "video":
                state.history[prompt_id] = {
                    "status": {"status_str": "success", "completed": True, "messages": []},
                    "outputs": {"8": {"images": [{"filename": "frame_00001.png", "subfolder": "", "type": "output"}]},
                                "30": {"gifs": [{"filename": "wan_00001.mp4", "subfolder": "video", "type": "output"}]}},
                }
            elif outcome == "interrupted":
                # 有人在 ComfyUI 界面里点了中断:历史里记成 error,消息里是 execution_interrupted
                state.history[prompt_id] = {"status": {
                    "status_str": "error", "completed": False,
                    "messages": [["execution_start", {"prompt_id": prompt_id}],
                                 ["execution_interrupted", {"prompt_id": prompt_id, "node_id": "3",
                                                            "node_type": "KSampler", "executed": ["4"]}]],
                }, "outputs": {}}
            elif outcome == "error":
                # 和真的 ComfyUI 一样,历史里存着提交的那张图(`prompt` 的第三项)。
                state.history[prompt_id] = {
                    "prompt": [state.next_id, prompt_id, body.get("prompt") or {}, {}, []],
                    "status": {
                        "status_str": "error", "completed": False,
                        "messages": [["execution_error", {"node_type": state.error_node,
                                                          "exception_message": state.error_message}]],
                    },
                }
            else:
                state.running.append(prompt_id)
            state.submitted.set()
            self._json({"prompt_id": prompt_id, "number": state.next_id, "node_errors": {}})
        elif path == "/v2/manager/queue/install_model" and state.manager:
            if "client_id" not in body or "ui_id" not in body:
                self.send_response(400)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            state.manager_tasks.append(body)
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif path == "/v2/manager/queue/task" and state.manager:
            # 节点包之类的任务(QueueTaskItem:ui_id、client_id、kind、params)。缺字段 → 400,和 pydantic 校验一样。
            if not all(key in body for key in ("ui_id", "client_id", "kind", "params")):
                self._json({"error": "Invalid task data"}, 400)
                return
            state.manager_tasks.append(body)
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif path == "/v2/manager/reboot" and state.manager:
            if not state.manager_reboot_allowed:
                self._json({}, 403)
                return
            state.down_left = state.reboot_down_polls
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif path == "/v2/manager/queue/start" and state.manager:
            # 真的 Manager 在后台线程里一个个跑;这里当场跑完,插件轮询历史时就看得到结果。
            for task in [one for one in state.manager_tasks if one.get("kind") == "install"]:
                ok = state.manager_outcome == "success"
                params = task["params"]
                if ok:
                    state.manager_installed[params["id"]] = {"ver": "1.0.0", "cnr_id": params["id"], "aux_id": None,
                                                            "enabled": True}
                elif state.manager_outcome == "policy":
                    state.log({"m": f"\x1b[1m\x1b[31m[ERROR]\x1b[0m {MANAGER_POLICY_MESSAGE}\n"})
                else:
                    state.log({"m": f"[ComfyUI-Manager] Installation failed: Cannot resolve install target: '{params['id']}'\n"})
                state.manager_history[task["ui_id"]] = {
                    "ui_id": task["ui_id"], "client_id": task["client_id"], "kind": "install",
                    "result": "success" if ok else "failed",
                    "status": {"status_str": "success" if ok else "error", "completed": True,
                               "messages": [] if ok else ["failed"]},
                    "params": params,
                }
            state.manager_tasks[:] = [one for one in state.manager_tasks if one.get("kind") != "install"]
            for task in state.manager_tasks:
                ok = state.manager_outcome == "success"
                if ok:
                    state.model_folders.setdefault(task["save_path"], []).append(task["filename"])
                elif state.manager_outcome == "policy":
                    state.log({"m": f"\x1b[1m\x1b[31m[ERROR]\x1b[0m {MANAGER_POLICY_MESSAGE}\n"})
                else:
                    state.log({"m": "[ComfyUI-Manager] Model installation error: HTTP Error 404: Not Found\n"})
                state.manager_history[task["ui_id"]] = {
                    "ui_id": task["ui_id"], "client_id": task["client_id"], "kind": "install-model",
                    "result": "success" if ok else "failed",
                    "status": {"status_str": "success" if ok else "error", "completed": True,
                               "messages": [] if ok else ["failed"]},
                    "params": {key: value for key, value in task.items() if key not in ("client_id",)},
                }
            state.manager_tasks.clear()
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif path in ("/interrupt", "/queue", "/free"):
            if path == "/queue" and body.get("clear"):
                state.pending.clear()
            self._json({})
        else:
            self._json({"error": "unknown"}, 404)

    # --- WebSocket --------------------------------------------------------

    def _websocket(self, client_id: str) -> None:
        state = self.server.state
        self.close_connection = True
        if not state.websocket:
            self._json({"error": "no websocket"}, 404)
            return
        key = self.headers.get("Sec-WebSocket-Key", "")
        accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        self.wfile.write(
            ("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
             f"Sec-WebSocket-Accept: {accept}\r\n\r\n").encode("ascii")
        )
        self.wfile.flush()
        _frame(self.wfile, {"type": "status", "data": {"status": {"exec_info": {"queue_remaining": 1}}, "sid": client_id}})
        if not state.submitted.wait(timeout=10):
            return
        prompt_id = f"p{state.next_id}"
        if state.websocket_reset:
            self.wfile.write(b"\x81")  # 半个帧头,然后 RST
            self.wfile.flush()
            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            self.connection.close()
            return
        self.wfile.write(bytes([0x82, 4]) + b"\x00\x01\x02\x03")  # 一帧二进制预览图:插件该跳过
        if state.outcome == "error":
            _frame(self.wfile, {"type": "execution_error", "data": {
                "prompt_id": prompt_id, "node_id": "6", "node_type": state.error_node,
                "exception_message": state.error_message}})
            self.wfile.flush()
            return
        for message in (
            {"type": "execution_start", "data": {"prompt_id": prompt_id}},
            {"type": "execution_cached", "data": {"nodes": ["4"], "prompt_id": prompt_id}},
            {"type": "executing", "data": {"node": "3", "prompt_id": prompt_id}},
            {"type": "progress", "data": {"value": 5, "max": 20, "prompt_id": prompt_id, "node": "3"}},
            {"type": "executing", "data": {"node": None, "prompt_id": prompt_id}},
        ):
            _frame(self.wfile, message)
        self.wfile.flush()


def _frame(stream: Any, message: dict[str, Any]) -> None:
    payload = json.dumps(message).encode("utf-8")
    if len(payload) < 126:
        header = bytes([0x81, len(payload)])
    else:
        header = bytes([0x81, 126]) + struct.pack("!H", len(payload))
    stream.write(header + payload)


def _multipart_fields(content_type: str, body: bytes) -> dict[str, str]:
    """multipart 里除文件以外的字段(`type`、`subfolder`、`overwrite`)。"""
    boundary = content_type.split("boundary=", 1)[1].encode()
    fields: dict[str, str] = {}
    for part in body.split(b"--" + boundary):
        found = re.search(rb'name="([^"]+)"\r\n\r\n', part)
        if found and b"filename=" not in part:
            fields[found.group(1).decode()] = part.split(b"\r\n\r\n", 1)[1].rstrip(b"\r\n").decode()
    return fields


def _multipart_file(content_type: str, body: bytes) -> tuple[str, bytes]:
    boundary = content_type.split("boundary=", 1)[1].encode()
    for part in body.split(b"--" + boundary):
        if b'name="image"' not in part:
            continue
        head, _, content = part.partition(b"\r\n\r\n")
        name = re.search(rb'filename="([^"]+)"', head).group(1).decode()
        return name, content.rstrip(b"\r\n")
    raise AssertionError("upload without an image part")


class FakeComfyUI(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.state = State()
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def __enter__(self) -> "FakeComfyUI":
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.shutdown()
        self.server_close()

    def posted(self, path: str) -> list[Any]:
        return [body for method, called, body in self.state.calls if method == "POST" and called == path]
