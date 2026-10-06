"""在 ComfyUI 上跑一张图:传素材、提交、看进度、能取消、能接着等、取回产出。

两条路共用这里:**替宿主做一次生成**(`generate`,见 docs/PLUGIN_MANIFEST 的「替宿主做生成」)和
**跑一张工作流**(每张工作流自己的工具,见 tooling.py)。这一侧只做三件宿主做不了的事:

- **说出进度**:WebSocket 上的真实进度(哪个节点、第几步),连不上就退回轮询 `/history` / `/queue`;
- **停下远端**:宿主建了取消文件,就把这一个任务从 ComfyUI 里停掉 —— 在跑的 `/interrupt`,
  在排队的从队列里删掉。不去停的话,ComfyUI 会把它跑完,占着显卡,而结果没人要;
- **交回回执**:提交拿到 `prompt_id` 就交给宿主,宿主落库。后端重启后带着它再来,这里接着等,不再提交。

宿主还可以带着**工作台画布上现在这张图**来(`graph`,ADR 0038 §6):不从文件读、直接提交,`client_id` 用前端的那个
(画布上照常亮起正在跑的节点),`extra_pnginfo.workflow` 带上界面格式(产出拖回 ComfyUI 有布局);只按历史轮询跟到完成,
不另开 WebSocket 去抢那个 `client_id`(ComfyUI 一个 `client_id` 只留一条连接,后连的会把画布那条挤掉)。
"""

from __future__ import annotations

import json
import os
import random
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable, NamedTuple

import app_form
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


_SIZE_TEXT = re.compile(r"^\s*(\d+)\s*[x×*]\s*(\d+)\s*$", re.IGNORECASE)


def _size(value: Any) -> tuple[int, int] | None:
    """「宽x高」(`768x1024`、`768 × 1024`、`768*1024` 都认)→ 每边取整到 8 的倍数(graph.snap_side)。"""
    found = _SIZE_TEXT.match(str(value or ""))
    if not found:
        return None
    return graph.snap_side(found.group(1)), graph.snap_side(found.group(2))


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
            values[key] = graph.snap_side(parameters[key])
    for key in ("steps", "duration_seconds"):
        if _number(parameters.get(key)):
            values[key] = parameters[key]
    return values


def runs_from(parameters: dict[str, Any]) -> int:
    """「张数」= 跑几遍(见 graph.counts_runs):没给是一遍,最多 graph.MAX_RUNS 遍。"""
    runs = parameters.get("num_images")
    return min(max(int(runs), 1), graph.MAX_RUNS) if _number(runs) else 1


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


#: 加载节点读的模型文件:输入名以 `_name` 结尾(ckpt_name、lora_name、unet_name、vae_name、clip_name、model_name …)、
#: 值带着这几种后缀。值不在 ComfyUI 给的可选值里,就是那台机器上没有这个文件。
_MODEL_SUFFIXES = (".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf", ".sft", ".onnx")
#: 一句话里最多点几个名字(一张大图缺十几个节点时,后面的用「等 n 个」带过)。
_MAX_NAMED = 8


def _options(definition: Any) -> list[str] | None:
    """一个下拉的可选值;**不是下拉**(STRING 这类)是 None。空的下拉是 `[]` —— 那个目录里一个文件都没有(刚装的 ComfyUI
    的 upscale_models),选了什么都没有,不是「不判」。"""
    if not isinstance(definition, list) or not definition:
        return None
    if isinstance(definition[0], list):
        return [str(one) for one in definition[0]]
    extra = definition[1] if len(definition) > 1 and isinstance(definition[1], dict) else {}
    return [str(one) for one in extra.get("options") or []] if definition[0] == "COMBO" else None


def _same_file(name: str) -> str:
    """模型文件名比较时不分 / 和 \\(Windows 上的 ComfyUI 列子目录用反斜杠,别处存的工作流用斜杠)。"""
    return name.replace("\\", "/")


