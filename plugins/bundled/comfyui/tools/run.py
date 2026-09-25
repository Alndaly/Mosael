"""在 ComfyUI 上做一次生成:填图、传参考图、提交、看进度、能取消、能接着等、取回成片。

协议见 docs/PLUGIN_MANIFEST 的「替宿主做生成」。这一侧只做三件宿主做不了的事:

- **说出进度**:WebSocket 上的真实进度(哪个节点、第几步),连不上就退回轮询 `/history` / `/queue`;
- **停下远端**:宿主建了取消文件,就把这一个任务从 ComfyUI 里停掉 —— 在跑的 `/interrupt`,
  在排队的从队列里删掉。不去停的话,ComfyUI 会把它跑完,占着显卡,而结果没人要;
- **交回回执**:提交拿到 `prompt_id` 就交给宿主,宿主落库。后端重启后带着它再来,这里接着等,不再提交。
"""

from __future__ import annotations

import json
import os
import random
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import graph
import models
from comfy_http import Comfy
from lines import ComfyError, say
from ws import WebSocket, WebSocketClosed

#: 轮询的节奏。WebSocket 在的时候它只是保险(几秒没消息就看一眼 /history)。
POLL_SECONDS = 1.0
QUIET_SECONDS = 5.0

Emit = Callable[[dict[str, Any]], None]


def _cancelled() -> bool:
    path = os.environ.get("MOSAEL_PLUGIN_CANCEL_FILE", "")
    return bool(path) and os.path.exists(path)


def _progress(emit: Emit, fraction: float, message: str) -> None:
    emit({"event": "progress", "progress": round(max(0.0, min(0.95, fraction)), 4), "message": message})


def _size(value: Any) -> tuple[int, int] | None:
    text = str(value or "").lower().replace("*", "x")
    if "x" not in text:
        return None
    try:
        width, height = (int(part) for part in text.split("x", 1))
    except ValueError:
        return None
    return (max(16, width), max(16, height))


