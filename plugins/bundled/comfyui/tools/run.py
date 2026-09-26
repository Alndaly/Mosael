"""在 ComfyUI 上跑一张图:传素材、提交、看进度、能取消、能接着等、取回产出。

两条路共用这里:**替宿主做一次生成**(`generate`,见 docs/PLUGIN_MANIFEST 的「替宿主做生成」)和
**跑一张工作流**(每张工作流自己的工具,见 tooling.py)。这一侧只做三件宿主做不了的事:

- **说出进度**:WebSocket 上的真实进度(哪个节点、第几步),连不上就退回轮询 `/history` / `/queue`;
- **停下远端**:宿主建了取消文件,就把这一个任务从 ComfyUI 里停掉 —— 在跑的 `/interrupt`,
  在排队的从队列里删掉。不去停的话,ComfyUI 会把它跑完,占着显卡,而结果没人要;
- **交回回执**:提交拿到 `prompt_id` 就交给宿主,宿主落库。后端重启后带着它再来,这里接着等,不再提交。
"""

from __future__ import annotations

import json
import os
import random
import re
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


def cancelled() -> bool:
    path = os.environ.get("MOSAEL_PLUGIN_CANCEL_FILE", "")
    return bool(path) and os.path.exists(path)


def progress(emit: Emit, fraction: float, message: str) -> None:
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


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def values_from(prompt: Any, negative: Any, parameters: dict[str, Any], defaults: dict[str, Any], *,
                keep_seed: bool = False) -> dict[str, Any]:
    """宿主主控件的那几样。**只放给了的**(和占位符的默认值)—— 没选尺寸就不改这张图的尺寸。

    提示词、反向提示词空着是「没写」:用这张图自己存着的那句(内置图和粘贴的模板由占位符的默认值兜底),
    不是把它清成空串 —— 宿主对没填的反向提示词发的就是空串。
    """
    values: dict[str, Any] = dict(defaults)
    for key, text in (("prompt", prompt), ("negative", negative)):
        if isinstance(text, str) and text.strip():
            values[key] = text
    # 种子:用户没给就每次随机 —— 通过 API 提交时同一个种子会得到同一张图(ComfyUI 还会整张命中缓存),
    # 而界面上的「每次生成后随机」只是 ComfyUI 前端的行为,API 那一侧没有。`keep_seed` 时留着图里存的。
    seed = parameters.get("seed")
    if _number(seed):
        values["seed"] = int(seed)
    elif not keep_seed:
        values["seed"] = random.randint(0, 2**31 - 1)
    size = _size(parameters.get("size"))
    if size:
        values["width"], values["height"] = size
    for key in ("width", "height"):
        if _number(parameters.get(key)):
            values[key] = int(parameters[key])
    for key in ("steps", "duration_seconds"):
        if _number(parameters.get(key)):
            values[key] = parameters[key]
    if _number(parameters.get("num_images")):
        values["batch"] = int(parameters["num_images"])
    return values


def overrides_from(parameters: dict[str, Any]) -> dict[str, Any]:
    """参数表里动过的那些(`<节点 id>.<输入名>`)。宿主词汇的键(seed / size …)不在这里。"""
    return {key: value for key, value in (parameters or {}).items() if "." in key}


def upload(comfy: Comfy, inputs: list[dict[str, str]]) -> dict[str, list[str]]:
    """把输入素材传上去,按角色记下 ComfyUI 那边的名字(读素材的节点填的就是它)。"""
    uploaded: dict[str, list[str]] = {}
    for item in inputs:
        source = Path(item["path"])
        name = f"mosael-{uuid.uuid4().hex[:8]}-{_safe_name(source.name)}"
        uploaded.setdefault(item["role"], []).append(comfy.upload_image(source, name))
    return uploaded


