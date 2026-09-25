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
PORTRAIT_UI: dict[str, Any] = {
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
    reject: dict[str, Any] | None = None
    running: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    uploads: list[tuple[str, bytes]] = field(default_factory=list)
    calls: list[tuple[str, str, Any]] = field(default_factory=list)
    websocket: bool = False
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

    # --- GET --------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 — http.server 的约定
        state = self.server.state
        parts = urlsplit(self.path)
        path, query = parts.path, parse_qs(parts.query)
        state.calls.append(("GET", path, query))
        if path == "/ws":
            self._websocket(query.get("clientId", [""])[0])
            return
        if path == "/object_info":
            self._json(state.object_info)
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
            elif state.outcome == "error":
                state.history[prompt_id] = {"status": {
                    "status_str": "error", "completed": False,
                    "messages": [["execution_error", {"node_type": "KSampler", "exception_message": "CUDA out of memory"}]],
                }}
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
        self.wfile.write(bytes([0x82, 4]) + b"\x00\x01\x02\x03")  # 一帧二进制预览图:插件该跳过
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
