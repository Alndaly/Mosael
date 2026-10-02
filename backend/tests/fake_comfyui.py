"""一台假的 ComfyUI:本机随机端口上的 HTTP 服务(可选 WebSocket),给 ComfyUI 插件的测试用。

**测试套不连真的 ComfyUI。** 这台假的只实现插件用到的那几个接口,形状照 ComfyUI 0.3x 的真实回包:
`/object_info`、`/api/userdata`(列工作流 / 取工作流)、`/upload/image`(multipart)、`/prompt`、
`/history/{id}`、`/queue`、`/interrupt`、`/view`,以及 `/ws?clientId=…` 上的执行事件。

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
}
for _name in ("SaveImage",):
    OBJECT_INFO[_name]["output_node"] = True


def widget(name: str) -> dict[str, Any]:
    return {"name": name, "widget": {"name": name}, "link": None}


def conn(name: str, link: int) -> dict[str, Any]:
    return {"name": name, "link": link}


#: 一张保存的**文生图 + 参考图**工作流(UI 格式),形状照 ComfyUI 前端保存下来的那种。
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
    ],
    "links": [
        [1, 4, 0, 3, 0, "MODEL"], [2, 6, 0, 3, 1, "CONDITIONING"], [3, 7, 0, 3, 2, "CONDITIONING"],
        [4, 5, 0, 3, 3, "LATENT"], [5, 4, 1, 6, 0, "CLIP"], [6, 4, 1, 7, 0, "CLIP"],
        [7, 3, 0, 8, 0, "LATENT"], [8, 4, 2, 8, 1, "VAE"], [9, 8, 0, 9, 0, "IMAGE"],
    ],
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

#: 只接了**预览**节点的工作流(用户 ComfyUI 里「古风女孩1」那种):三个 PreviewImage,都没改标题。生成交回的就是
#: 这三份预览。
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
    #: outcome == "error" 时 ComfyUI 说的是哪一类节点、什么原话(WebSocket 和历史里是同一句)。
    error_node: str = "KSampler"
    error_message: str = "CUDA out of memory"
    reject: dict[str, Any] | None = None
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
        if path == "/object_info":
            self._json(state.object_info)
        elif path == "/api/userdata" and query.get("dir") == ["workflows"] and not state.workflows:
            # 刚装好的 ComfyUI 还没存过工作流:workflows 目录不存在,ComfyUI 回 404 "Directory not found"
            self.send_response(404)
            self.send_header("Content-Length", "19")
            self.end_headers()
            self.wfile.write(b"Directory not found")
        elif path == "/api/userdata" and query.get("dir") == ["workflows"]:
            self._json([{"path": name, "size": len(json.dumps(graph)), "modified": 1}
                        for name, graph in state.workflows.items()])
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
        elif path == "/history":
            items = list(state.history.items())
            limit = int(query.get("max_items", ["0"])[0] or 0)
            self._json(dict(items[-limit:] if limit else items))
        elif path.startswith("/api/userdata/"):
            name = unquote(path[len("/api/userdata/"):])
            workflow = state.workflows.get(name.removeprefix("workflows/"))
            if workflow is None:
                self._json({"error": "not found"}, 404)
            else:
                self._json(workflow)
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

    def do_POST(self) -> None:  # noqa: N802
        state = self.server.state
        path = urlsplit(self.path).path
        raw = self._body()
        if not self._authorized():
            return
        if path == "/upload/image":
            name, content = _multipart_file(self.headers.get("Content-Type", ""), raw)
            state.uploads.append((name, content))
            state.calls.append(("POST", path, name))
            self._json({"name": name, "subfolder": "mosael", "type": "input"})
            return
        body = json.loads(raw or b"{}")
        state.calls.append(("POST", path, body))
        if path == "/prompt":
            if state.reject is not None:
                self._json(state.reject, 400)
                return
            state.next_id += 1
            prompt_id = f"p{state.next_id}"
            if state.outputs is not None:
                state.history[prompt_id] = {
                    "prompt": [state.next_id, prompt_id, body.get("prompt") or {}, {}, []],
                    "status": {"status_str": "success", "completed": True, "messages": []},
                    "outputs": json.loads(json.dumps(state.outputs)),
                }
            elif state.outcome == "success":
                state.history[prompt_id] = {
                    "status": {"status_str": "success", "completed": True, "messages": []},
                    "outputs": {"9": {"images": [{"filename": "mosael_00001_.png", "subfolder": "", "type": "output"}],
                                      },
                                "12": {"images": [{"filename": "preview.png", "subfolder": "", "type": "temp"}]}},
                }
            elif state.outcome == "video":
                state.history[prompt_id] = {
                    "status": {"status_str": "success", "completed": True, "messages": []},
                    "outputs": {"8": {"images": [{"filename": "frame_00001.png", "subfolder": "", "type": "output"}]},
                                "30": {"gifs": [{"filename": "wan_00001.mp4", "subfolder": "video", "type": "output"}]}},
                }
            elif state.outcome == "interrupted":
                # 有人在 ComfyUI 界面里点了中断:历史里记成 error,消息里是 execution_interrupted
                state.history[prompt_id] = {"status": {
                    "status_str": "error", "completed": False,
                    "messages": [["execution_start", {"prompt_id": prompt_id}],
                                 ["execution_interrupted", {"prompt_id": prompt_id, "node_id": "3",
                                                            "node_type": "KSampler", "executed": ["4"]}]],
                }, "outputs": {}}
            elif state.outcome == "error":
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