def missing(prompt: dict[str, Any], object_info: dict[str, Any]) -> tuple[list[str], list[str]]:
    """这张图要、这台 ComfyUI 上没有的东西:(没装的节点类型, 「模型文件(#节点 类型 · 输入名)」)。"""
    nodes: list[str] = []
    files: list[str] = []
    for node_id in sorted(prompt, key=graph._node_order):  # noqa: SLF001 — 同一个插件里的模块
        node = prompt[node_id]
        class_type = str(node.get("class_type", ""))
        if class_type not in object_info:
            if class_type not in nodes:
                nodes.append(class_type)
            continue
        defs = graph._input_defs(object_info, class_type)  # noqa: SLF001
        for name, value in (node.get("inputs") or {}).items():
            if not (isinstance(value, str) and name.endswith("_name") and value.lower().endswith(_MODEL_SUFFIXES)):
                continue
            choices = _options(defs.get(name))
            if choices is not None and _same_file(value) not in {_same_file(one) for one in choices}:
                files.append(f"「{value}」(#{node_id} {class_type} · {name})")
    return nodes, files


def _named(names: list[str], sep: str) -> str:
    shown = sep.join(names[:_MAX_NAMED])
    return shown if len(names) <= _MAX_NAMED else f"{shown}{sep}… ({len(names)})"


def preflight(prompt: dict[str, Any], object_info: dict[str, Any], locale: str) -> None:
    """提交之前看一眼:这张图要的节点、模型文件这台 ComfyUI 上有没有。缺的**一次说全**,什么都不排上。

    ComfyUI 自己每次只说第一个没装的节点(「Node 'X' not found. The custom node may not be installed.」),装好一个才知道
    下一个;缺模型文件时回一句英文的「Value not in list」,有的加载节点还要执行到它才说找不到。不知道节点定义
    (object_info 拿不到)就不判,交给 ComfyUI 去说。"""
    if not object_info:
        return
    nodes, files = missing(prompt, object_info)
    zh: list[str] = []
    en: list[str] = []
    if nodes:
        zh.append(f"这台 ComfyUI 没装这张工作流用到的节点:{_named(nodes, '、')}。它们多半来自没装的自定义节点包 —— 在 ComfyUI "
                  "的 Manager 里「安装缺失的节点」、重启 ComfyUI 再试。")
        en.append(f"This ComfyUI doesn't have the nodes this workflow uses: {_named(nodes, ', ')}. They most likely come from "
                  "custom node packs that aren't installed; install them from ComfyUI Manager (Install Missing Custom Nodes), "
                  "restart ComfyUI and try again.")
    if files:
        zh.append(f"这台 ComfyUI 上没有这张工作流要的模型文件:{_named(files, '、')}。把文件放进 ComfyUI 对应的模型目录,"
                  "或者在参数里换成已有的文件再试。")
        en.append(f"This ComfyUI doesn't have the model files this workflow needs: {_named(files, ', ')}. Put them in the "
                  "matching ComfyUI models folder, or pick a file it has in the parameters, and try again.")
    if zh:
        raise ComfyError(say(locale, "".join(zh), " ".join(en)))


def submit(comfy: Comfy, prompt: dict[str, Any], client_id: str, locale: str,
           extra_data: dict[str, Any] | None = None) -> str:
    body: dict[str, Any] = {"prompt": prompt, "client_id": client_id}
    if extra_data:
        body["extra_data"] = extra_data
    try:
        answer = comfy.post("/prompt", body)
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
    if (answer or {}).get("node_errors"):
        # 一部分输出节点校验不过时 ComfyUI 照样排上,只跑过了的那几个:缺了 checkpoint 的出图那一路不跑,一个只预览
        # 参考图的节点照跑 —— 交回来的就成了那张预览。这张图没有按它本来的样子跑:说出原因,把排上的撤掉。
        stop(comfy, prompt_id)
        detail = graph.validation_errors({"node_errors": answer["node_errors"]})
        raise ComfyError(say(locale, f"ComfyUI 拒绝了这张工作流:{detail}", f"ComfyUI rejected the workflow: {detail}"))
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
#: ComfyUI 执行到加载节点才发现文件不在:「Model in folder 'checkpoints' with filename '…' not found.」
_MISSING_FILE = re.compile(r"Model in folder '([^']+)' with filename '([^']+)' not found", re.IGNORECASE)


