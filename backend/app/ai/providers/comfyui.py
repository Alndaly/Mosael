from __future__ import annotations

import copy
import json
import random
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.ai.providers.base import (
    GenerationProvider,
    GenerationRequest,
    GenerationResult,
    ProviderContext,
    ProviderError,
    metering_from_request,
)

"""
ComfyUI adapter: a local (or LAN) ComfyUI instance becomes a zero-credential image
provider. POST /prompt submits an API-format workflow graph, /history/{id} is polled
until the graph finishes, and each SaveImage output is fetched via /view.

The seam that makes arbitrary ComfyUI graphs fit Mibu's prompt→image contract is a
*template with placeholders*: the profile may carry a workflow exported from ComfyUI
(设置 → 生成 → ComfyUI → 工作流模板, API format), in which `{{prompt}}` `{{negative}}`
`{{seed}}` `{{width}}` `{{height}}` `{{steps}}` are substituted per request. Without a
template a built-in txt2img graph is used, with the checkpoint discovered live from
/object_info — so a stock ComfyUI works before anything is configured.
"""

DEFAULT_BASE = "http://127.0.0.1:8188"
SUBMIT_TIMEOUT = 30
#: Generation itself can be minutes on a modest GPU; polling is cheap, the ceiling generous.
POLL_TIMEOUT_SECONDS = 600
POLL_INTERVAL_SECONDS = 1.0

#: Minimal txt2img in ComfyUI API format. `ckpt_name` is filled from /object_info at run
#: time — hardcoding a checkpoint filename would break on every install but the author's.
DEFAULT_TEMPLATE: dict[str, Any] = {
    "3": {"class_type": "KSampler", "inputs": {
        "cfg": 7, "denoise": 1, "sampler_name": "euler", "scheduler": "normal",
        "seed": "{{seed}}", "steps": "{{steps}}",
        "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "{{checkpoint}}"}},
    "5": {"class_type": "EmptyLatentImage", "inputs": {"batch_size": 1, "width": "{{width}}", "height": "{{height}}"}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 1], "text": "{{prompt}}"}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 1], "text": "{{negative}}"}},
    "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
    "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "mibu", "images": ["8", 0]}},
}


