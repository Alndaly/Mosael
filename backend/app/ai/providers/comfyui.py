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
    GenerationCallbacks,
    GenerationProvider,
    GenerationRequest,
    GenerationResult,
    ProviderContext,
    ProviderError,
    metering_from_request,
)
from app.ai.providers.comfyui_client import ComfyUIClient, inject_generation_params

"""
ComfyUI adapter: a local (or LAN) ComfyUI instance becomes a zero-credential image/video
provider. POST /prompt submits an API-format workflow graph, /history/{id} is polled until
the graph finishes, outputs are fetched via /view.

The seam that makes arbitrary ComfyUI graphs fit Mibu's prompt→media contract is a
*template with placeholders*: the profile may carry a workflow exported from ComfyUI
(API format) in which `{{prompt}}` `{{negative}}` `{{seed}}` `{{width}}` `{{height}}`
`{{steps}}` `{{duration_seconds}}` are substituted per request. Images fall back to a
built-in txt2img graph (checkpoint discovered live from /object_info) so a stock ComfyUI
works unconfigured; video always needs a pasted template — there is no stock video graph
that works without extra custom nodes, so pretending otherwise would only defer the error.

Multiple templates = multiple provider profiles: the profile picker already selects among
them per generation session, so template management needs no parallel store.

Cancel/progress ride on GenerationCallbacks: each poll tick reports coarse progress
(queue position, elapsed) and checks for user cancel, which maps to POST /interrupt for
the running prompt plus a queue delete for a pending one.
"""

DEFAULT_BASE = "http://127.0.0.1:8188"
SUBMIT_TIMEOUT = 30
#: Generation itself can be minutes on a modest GPU; polling is cheap, the ceiling generous.
POLL_TIMEOUT_SECONDS = 600
POLL_INTERVAL_SECONDS = 1.0
#: Keys ComfyUI output nodes file media under: SaveImage → images, VHS/AnimateDiff → gifs,
#: newer video-combine nodes → videos. Scanned in this order.
OUTPUT_KEYS = ("images", "gifs", "videos")

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