def failure(locale: str, node: str, said: str, api: dict[str, Any] | None) -> ComfyError:
    """ComfyUI 执行失败时给人看的那句。

    认得出的原因说人话、点名是哪个模型文件、说怎么办;认不出的照旧带上 ComfyUI 的原话。此前一律是
    「ComfyUI 执行失败:CLIPTextEncode: ERROR: clip input is invalid: None If the clip is from a checkpoint…」——
    用户在「模型」里挑了一个不带文本编码器的文件,读完这句也不知道是哪个文件、该换成什么。
    """
    absent = _MISSING_FILE.search(said or "")
    if absent:
        folder, name = absent.groups()
        return ComfyError(say(
            locale,
            f"ComfyUI 上没有模型文件「{name}」({folder} 目录)。把它放进 ComfyUI 的 models/{folder},或者在参数里换成已有的"
            "文件再试。",
            f"ComfyUI doesn't have the model file “{name}” (folder {folder}). Put it in ComfyUI's models/{folder}, or pick a "
            "file it has in the parameters, and try again.",
        ))
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
               titles: dict[str, str] | None = None, receipt: dict[str, Any] | None = None
               ) -> tuple[str, dict[str, Any] | None]:
    """提交一张填好的 API 图并等它跑完。返回 (任务号, 历史条目)。`receipt` 是回执里多记的东西(循环到第几次)。"""
    client_id = uuid.uuid4().hex
    # 先连 WebSocket 再提交:ComfyUI 只把事件推给**已经连着**的那个 clientId,晚连就错过开头。
    socket = _open_socket(comfy, client_id)
    try:
        prompt_id = submit(comfy, prompt, client_id, locale)
        emit({"event": "task", "task": {"prompt_id": prompt_id, "client_id": client_id, **(receipt or {})}})
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


class Repeated(NamedTuple):
    """跑 N 遍的结果:跑出来的那几遍 (任务号, 历史条目, 种子),和没出来的那几遍 (第几遍, 原因)。"""

    runs: list[tuple[str, dict[str, Any], int]]
    failures: list[tuple[int, str]]
    count: int


def run_repeated(comfy: Comfy, build: Callable[[int], dict[str, Any]], count: int, given_seed: int | None, emit: Emit,
                 locale: str, titles: dict[str, str] | None, resume: dict[str, Any] | None = None) -> Repeated:
    """跑 N 遍(「张数」,见 graph.counts_runs):循环提交 N 次,每次换一个种子 —— 给了种子就从它开始依次 +1,没给就
    每次随机。每遍按工作流原样,一遍出几张是它自己的批量。

    `build(种子)` 交回这一次要提交的图。一次一次来(跑完一遍再提交下一遍,不往 ComfyUI 的队列里灌);取消了剩下的
    不再提交,在跑的那一次由 run_prompt 停下。某一次失败不拖垮别的:记下原因接着跑,出来的照样交回。
    回执里记着这是第几次、前面几次的任务号和种子(`repeat`):后端重启后带着它回来,接着等在跑的那一次,剩下的照常提交。
    """
    state = (resume or {}).get("repeat") if isinstance(resume, dict) else None
    seeds: list[int] = [int(one) for one in (state or {}).get("seeds") or []]
    done: list[str] = [str(one) for one in (state or {}).get("done") or []]
    runs: list[tuple[str, dict[str, Any], int]] = []
    failures: list[tuple[int, str]] = []

    def step_emit(index: int) -> Emit:
        def relay(event: dict[str, Any]) -> None:
            if event.get("event") == "progress":
                share = (index + float(event.get("progress") or 0)) / count
                head = say(locale, f"第 {index + 1}/{count} 遍", f"Run {index + 1}/{count}")
                event = {**event, "progress": round(min(0.95, share), 4), "message": f"{head} · {event.get('message', '')}"}
            emit(event)
        return relay

    def settle(index: int, prompt_id: str, waiting: Callable[[], dict[str, Any] | None]) -> None:
        try:
            entry = waiting()
        except ComfyError as exc:
            if cancelled():
                raise
            failures.append((index + 1, str(exc)))
            return
        if entry:
            runs.append((prompt_id, entry, seeds[index]))

    for index, prompt_id in enumerate(done):  # 重启之前已经跑完的那几次:历史里取
        settle(index, prompt_id, lambda pid=prompt_id: history_entry(comfy, pid))
    start = len(done)
    if state and resume.get("prompt_id"):  # 重启时在跑的那一次:接着等,不再提交
        current = str(resume["prompt_id"])
        settle(start, current, lambda: follow_poll(comfy, current, step_emit(start), locale))
        done.append(current)
        start += 1
    for index in range(start, count):
        if cancelled():
            raise ComfyError(say(locale, "已取消", "Cancelled"))
        seed = given_seed + index if given_seed is not None else random.randint(0, 2**31 - 1)
        seeds = seeds[:index] + [seed]
        prompt = build(seed)
        receipt = {"repeat": {"count": count, "index": index, "done": list(done), "seeds": list(seeds)}}
        try:
            prompt_id, entry = run_prompt(comfy, prompt, step_emit(index), locale, titles, receipt=receipt)
        except ComfyError as exc:
            if cancelled():
                raise
            failures.append((index + 1, str(exc)))
            continue
        done.append(prompt_id)
        if entry:
            runs.append((prompt_id, entry, seed))
    return Repeated(runs, failures, count)