def substitute_placeholders(graph: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """Fill `{{key}}` placeholders in a parsed API-format graph.

    Values are substituted *after* parsing, not by string-replacing the JSON text: a prompt
    containing quotes or backslashes must never be able to break the document. A string that
    IS exactly one placeholder takes the raw value (so `"{{seed}}"` becomes an int, which
    KSampler requires); a string *containing* placeholders gets them spliced in as text.
    """

    def fill(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: fill(item) for key, item in value.items()}
        if isinstance(value, list):
            return [fill(item) for item in value]
        if isinstance(value, str):
            for key, raw in values.items():
                if value == "{{" + key + "}}":
                    return raw
            for key, raw in values.items():
                value = value.replace("{{" + key + "}}", str(raw))
            return value
        return value

    return fill(copy.deepcopy(graph))


def collect_output_images(history_entry: dict[str, Any]) -> list[dict[str, Any]]:
    """The image refs a finished graph produced, in node order."""
    images: list[dict[str, Any]] = []
    for node_output in (history_entry.get("outputs") or {}).values():
        for image in node_output.get("images") or []:
            if image.get("filename") and image.get("type") != "temp":
                images.append(image)
    return images


def _size_from_request(request: GenerationRequest) -> tuple[int, int]:
    size = str(request.parameters.get("size") or "").replace("*", "x")
    if "x" in size:
        try:
            width, height = (int(part) for part in size.split("x", 1))
            return max(64, width), max(64, height)
        except ValueError:
            pass
    return 1024, 1024


class ComfyUIProvider(GenerationProvider):
    name = "comfyui"
    kind = "image"

    def requires_credentials(self) -> bool:
        return False  # 本地服务,无密钥;可达性在 generate 里用可读错误报告

    def generate(self, request: GenerationRequest, context: ProviderContext, output_dir: Path) -> GenerationResult:
        base = (context.base_url or DEFAULT_BASE).rstrip("/")
        width, height = _size_from_request(request)
        values: dict[str, Any] = {
            "prompt": request.prompt,
            "negative": request.negative_prompt,
            "seed": int(request.parameters.get("seed") or random.randint(0, 2**31 - 1)),
            "steps": int(request.parameters.get("steps") or 20),
            "width": width,
            "height": height,
        }
        try:
            with httpx.Client(base_url=base, timeout=SUBMIT_TIMEOUT) as client:
                graph = self._resolve_template(client, context)
                graph = substitute_placeholders(graph, values)
                prompt_id = self._submit(client, graph)
                entry = self._wait(client, prompt_id)
                images = collect_output_images(entry)
                if not images:
                    raise ProviderError("ComfyUI 完成了执行但没有产出图片——工作流模板里需要一个 SaveImage 节点")
                output_dir.mkdir(parents=True, exist_ok=True)
                target = output_dir / f"comfyui-{prompt_id[:8]}{Path(images[0]['filename']).suffix or '.png'}"
                download = client.get("/view", params={
                    "filename": images[0]["filename"],
                    "subfolder": images[0].get("subfolder", ""),
                    "type": images[0].get("type", "output"),
                })
                download.raise_for_status()
                target.write_bytes(download.content)
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"连接 ComfyUI 失败({base}):{exc}。请确认 ComfyUI 正在运行,地址在设置 → AI 绘图 → ComfyUI 里可改。"
            ) from exc
        usage = metering_from_request(request)
        usage["images"] = 1
        return GenerationResult(output_path=target, usage=usage, raw_usage={"prompt_id": prompt_id})

    # ------------------------------------------------------------------
    def _resolve_template(self, client: httpx.Client, context: ProviderContext) -> dict[str, Any]:
        raw = str((context.extra or {}).get("workflow_template") or "").strip()
        if raw:
            try:
                graph = json.loads(raw)
            except ValueError as exc:
                raise ProviderError("ComfyUI 工作流模板不是合法 JSON——请从 ComfyUI 用「导出 (API)」格式导出后粘贴") from exc
            if not isinstance(graph, dict) or not graph:
                raise ProviderError("ComfyUI 工作流模板为空——需要 API 格式(节点 id → {class_type, inputs})")
            return graph
        # 无模板 → 内置 txt2img,checkpoint 现场发现
        response = client.get("/object_info/CheckpointLoaderSimple")
        response.raise_for_status()
        info = response.json().get("CheckpointLoaderSimple") or {}
        try:
            checkpoints = info["input"]["required"]["ckpt_name"][0]
        except (KeyError, IndexError, TypeError):
            checkpoints = []
        if not checkpoints:
            raise ProviderError("ComfyUI 里没有任何 checkpoint 模型——请先在 ComfyUI 安装一个模型,或在档案里粘贴自定义工作流模板")
        return substitute_placeholders(DEFAULT_TEMPLATE, {"checkpoint": checkpoints[0]})

    def _submit(self, client: httpx.Client, graph: dict[str, Any]) -> str:
        response = client.post("/prompt", json={"prompt": graph, "client_id": uuid.uuid4().hex})
        if response.status_code == 400:
            # ComfyUI 的校验错误藏在 node_errors 里,原样抛 HTTP 400 对用户毫无帮助
            detail = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            node_errors = detail.get("node_errors") or {}
            messages = [
                str(err.get("message") or err)
                for node in node_errors.values()
                for err in (node.get("errors") or [])
            ]
            top = (detail.get("error") or {}).get("message") if isinstance(detail.get("error"), dict) else ""
            raise ProviderError("ComfyUI 拒绝了工作流:" + ("; ".join(filter(None, [top, *messages])) or response.text[:300]))
        response.raise_for_status()
        prompt_id = str(response.json().get("prompt_id") or "")
        if not prompt_id:
            raise ProviderError("ComfyUI 未返回 prompt_id")
        return prompt_id

    def _wait(self, client: httpx.Client, prompt_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            response = client.get(f"/history/{prompt_id}")
            response.raise_for_status()
            entry = response.json().get(prompt_id)
            if entry:
                status = entry.get("status") or {}
                if status.get("status_str") == "error":
                    raise ProviderError(f"ComfyUI 执行失败:{_error_from_status(status)}")
                if status.get("completed") or entry.get("outputs"):
                    return entry
            time.sleep(POLL_INTERVAL_SECONDS)
        raise ProviderError(f"ComfyUI 生成超时({POLL_TIMEOUT_SECONDS}s)——工作流可能仍在排队,可在 ComfyUI 界面查看")


def _error_from_status(status: dict[str, Any]) -> str:
    for message in reversed(status.get("messages") or []):
        # messages 是 [type, payload] 对;execution_error 的 payload 带 exception_message
        if isinstance(message, list) and len(message) == 2 and message[0] == "execution_error":
            payload = message[1] or {}
            return str(payload.get("exception_message") or payload.get("node_type") or "execution_error")[:300]
    return "未知错误(详见 ComfyUI 日志)"