def _safe_name(name: str) -> str:
    """ComfyUI 的 input 目录里的文件名:去掉路径分隔、控制字符和引号(它要放进 multipart 头里的
    `filename="…"`),留后缀。"""
    cleaned = re.sub(r"[\\/\x00-\x1f\"]+", "_", name).strip() or "input"
    return cleaned[-80:]


def submit(comfy: Comfy, prompt: dict[str, Any], client_id: str, locale: str) -> str:
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


def stop(comfy: Comfy, prompt_id: str) -> None:
    """停下这一个任务:在跑就 /interrupt,在排队就从队列里删。

    先看队列再动手:`/interrupt` 停的是**正在跑的那个**,不管它是谁的 —— 同一台 ComfyUI 上别人的
    任务不该因为我这边取消而被掐掉。看不了队列(老版本 / 网络抖一下)才两样都做。
    """
    try:
        running_ids, pending_ids = comfy.queue()
        running, pending = set(running_ids), set(pending_ids)
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
    """把 ComfyUI 的事件折算成一个比例和一句话:「采样 12/20 · 第 3/9 个节点」。

    节点叫什么用**界面上的名字**(用户起的标题,没有就是类名):一张图里两个 KSampler,只说
    「KSampler」分不清是哪一个在跑。
    """

    def __init__(self, prompt: dict[str, Any], locale: str, titles: dict[str, str] | None = None) -> None:
        self.prompt = prompt
        self.total = max(1, len(prompt))
        self.names = {
            node_id: (titles or {}).get(node_id) or str((node.get("_meta") or {}).get("title") or "")
            or str(node.get("class_type", ""))
            for node_id, node in prompt.items()
        }
        self.done: set[str] = set()
        self.current = ""
        self.step = 0.0
        self.locale = locale
        self.started = False

    def fraction(self) -> float:
        return 0.05 + 0.9 * min(1.0, (len(self.done) + self.step) / self.total)

    def message(self, detail: str = "") -> str:
        if not self.started:
            return say(self.locale, "ComfyUI 排队中", "Queued in ComfyUI")
        name = self.names.get(self.current, "")
        if not name:
            return say(self.locale, "ComfyUI 生成中", "Generating in ComfyUI")
        where = min(self.total, len(self.done) + 1)
        position = say(self.locale, f"第 {where}/{self.total} 个节点", f"node {where}/{self.total}")
        return f"{name} {detail} · {position}" if detail else f"{name} · {position}"

    def enter(self, node: str) -> None:
        self.started = True
        if self.current and self.current != node:
            self.done.add(self.current)
        self.current, self.step = node, 0.0


def _follow_ws(comfy: Comfy, socket: WebSocket, prompt_id: str, tracker: _Tracker, emit: Emit, locale: str) -> dict[str, Any]:
    """跟着 WebSocket 等到结束。几秒没消息就看一眼 /history(WebSocket 丢了消息也不至于等到天荒地老)。"""
    last_poll = time.monotonic()
    while True:
        if cancelled():
            stop(comfy, prompt_id)
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
                progress(emit, tracker.fraction(), tracker.message())
            elif kind == "execution_cached" and mine:
                tracker.started = True
                tracker.done.update(str(node) for node in data.get("nodes") or [])
                progress(emit, tracker.fraction(), tracker.message())
            elif kind == "executing" and mine:
                node = data.get("node")
                if node is None and data.get("prompt_id") == prompt_id:
                    entry = history_entry(comfy, prompt_id)
                    if entry:
                        return entry
                    continue
                tracker.enter(str(node))
                progress(emit, tracker.fraction(), tracker.message())
            elif kind == "progress" and mine:
                value, maximum = data.get("value"), data.get("max")
                if data.get("node") is not None and str(data["node"]) != tracker.current:
                    tracker.enter(str(data["node"]))
                if _number(value) and _number(maximum) and maximum:
                    tracker.step = min(1.0, value / maximum)
                    progress(emit, tracker.fraction(), tracker.message(f"{int(value)}/{int(maximum)}"))
            elif kind == "progress_state" and mine:
                # 新版 ComfyUI:一次报全部节点的状态。挑正在跑的那个说。
                for node_id, state in (data.get("nodes") or {}).items():
                    if not isinstance(state, dict):
                        continue
                    if state.get("state") == "finished":
                        tracker.done.add(str(node_id))
                    elif state.get("state") == "running":
                        if str(node_id) != tracker.current:
                            tracker.enter(str(node_id))
                        value, maximum = state.get("value"), state.get("max")
                        if _number(value) and _number(maximum) and maximum and maximum > 1:
                            tracker.step = min(1.0, value / maximum)
                            progress(emit, tracker.fraction(), tracker.message(f"{int(value)}/{int(maximum)}"))
            elif kind == "execution_error" and data.get("prompt_id") == prompt_id:
                raise failure(locale, str(data.get("node_type") or ""), str(data.get("exception_message") or ""),
                              tracker.prompt)
            elif kind == "execution_interrupted" and data.get("prompt_id") == prompt_id:
                raise ComfyError(say(locale, "ComfyUI 里这个任务被中断了", "The task was interrupted in ComfyUI"))
            elif kind == "execution_success" and data.get("prompt_id") == prompt_id:
                entry = history_entry(comfy, prompt_id)
                if entry:
                    return entry
            last_poll = time.monotonic()
            continue
        if time.monotonic() - last_poll >= QUIET_SECONDS:
            last_poll = time.monotonic()
            entry = history_entry(comfy, prompt_id)
            if entry:
                return entry