def repeat_note(result: Repeated, locale: str) -> str:
    """有几遍没出来时给人看的那一句:跑了几遍、出来了几遍、哪几遍没出来、为什么。都出来了是空串。"""
    if not result.failures:
        return ""
    which = "、".join(str(index) for index, _ in result.failures)
    reasons = ";".join(dict.fromkeys(reason for _, reason in result.failures))
    return say(locale, f"跑了 {result.count} 遍,出来 {len(result.runs)} 遍;第 {which} 遍没出来:{reasons}",
               f"{len(result.runs)} of {result.count} runs came out; run {which.replace('、', ', ')} failed: {reasons}")


def generate(request: dict[str, Any], comfy: Comfy, locale: str, emit: Emit) -> dict[str, Any]:
    kind = str(request.get("kind") or "image")
    resume = request.get("resume")
    #: 「结果取自」(见 graph._output_choice):没选就是缺省的「最终结果」,中间一步的预览不交回、不跑;选了一个节点
    #: 只要它的;「全部」是这一种交回的每一个。
    choice = str((request.get("parameters") or {}).get(graph.OUTPUT_CHOICE) or "")
    if isinstance(resume, dict) and resume.get("prompt_id") and not resume.get("repeat"):
        # 接着等上一个进程提交过的那个任务。**不再提交**:它可能已经跑了一半,也可能已经跑完。提交的那张图已经按
        # 「结果取自」摘过了,交回它跑出来的;选了一个节点的照旧只认它的。
        wanted = {choice} if choice not in ("", graph.ALL_OUTPUTS, graph.FINAL_OUTPUTS) else None
        prompt_id = str(resume["prompt_id"])
        progress(emit, 0.05, say(locale, "接着等 ComfyUI 里的任务", "Resuming the ComfyUI task"))
        entry = follow_poll(comfy, prompt_id, emit, locale)
    elif isinstance(request.get("graph"), dict):
        return _generate_canvas(request["graph"], comfy, locale, emit, kind)
    else:
        object_info = comfy.object_info()
        model_id = str(request.get("model") or "")
        api, defaults, titles, marks = models.load(comfy, model_id, object_info, locale)
        form = app_form.resolve(marks, api, object_info, titles)[0]
        parameters = request.get("parameters") or {}
        if form.app:
            # 有应用表单时只认表单里的键(ADR 0038 §4):画板格子、工作流节点里存着的旧键不再写进图 —— 没挑的项照工作流原样跑
            allowed = set(graph.describe(model_id, "", api, object_info, titles, form)["parameters"])
            parameters = {key: value for key, value in parameters.items() if key in allowed}
        # 提示词空着 = 用这张图自己存着的那句(模型声明了 `prompt: optional`,见 graph.prompt_requirement)。应用表单里
        # 没挑种子的:照工作流自己的设定(固定的留着,每次随机的换一个),不再每次换一个
        values = values_from(request.get("prompt"), request.get("negative_prompt"), parameters, defaults,
                             keep_seed=form.app and not form.graph_item("seed"))
        # 「张数」是跑几遍(见 graph.counts_runs),缺省一遍;每遍按工作流原样,画布上存着的 batch_size 照旧 ——
        # 宿主照目录说的「跑几遍 × 一遍几张」摆占位,做的是同一件事。
        runs = runs_from(parameters)
        wanted = graph.chosen_outputs(api, kind, choice, object_info, titles, locale, form.results)
        if isinstance(resume, dict) and resume.get("repeat") or (runs > 1 and graph.counts_runs(api)):
            # 跑 N 遍:循环提交 N 次(重启时带着循环的回执回来,接着跑)
            return _generate_repeated(request, comfy, locale, emit, kind, wanted, runs,
                                      (object_info, api, titles, values, parameters, form))
        prompt = graph.fill(api, values, overrides_from(parameters), object_info, form.prompts())
        if wanted is not None:
            prompt = graph.keep_outputs(prompt, kind, wanted, object_info, titles)
        preflight(prompt, object_info, locale)
        uploaded = upload(comfy, request.get("inputs") or [])
        if uploaded:
            prompt = graph.wire_inputs(prompt, graph.kind_of(prompt), uploaded, form.slots() if form.app else None)
        prompt_id, entry = run_prompt(comfy, prompt, emit, locale, titles)
    return _delivered(comfy, entry, kind, wanted, prompt_id, locale)