def collect_output_files(history_entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Every media file a finished graph produced (images/gifs/videos), previews excluded."""
    files: list[dict[str, Any]] = []
    for node_output in (history_entry.get("outputs") or {}).values():
        for key in OUTPUT_KEYS:
            for item in node_output.get(key) or []:
                if item.get("filename") and item.get("type") != "temp":
                    files.append(item)
    return files


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
    supports_callbacks = True

    def __init__(self, kind: str = "image") -> None:
        self.kind = kind

    def requires_credentials(self) -> bool:
        return False  # 本地服务,无密钥;可达性在 generate 里用可读错误报告

    def generate(
        self,
        request: GenerationRequest,
        context: ProviderContext,
        output_dir: Path,
        callbacks: GenerationCallbacks | None = None,
    ) -> GenerationResult:
        base = (context.base_url or DEFAULT_BASE).rstrip("/")
        width, height = _size_from_request(request)
        values: dict[str, Any] = {
            "prompt": request.prompt,
            "negative": request.negative_prompt,
            "seed": int(request.parameters.get("seed") or random.randint(0, 2**31 - 1)),
            "steps": int(request.parameters.get("steps") or 20),
            "width": width,
            "height": height,
            "duration_seconds": float(request.parameters.get("duration_seconds", 5)),
        }
        try:
            with httpx.Client(base_url=base, timeout=SUBMIT_TIMEOUT) as client:
                graph = self._resolve_graph(client, context, request, values, base)
                prompt_id = self._submit(client, graph)
                entry = self._wait(client, prompt_id, callbacks)
                files = collect_output_files(entry)
                if not files:
                    raise ProviderError(
                        "ComfyUI 完成了执行但没有产出文件——工作流模板里需要 SaveImage(图)或视频合成输出节点(视频)"
                    )
                output_dir.mkdir(parents=True, exist_ok=True)
                chosen = self._pick_output(files)
                suffix = Path(chosen["filename"]).suffix or (".mp4" if self.kind == "video" else ".png")
                target = output_dir / f"comfyui-{prompt_id[:8]}{suffix}"
                download = client.get("/view", params={
                    "filename": chosen["filename"],
                    "subfolder": chosen.get("subfolder", ""),
                    "type": chosen.get("type", "output"),
                })
                download.raise_for_status()
                target.write_bytes(download.content)
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"连接 ComfyUI 失败({base}):{exc}。请确认 ComfyUI 正在运行,地址在设置 → AI 绘图 → ComfyUI 里可改。"
            ) from exc
        usage = metering_from_request(request)
        return GenerationResult(output_path=target, usage=usage, raw_usage={"prompt_id": prompt_id})

    # ------------------------------------------------------------------
    def _pick_output(self, files: list[dict[str, Any]]) -> dict[str, Any]:
        if self.kind == "video":
            # 视频图里常同时有帧图与合成视频;优先真正的视频容器
            for item in files:
                if Path(item["filename"]).suffix.lower() in (".mp4", ".webm", ".mov", ".gif", ".webp"):
                    return item
        return files[0]

    def _resolve_graph(
        self,
        client: httpx.Client,
        context: ProviderContext,
        request: GenerationRequest,
        values: dict[str, Any],
        base: str,
    ) -> dict[str, Any]:
        """决定这次生成用哪张图并填好参数,分三条路:
        1) 生成时选了 ComfyUI 里保存的工作流(parameters.workflow=文件路径)→ 拉取 + UI→API 转换
           + 自动识别注入提示词/种子/尺寸(ComfyUI 知识都在 comfyui_client)。
        2) 档案里粘贴了自定义 API 模板 → 走 {{占位符}} 替换(现状)。
        3) 都没有 → 内置 txt2img。
        末尾统一再跑一次 substitute,让路 1 里用户手动标的 {{prompt}} 占位符也能兜底。"""
        workflow = str(request.parameters.get("workflow") or "").strip()
        if workflow and workflow not in ("builtin", "custom"):
            try:
                api_prompt = ComfyUIClient(base).workflow_to_api_prompt(workflow)
            except Exception as exc:  # noqa: BLE001 — 任何拉取/转换失败都回报可读错误
                raise ProviderError(
                    f"拉取或转换 ComfyUI 工作流「{workflow}」失败:{exc}。"
                    "可在生成时改选其它工作流、内置文生图,或在档案里粘贴自定义 API 模板。"
                ) from exc
            graph = inject_generation_params(api_prompt, values)
            return substitute_placeholders(graph, values)
        template = self._resolve_template(client, context)
        return substitute_placeholders(template, values)

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
        if self.kind == "video":
            # 没有"到处都能跑"的内置视频图(AnimateDiff/SVD/WAN 都要装节点),
            # 硬造一个只会把错误推迟到执行期 —— 不如立刻说清楚缺什么。
            raise ProviderError(
                "ComfyUI 视频生成需要工作流模板:在 ComfyUI 里搭好视频工作流(如 AnimateDiff / WAN),"
                "「导出 (API)」后粘贴到该档案的模板字段,提示词位置写 {{prompt}}"
            )
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

    def _wait(self, client: httpx.Client, prompt_id: str, callbacks: GenerationCallbacks | None) -> dict[str, Any]:
        started = time.monotonic()
        deadline = started + POLL_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if callbacks is not None and callbacks.is_cancelled():
                self._interrupt(client, prompt_id)
                raise ProviderError("已取消")
            if callbacks is not None:
                callbacks.on_progress(*self._progress(client, prompt_id, started))
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

    def _progress(self, client: httpx.Client, prompt_id: str, started: float) -> tuple[float, str]:
        """Coarse progress from the queue: position while pending, elapsed while running.

        ComfyUI's fine-grained progress lives on a WebSocket; the queue poll costs one GET
        we are already paying and never lies about state. 0.95 is the runner's ceiling —
        1.0 belongs to asset registration.
        """
        elapsed = int(time.monotonic() - started)
        try:
            queue = client.get("/queue").json()
            pending = [item[1] for item in queue.get("queue_pending") or [] if len(item) > 1]
            if prompt_id in pending:
                position = pending.index(prompt_id) + 1
                return 0.05, f"ComfyUI 排队中(第 {position} 位)"
        except Exception:  # noqa: BLE001 — 进度是装饰,拿不到队列绝不影响生成
            pass
        fraction = min(0.9, 0.15 + elapsed / 120.0)  # 无真实进度时按时间爬坡,封顶 0.9
        return fraction, f"ComfyUI 生成中…(已用 {elapsed}s)"

    def _interrupt(self, client: httpx.Client, prompt_id: str) -> None:
        """Best-effort stop: interrupt the running prompt AND drop it from the queue —
        which one applies depends on timing we cannot observe atomically."""
        for call in (
            lambda: client.post("/interrupt"),
            lambda: client.post("/queue", json={"delete": [prompt_id]}),
        ):
            try:
                call()
            except httpx.HTTPError:
                pass


def _error_from_status(status: dict[str, Any]) -> str:
    for message in reversed(status.get("messages") or []):
        # messages 是 [type, payload] 对;execution_error 的 payload 带 exception_message
        if isinstance(message, list) and len(message) == 2 and message[0] == "execution_error":
            payload = message[1] or {}
            return str(payload.get("exception_message") or payload.get("node_type") or "execution_error")[:300]
    return "未知错误(详见 ComfyUI 日志)"