#: ComfyUI 的「这个输入是空的」:加载节点交出的东西里缺了这一块。最常见的是 checkpoint 文件里本来就没有
#: 文本编码器(或 VAE)—— Flux、Anima 这类模型的权重单独发,要在图里另加一个加载节点。
_MISSING_PART = re.compile(r"\b(clip|vae) input is invalid: None", re.IGNORECASE)


def failure(locale: str, node: str, said: str, api: dict[str, Any] | None) -> ComfyError:
    """ComfyUI 执行失败时给人看的那句。

    认得出的原因说人话、点名是哪个模型文件、说怎么办;认不出的照旧带上 ComfyUI 的原话。此前一律是
    「ComfyUI 执行失败:CLIPTextEncode: ERROR: clip input is invalid: None If the clip is from a checkpoint…」——
    用户在「模型」里挑了一个不带文本编码器的文件,读完这句也不知道是哪个文件、该换成什么。
    """
    missing = _MISSING_PART.search(said or "")
    if missing:
        files = graph.checkpoint_files(api or {})
        named_zh = "、".join(f"「{one}」" for one in files) or "图里加载的那个"
        named_en = ", ".join(f"“{one}”" for one in files) or "the one this graph loads"
        if missing.group(1).lower() == "clip":
            return ComfyError(say(
                locale,
                f"模型文件{named_zh}里没有文本编码器(CLIP),用普通的 checkpoint 加载节点读不出来 —— Flux、Anima 这类"
                "模型的文本编码器是单独的文件。换一个完整的 checkpoint;或者在 ComfyUI 里搭一张单独加载文本编码器的工作流"
                "并保存,再在 Mosael 里选那个工作流。",
                f"The model file {named_en} has no text encoder (CLIP), so a plain checkpoint loader can't read one. Models "
                "such as Flux or Anima ship their text encoder separately. Pick a complete checkpoint, or save a workflow in "
                "ComfyUI that loads the text encoder on its own and pick that workflow in Mosael.",
            ))
        return ComfyError(say(
            locale,
            f"模型文件{named_zh}里没有 VAE。换一个自带 VAE 的 checkpoint;或者在 ComfyUI 里给工作流加一个 VAE 加载节点"
            "并保存,再在 Mosael 里选那个工作流。",
            f"The model file {named_en} has no VAE. Pick a checkpoint with a baked-in VAE, or add a VAE loader to a "
            "workflow in ComfyUI, save it, and pick that workflow in Mosael.",
        ))
    text = f"{node}: {said}".strip(": ")
    return ComfyError(say(locale, f"ComfyUI 执行失败:{text or '详见 ComfyUI 日志'}",
                          f"ComfyUI execution failed: {text or 'see the ComfyUI log'}"))