def _values(request: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """宿主主控件的那几样。**只放给了的**(和占位符的默认值)—— 没选尺寸就不改这张图的尺寸。"""
    parameters = request.get("parameters") or {}
    values: dict[str, Any] = dict(defaults)
    values["prompt"] = str(request.get("prompt") or "")
    negative = str(request.get("negative_prompt") or "")
    if negative or "negative" not in values:
        values["negative"] = negative
    # 种子:用户没给就每次随机 —— 通过 API 提交时同一个种子会得到同一张图,而界面上的
    # 「每次生成后随机」只是 ComfyUI 前端的行为,API 那一侧没有。
    seed = parameters.get("seed")
    values["seed"] = int(seed) if isinstance(seed, (int, float)) and not isinstance(seed, bool) else random.randint(0, 2**31 - 1)
    size = _size(parameters.get("size"))
    if size:
        values["width"], values["height"] = size
    for key in ("steps", "duration_seconds"):
        if isinstance(parameters.get(key), (int, float)) and not isinstance(parameters.get(key), bool):
            values[key] = parameters[key]
    return values


def _overrides(request: dict[str, Any]) -> dict[str, Any]:
    """参数表里动过的那些(`<节点 id>.<输入名>`)。宿主词汇的键(seed / size …)不在这里。"""
    return {key: value for key, value in (request.get("parameters") or {}).items() if "." in key}


def _upload(comfy: Comfy, inputs: list[dict[str, str]]) -> dict[str, list[str]]:
    uploaded: dict[str, list[str]] = {}
    for item in inputs:
        source = Path(item["path"])
        name = f"mosael-{uuid.uuid4().hex[:8]}-{source.name}"
        uploaded.setdefault(item["role"], []).append(comfy.upload_image(source, name))
    return uploaded


def _submit(comfy: Comfy, prompt: dict[str, Any], client_id: str, locale: str) -> str:
    try:
        answer = comfy.post("/prompt", {"prompt": prompt, "client_id": client_id})
    except ComfyError as exc:
        if exc.status == 400:
            try:
                detail = graph.validation_errors(json.loads(exc.body or "{}"))
            except ValueError:
                detail = exc.body
            raise ComfyError(say(locale, f"ComfyUI 拒绝了这张工作流:{detail}", f"ComfyUI rejected the workflow: {detail}")) from exc
        raise
    prompt_id = str((answer or {}).get("prompt_id") or "")
    if not prompt_id:
        raise ComfyError(say(locale, "ComfyUI 没有交回任务号", "ComfyUI did not return a prompt id"))
    return prompt_id


def _stop(comfy: Comfy, prompt_id: str) -> None:
    """停下这一个任务:在跑就 /interrupt,在排队就从队列里删。

    先看队列再动手:`/interrupt` 停的是**正在跑的那个**,不管它是谁的 —— 同一台 ComfyUI 上别人的
    任务不该因为我这边取消而被掐掉。看不了队列(老版本 / 网络抖一下)才两样都做。
    """
    try:
        queue = comfy.get("/queue") or {}
        running = {item[1] for item in queue.get("queue_running") or [] if isinstance(item, list) and len(item) > 1}
        pending = {item[1] for item in queue.get("queue_pending") or [] if isinstance(item, list) and len(item) > 1}
    except ComfyError:
        running, pending = {prompt_id}, {prompt_id}
    try:
        if prompt_id in running:
            comfy.post("/interrupt", {"prompt_id": prompt_id})
    except ComfyError:
        pass
    try:
        if prompt_id in pending:
            comfy.post("/queue", {"delete": [prompt_id]})
    except ComfyError:
        pass


class _Tracker:
    """把 ComfyUI 的事件折算成一个比例和一句话。"""

    def __init__(self, prompt: dict[str, Any], locale: str) -> None:
        self.total = max(1, len(prompt))
        self.types = {node_id: str(node.get("class_type", "")) for node_id, node in prompt.items()}
        self.done: set[str] = set()
        self.current = ""
        self.step = 0.0
        self.locale = locale
        self.started = False

    def fraction(self) -> float:
        return 0.05 + 0.9 * min(1.0, (len(self.done) + self.step) / self.total)

    def message(self, detail: str = "") -> str:
        name = self.types.get(self.current, "")
        if not self.started:
            return say(self.locale, "ComfyUI 排队中", "Queued in ComfyUI")
        if name and detail:
            return f"{name} {detail}"
        return name or say(self.locale, "ComfyUI 生成中", "Generating in ComfyUI")


def _follow_ws(comfy: Comfy, socket: WebSocket, prompt_id: str, tracker: _Tracker, emit: Emit, locale: str) -> dict[str, Any]:
    """跟着 WebSocket 等到结束。几秒没消息就看一眼 /history(WebSocket 丢了消息也不至于等到天荒地老)。"""
    last_poll = time.monotonic()
    while True:
        if _cancelled():
            _stop(comfy, prompt_id)
            raise ComfyError(say(locale, "已取消", "Cancelled"))
        raw = socket.recv(POLL_SECONDS)
        if raw:
            try:
                message = json.loads(raw)
            except ValueError:
                message = {}
            kind = message.get("type")
            data = message.get("data") or {}
            mine = data.get("prompt_id") in (None, prompt_id)
            if kind == "execution_start" and mine:
                tracker.started = True
                _progress(emit, tracker.fraction(), tracker.message())
            elif kind == "execution_cached" and mine:
                tracker.started = True
                tracker.done.update(str(node) for node in data.get("nodes") or [])
                _progress(emit, tracker.fraction(), tracker.message())
            elif kind == "executing" and mine:
                node = data.get("node")
                if node is None and data.get("prompt_id") == prompt_id:
                    entry = _history(comfy, prompt_id)
                    if entry:
                        return entry
                    continue
                tracker.started = True
                if tracker.current:
                    tracker.done.add(tracker.current)
                tracker.current, tracker.step = str(node), 0.0
                _progress(emit, tracker.fraction(), tracker.message())
            elif kind == "progress" and mine:
                value, maximum = data.get("value"), data.get("max")
                if isinstance(value, (int, float)) and isinstance(maximum, (int, float)) and maximum:
                    tracker.step = min(1.0, value / maximum)
                    _progress(emit, tracker.fraction(), tracker.message(f"{int(value)}/{int(maximum)}"))
            elif kind == "execution_error" and data.get("prompt_id") == prompt_id:
                said = f"{data.get('node_type') or ''}: {data.get('exception_message') or ''}".strip(": ")
                raise ComfyError(say(locale, f"ComfyUI 执行失败:{said or '详见 ComfyUI 日志'}",
                                     f"ComfyUI execution failed: {said or 'see the ComfyUI log'}"))
            elif kind == "execution_interrupted" and data.get("prompt_id") == prompt_id:
                raise ComfyError(say(locale, "ComfyUI 里这个任务被中断了", "The task was interrupted in ComfyUI"))
            elif kind == "execution_success" and data.get("prompt_id") == prompt_id:
                entry = _history(comfy, prompt_id)
                if entry:
                    return entry
            if raw:
                last_poll = time.monotonic()
                continue
        if time.monotonic() - last_poll >= QUIET_SECONDS:
            last_poll = time.monotonic()
            entry = _history(comfy, prompt_id)
            if entry:
                return entry


def _history(comfy: Comfy, prompt_id: str) -> dict[str, Any] | None:
    """这个任务跑完了吗:跑完了回它的那一条历史,失败了直接说原因,还没完回 None。"""
    entry = (comfy.get(f"/history/{prompt_id}") or {}).get(prompt_id)
    if not entry:
        return None
    status = entry.get("status") or {}
    if status.get("status_str") == "error":
        said = graph.execution_error(status)
        raise ComfyError(say(comfy.locale, f"ComfyUI 执行失败:{said or '详见 ComfyUI 日志'}",
                             f"ComfyUI execution failed: {said or 'see the ComfyUI log'}"))
    if status.get("completed") or entry.get("outputs"):
        return entry
    return None


def _follow_poll(comfy: Comfy, prompt_id: str, emit: Emit, locale: str) -> dict[str, Any]:
    """没有 WebSocket 时的等法:轮询历史和队列。只看得到排队和结束,中间按时间爬坡。"""
    started = time.monotonic()
    missing = 0
    while True:
        if _cancelled():
            _stop(comfy, prompt_id)
            raise ComfyError(say(locale, "已取消", "Cancelled"))
        entry = _history(comfy, prompt_id)
        if entry:
            return entry
        queue = comfy.get("/queue") or {}
        pending = [item[1] for item in queue.get("queue_pending") or [] if isinstance(item, list) and len(item) > 1]
        running = [item[1] for item in queue.get("queue_running") or [] if isinstance(item, list) and len(item) > 1]
        elapsed = int(time.monotonic() - started)
        if prompt_id in pending:
            _progress(emit, 0.05, say(locale, f"ComfyUI 排队中(第 {pending.index(prompt_id) + 1} 位)",
                                      f"Queued in ComfyUI (#{pending.index(prompt_id) + 1})"))
            missing = 0
        elif prompt_id in running:
            _progress(emit, min(0.9, 0.15 + elapsed / 120.0), say(locale, f"ComfyUI 生成中(已用 {elapsed}s)",
                                                                  f"Generating in ComfyUI ({elapsed}s)"))
            missing = 0
        else:
            # 队列里没有、历史里也没有:ComfyUI 多半重启过,这个任务已经没了。给它几次机会
            # (刚提交的那一瞬间两边都可能还没登记)。
            missing += 1
            if missing >= 5:
                raise ComfyError(say(locale, f"ComfyUI 里已经找不到任务 {prompt_id}(它可能重启过)",
                                     f"ComfyUI no longer knows task {prompt_id} (it may have restarted)"))
        time.sleep(POLL_SECONDS)


def _open_socket(comfy: Comfy, client_id: str) -> WebSocket | None:
    try:
        return WebSocket(comfy.ws_url(client_id))
    except (OSError, WebSocketClosed, ValueError):
        return None


def generate(request: dict[str, Any], comfy: Comfy, locale: str, emit: Emit) -> dict[str, Any]:
    kind = str(request.get("kind") or "image")
    resume = request.get("resume")
    if isinstance(resume, dict) and resume.get("prompt_id"):
        # 接着等上一个进程提交过的那个任务。**不再提交**:它可能已经跑了一半,也可能已经跑完。
        prompt_id = str(resume["prompt_id"])
        _progress(emit, 0.05, say(locale, "接着等 ComfyUI 里的任务", "Resuming the ComfyUI task"))
        entry = _follow_poll(comfy, prompt_id, emit, locale)
    else:
        object_info = comfy.object_info()
        api, defaults = models.load(comfy, str(request.get("model") or ""), object_info, locale)
        prompt = graph.fill(api, _values(request, defaults), _overrides(request))
        uploaded = _upload(comfy, request.get("inputs") or [])
        if uploaded:
            prompt = graph.wire_images(prompt, graph.kind_of(prompt), uploaded)
        client_id = uuid.uuid4().hex
        # 先连 WebSocket 再提交:ComfyUI 只把事件推给**已经连着**的那个 clientId,晚连就错过开头。
        socket = _open_socket(comfy, client_id)
        try:
            prompt_id = _submit(comfy, prompt, client_id, locale)
            emit({"event": "task", "task": {"prompt_id": prompt_id, "client_id": client_id}})
            tracker = _Tracker(prompt, locale)
            _progress(emit, 0.02, tracker.message())
            if socket is not None:
                try:
                    entry = _follow_ws(comfy, socket, prompt_id, tracker, emit, locale)
                except WebSocketClosed:
                    entry = _follow_poll(comfy, prompt_id, emit, locale)
            else:
                entry = _follow_poll(comfy, prompt_id, emit, locale)
        finally:
            if socket is not None:
                socket.close()
    files = graph.collect_outputs(entry, kind)
    if not files:
        raise ComfyError(say(locale, "ComfyUI 跑完了,但没有产出文件 —— 工作流里需要一个保存节点(SaveImage 或视频合成)",
                             "ComfyUI finished but produced no files. The workflow needs a save node (SaveImage or a video combine node)."))
    out_dir = Path(os.environ["MOSAEL_PLUGIN_OUTPUT_DIR"])
    outputs: list[dict[str, str]] = []
    for index, item in enumerate(files, start=1):
        suffix = Path(str(item["filename"])).suffix or (".mp4" if kind == "video" else ".png")
        target = out_dir / f"comfyui-{index:02d}{suffix}"
        comfy.download(item, target)
        outputs.append({"path": target.name})
    usage = {"videos": 1} if kind == "video" else {"images": len(outputs)}
    return {"outputs": outputs, "usage": usage, "raw": {"prompt_id": prompt_id}}