def _delivered(comfy: Comfy, entry: dict[str, Any] | None, kind: str, wanted: set[str] | None, prompt_id: str,
               locale: str) -> dict[str, Any]:
    """跑完的这一次交回什么:这一种的产出(`wanted` 只要那几个节点的),取回到本地,每份带上它来自的节点。"""
    files = graph.collect_outputs(entry or {}, kind, wanted)
    if not files:
        raise ComfyError(say(locale, "ComfyUI 跑完了,但没有产出文件 —— 工作流里需要一个保存节点(SaveImage 或视频合成)",
                             "ComfyUI finished but produced no files. The workflow needs a save node (SaveImage or a video combine node)."))
    # 每份产出带上它来自的节点(ADR 0038 §5):宿主记进生成记录和素材的生成参数。不叫 `output_node` —— 那是「结果取自」
    # 的参数键,记进去之后「用同样的参数再来一次」会被当成选了那一个节点
    outputs = [{"path": one["path"], "parameters": {"source_node": one["node"]}}
               for one in download(comfy, [{**one, "media": kind} for one in files], "comfyui")]
    usage = {_USAGE_UNITS.get(kind, "images"): len(outputs)}
    return {"outputs": outputs, "usage": usage, "raw": {"prompt_id": prompt_id}}


#: 前端的 clientId:ComfyUI 前端自己生成的一串(uuid 去掉横线,或带横线);认不出就换成我们自己的。
_CLIENT_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