def history_entry(comfy: Comfy, prompt_id: str) -> dict[str, Any] | None:
    """这个任务跑完了吗:跑完了回它的那一条历史,失败了直接说原因,还没完回 None。"""
    entry = comfy.history(prompt_id).get(prompt_id)
    if not entry:
        return None
    status = entry.get("status") or {}
    if status.get("status_str") == "error" and graph.interrupted(status):
        raise ComfyError(say(comfy.locale, "ComfyUI 里这个任务被中断了", "The task was interrupted in ComfyUI"))
    if status.get("status_str") == "error":
        node, said = graph.execution_error_parts(status) or ("", "")
        #: 历史条目里存着提交的那张图(`prompt` 的第三项):接着等上一个进程提交的任务时,手里只有它。
        submitted = entry.get("prompt")
        api = submitted[2] if isinstance(submitted, list) and len(submitted) > 2 and isinstance(submitted[2], dict) else {}
        raise failure(comfy.locale, node, said, api)
    if status.get("completed") or entry.get("outputs"):
        return entry
    return None


def follow_poll(comfy: Comfy, prompt_id: str, emit: Emit, locale: str, *, deadline: float | None = None) -> dict[str, Any] | None:
    """没有 WebSocket 时的等法:轮询历史和队列。只看得到排队和结束,中间按时间爬坡。

    给了 `deadline`(time.monotonic 的时刻)就只等到那时,没完回 None —— 智能体那一侧一次调用只等几分钟。
    """
    started = time.monotonic()
    missing = 0
    while True:
        if cancelled():
            stop(comfy, prompt_id)
            raise ComfyError(say(locale, "已取消", "Cancelled"))
        entry = history_entry(comfy, prompt_id)
        if entry:
            return entry
        running, pending = comfy.queue()
        elapsed = int(time.monotonic() - started)
        if prompt_id in pending:
            progress(emit, 0.05, say(locale, f"ComfyUI 排队中(第 {pending.index(prompt_id) + 1} 位)",
                                     f"Queued in ComfyUI (#{pending.index(prompt_id) + 1})"))
            missing = 0
        elif prompt_id in running:
            progress(emit, min(0.9, 0.15 + elapsed / 120.0), say(locale, f"ComfyUI 生成中(已用 {elapsed}s)",
                                                                 f"Generating in ComfyUI ({elapsed}s)"))
            missing = 0
        else:
            # 队列里没有、历史里也没有:ComfyUI 多半重启过,这个任务已经没了。给它几次机会
            # (刚提交的那一瞬间两边都可能还没登记)。
            missing += 1
            if missing >= 5:
                raise ComfyError(say(locale, f"ComfyUI 里已经找不到任务 {prompt_id}(它可能重启过)",
                                     f"ComfyUI no longer knows task {prompt_id} (it may have restarted)"))
        if deadline is not None and time.monotonic() >= deadline:
            return None
        time.sleep(POLL_SECONDS)


def _open_socket(comfy: Comfy, client_id: str) -> WebSocket | None:
    try:
        return WebSocket(comfy.ws_url(client_id), headers=comfy.headers)
    except (OSError, WebSocketClosed, ValueError):
        return None