def _generate_canvas(canvas: dict[str, Any], comfy: Comfy, locale: str, emit: Emit, kind: str) -> dict[str, Any]:
    """跑工作台画布上现在这张(ADR 0038 §6,含没存的改动):宿主给的是前端 `graphToPrompt` 出来的 API 图、界面格式、前端的
    `clientId`。不读文件、不填参数(画布上就是用户要的样子),提交之前照样查一遍缺的节点和模型;只按历史轮询跟到完成 ——
    不开 WebSocket,免得把画布那条连接挤掉(细进度工作台自己看前端的事件)。交回这一种的**全部**产出、各带来自哪个节点:
    工作台按节点分组摆出来,用户在那里挑「以后只要这张」。"""
    prompt = canvas.get("prompt")
    if not isinstance(prompt, dict) or not prompt or not all(
            isinstance(node, dict) and isinstance(node.get("class_type"), str) and isinstance(node.get("inputs"), dict)
            for node in prompt.values()):
        raise ComfyError(say(locale, "画布上的图形状不对,没有提交", "The canvas graph is malformed; nothing was submitted."))
    workflow = canvas.get("workflow")
    client_id = str(canvas.get("client_id") or "")
    if not _CLIENT_ID.match(client_id):
        client_id = uuid.uuid4().hex
    preflight(prompt, comfy.object_info(), locale)
    extra = ({"extra_pnginfo": {"workflow": workflow}}
             if isinstance(workflow, dict) and isinstance(workflow.get("nodes"), list) else None)
    prompt_id = submit(comfy, prompt, client_id, locale, extra)
    emit({"event": "task", "task": {"prompt_id": prompt_id, "client_id": client_id}})
    progress(emit, 0.02, say(locale, "已交给 ComfyUI(画布上这张)", "Submitted to ComfyUI (the canvas graph)"))
    entry = follow_poll(comfy, prompt_id, emit, locale)
    return _delivered(comfy, entry, kind, None, prompt_id, locale)


def _generate_repeated(request: dict[str, Any], comfy: Comfy, locale: str, emit: Emit, kind: str,
                       wanted: set[str] | None, runs: int,
                       loaded: tuple[dict[str, Any], dict[str, Any], dict[str, str], dict[str, Any], dict[str, Any],
                                     graph.Form],
                       ) -> dict[str, Any]:
    """跑 N 遍:循环提交 N 次(run_repeated),每份产出带着它那一遍用的种子和它来自的节点;有几遍没出来时说明一句。

    `loaded` 是 generate 已经取好的 (object_info, 图, 节点名字, 主控件的值, 参数表, 表单),不再拉第二遍。"""
    object_info, api, titles, values, parameters, form = loaded
    given = int(parameters["seed"]) if _number(parameters.get("seed")) else None
    overrides = overrides_from(parameters)
    uploaded: dict[str, list[str]] | None = None

    def build(seed: int) -> dict[str, Any]:
        nonlocal uploaded
        prompt = graph.fill(api, {**values, "seed": seed}, overrides, object_info, form.prompts())
        if wanted is not None:
            prompt = graph.keep_outputs(prompt, kind, wanted, object_info, titles)
        if uploaded is None:  # 第一次提交之前查一遍、传一次素材,之后每次都接这一份
            preflight(prompt, object_info, locale)
            uploaded = upload(comfy, request.get("inputs") or [])
        if not uploaded:
            return prompt
        return graph.wire_inputs(prompt, graph.kind_of(prompt), uploaded, form.slots() if form.app else None)

    result = run_repeated(comfy, build, runs, given, emit, locale, titles, request.get("resume"))
    if not result.runs:
        raise ComfyError(result.failures[0][1] if result.failures else say(locale, "一遍都没出来", "No run came out"))
    files: list[dict[str, Any]] = []
    seeds: list[int] = []
    for _, entry, seed in result.runs:
        for one in graph.collect_outputs(entry, kind, wanted):
            files.append({**one, "media": kind})
            seeds.append(seed)
    if not files:
        raise ComfyError(say(locale, "ComfyUI 跑完了,但没有产出文件 —— 工作流里需要一个保存节点(SaveImage 或视频合成)",
                             "ComfyUI finished but produced no files. The workflow needs a save node (SaveImage or a video combine node)."))
    outputs = [{"path": one["path"], "parameters": {"seed": seed, "source_node": one["node"]}}
               for one, seed in zip(download(comfy, files, "comfyui"), seeds, strict=True)]
    output: dict[str, Any] = {
        "outputs": outputs,
        "usage": {_USAGE_UNITS.get(kind, "images"): len(outputs)},
        "raw": {"prompt_ids": [prompt_id for prompt_id, _, _ in result.runs], "seeds": [seed for _, _, seed in result.runs]},
    }
    note = repeat_note(result, locale)
    if note:
        output["note"] = note
    return output