def run_prompt(comfy: Comfy, prompt: dict[str, Any], emit: Emit, locale: str,
               titles: dict[str, str] | None = None) -> tuple[str, dict[str, Any] | None]:
    """提交一张填好的 API 图并等它跑完。返回 (任务号, 历史条目)。"""
    client_id = uuid.uuid4().hex
    # 先连 WebSocket 再提交:ComfyUI 只把事件推给**已经连着**的那个 clientId,晚连就错过开头。
    socket = _open_socket(comfy, client_id)
    try:
        prompt_id = submit(comfy, prompt, client_id, locale)
        emit({"event": "task", "task": {"prompt_id": prompt_id, "client_id": client_id}})
        tracker = _Tracker(prompt, locale, titles)
        progress(emit, 0.02, tracker.message())
        if socket is not None:
            try:
                return prompt_id, _follow_ws(comfy, socket, prompt_id, tracker, emit, locale)
            except WebSocketClosed:
                pass
        return prompt_id, follow_poll(comfy, prompt_id, emit, locale)
    finally:
        if socket is not None:
            socket.close()


_DEFAULT_SUFFIX = {"image": ".png", "video": ".mp4", "audio": ".wav"}
#: 用量按宿主的计量单位记(见 ai/providers/contracts/generation.metering_from_request)。
_USAGE_UNITS = {"image": "images", "video": "videos", "audio": "audios"}


def download(comfy: Comfy, files: list[dict[str, Any]], stem: str) -> list[dict[str, Any]]:
    """把产出取回到 MOSAEL_PLUGIN_OUTPUT_DIR,交回宿主认得的 artifact 项(`path` + 给人看的名字)。"""
    out_dir = Path(os.environ["MOSAEL_PLUGIN_OUTPUT_DIR"])
    stem = re.sub(r"[^\w.-]+", "-", stem).strip("-.")[:60] or "comfyui"
    artifacts: list[dict[str, Any]] = []
    for index, one in enumerate(files, start=1):
        item = one["item"]
        original = Path(str(item["filename"])).name
        suffix = Path(original).suffix or _DEFAULT_SUFFIX.get(one.get("media", ""), ".bin")
        target = out_dir / f"{stem}-{index:02d}{suffix}"
        comfy.download(item, target)
        artifacts.append({"path": target.name, "filename": original or target.name, "node": one.get("node", ""),
                          "media": one.get("media", "")})
    return artifacts


def generate(request: dict[str, Any], comfy: Comfy, locale: str, emit: Emit) -> dict[str, Any]:
    kind = str(request.get("kind") or "image")
    resume = request.get("resume")
    if isinstance(resume, dict) and resume.get("prompt_id"):
        # 接着等上一个进程提交过的那个任务。**不再提交**:它可能已经跑了一半,也可能已经跑完。
        prompt_id = str(resume["prompt_id"])
        progress(emit, 0.05, say(locale, "接着等 ComfyUI 里的任务", "Resuming the ComfyUI task"))
        entry = follow_poll(comfy, prompt_id, emit, locale)
    else:
        object_info = comfy.object_info()
        api, defaults, titles = models.load(comfy, str(request.get("model") or ""), object_info, locale)
        parameters = request.get("parameters") or {}
        # 提示词空着 = 用这张图自己存着的那句(模型声明了 `prompt: optional`,见 graph.prompt_requirement)
        values = values_from(request.get("prompt"), request.get("negative_prompt"), parameters, defaults)
        prompt = graph.fill(api, values, overrides_from(parameters))
        uploaded = upload(comfy, request.get("inputs") or [])
        if uploaded:
            prompt = graph.wire_inputs(prompt, graph.kind_of(prompt), uploaded)
        prompt_id, entry = run_prompt(comfy, prompt, emit, locale, titles)
    files = [{"item": item, "media": kind} for item in graph.collect_outputs(entry or {}, kind)]
    if not files:
        raise ComfyError(say(locale, "ComfyUI 跑完了,但没有产出文件 —— 工作流里需要一个保存节点(SaveImage 或视频合成)",
                             "ComfyUI finished but produced no files. The workflow needs a save node (SaveImage or a video combine node)."))
    outputs = [{"path": one["path"]} for one in download(comfy, files, "comfyui")]
    usage = {_USAGE_UNITS.get(kind, "images"): len(outputs)}
    return {"outputs": outputs, "usage": usage, "raw": {"prompt_id": prompt_id}}
