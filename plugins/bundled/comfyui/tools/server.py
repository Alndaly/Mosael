"""这台 ComfyUI 本身:状态(显卡、版本、队列)、装了哪些模型文件,以及三个会动它的操作。

`interrupt` / `clear_queue` / `free_memory` **会改变服务器的状态**,所以清单里不标只读、默认不开放给
智能体(见 mosael.plugin.json 的 recommended):清队列会把同一台机器上别人排着的任务一起清掉,
那是用户自己该决定的事。
"""

from __future__ import annotations

from typing import Any

from comfy_http import Comfy
from lines import ComfyError, say

#: `/models` 不在时(老版本 ComfyUI),从这些加载节点的下拉里认出模型文件 —— 下拉的可选值就是那个目录里的文件。
_LOADER_FIELDS: dict[str, tuple[str, str]] = {
    "checkpoints": ("CheckpointLoaderSimple", "ckpt_name"),
    "loras": ("LoraLoader", "lora_name"),
    "vae": ("VAELoader", "vae_name"),
    "upscale_models": ("UpscaleModelLoader", "model_name"),
    "controlnet": ("ControlNetLoader", "control_net_name"),
    "diffusion_models": ("UNETLoader", "unet_name"),
    "text_encoders": ("CLIPLoader", "clip_name"),
    "clip_vision": ("CLIPVisionLoader", "clip_name"),
    "style_models": ("StyleModelLoader", "style_model_name"),
}
#: 一个目录最多列多少个文件名。
_MAX_FILES = 500
_GB = 1024 ** 3


def _gb(value: Any) -> float | None:
    return round(float(value) / _GB, 2) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def server_status(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    stats = comfy.system_stats()
    system = stats.get("system") or {}
    devices = [
        {
            "name": str(device.get("name") or ""),
            "type": str(device.get("type") or ""),
            "vram_total_gb": _gb(device.get("vram_total")),
            "vram_free_gb": _gb(device.get("vram_free")),
        }
        for device in stats.get("devices") or []
        if isinstance(device, dict)
    ]
    running, pending = comfy.queue()
    gpu = devices[0] if devices else None
    free = f"{gpu['vram_free_gb']} / {gpu['vram_total_gb']} GB" if gpu and gpu["vram_total_gb"] is not None else ""
    head = " ".join(one for one in ("ComfyUI", str(system.get("comfyui_version") or "")) if one)
    summary = say(
        locale,
        f"{head}:在跑 {len(running)} 个,排队 {len(pending)} 个"
        + (f";{gpu['name']} 空闲显存 {free}" if gpu and free else ""),
        f"{head}: {len(running)} running, {len(pending)} queued"
        + (f"; {gpu['name']} free VRAM {free}" if gpu and free else ""),
    )
    return {
        "server": comfy.base,
        "comfyui_version": str(system.get("comfyui_version") or ""),
        "python_version": str(system.get("python_version") or ""),
        "pytorch_version": str(system.get("pytorch_version") or ""),
        "os": str(system.get("os") or ""),
        "ram_total_gb": _gb(system.get("ram_total")),
        "ram_free_gb": _gb(system.get("ram_free")),
        "devices": devices,
        "queue": {"running": len(running), "pending": len(pending), "running_ids": running, "pending_ids": pending},
        "summary": summary,
    }


def list_models(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    """装了哪些模型文件,按目录分(checkpoints / loras / vae / upscale_models / controlnet …)。"""
    wanted = str(payload.get("folder") or "").strip()
    folders: dict[str, list[str]] = {}
    available = comfy.model_folders()
    if available is not None:
        source = "models"
        names = [wanted] if wanted else [one for one in available if one in _LOADER_FIELDS or one in ("unet", "clip")]
        if wanted and wanted not in available:
            raise ComfyError(say(locale, f"ComfyUI 没有模型目录「{wanted}」,有的是:{', '.join(available)}",
                                 f"ComfyUI has no model folder “{wanted}”; it has: {', '.join(available)}"))
        for name in names:
            folders[name] = comfy.models_in(name)[:_MAX_FILES]
    else:
        source = "object_info"
        info = comfy.object_info()
        for name, (node, field) in _LOADER_FIELDS.items():
            if wanted and name != wanted:
                continue
            try:
                options = info[node]["input"]["required"][field][0]
            except (KeyError, IndexError, TypeError):
                continue
            if isinstance(options, list):
                folders[name] = [str(one) for one in options][:_MAX_FILES]
    counts = {name: len(files) for name, files in folders.items()}
    listed = [f"{name} {count}" for name, count in counts.items() if count]
    return {
        "folders": folders,
        "counts": counts,
        "source": source,
        "summary": say(locale, "模型文件:" + ("、".join(listed) or "没有"), "Model files: " + (", ".join(listed) or "none")),
    }


def interrupt(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    """停下正在跑的任务。给了 `prompt_id` 就只停那一个(在跑的中断、在排队的删掉)。"""
    prompt_id = str(payload.get("prompt_id") or "").strip()
    running, pending = comfy.queue()
    if prompt_id:
        if prompt_id in running:
            comfy.post("/interrupt", {"prompt_id": prompt_id})
            was = "running"
        elif prompt_id in pending:
            comfy.post("/queue", {"delete": [prompt_id]})
            was = "pending"
        else:
            was = "not-found"
        said = {
            "running": say(locale, f"已中断任务 {prompt_id}", f"Interrupted task {prompt_id}"),
            "pending": say(locale, f"已把任务 {prompt_id} 从队列里删掉", f"Removed task {prompt_id} from the queue"),
            "not-found": say(locale, f"任务 {prompt_id} 不在跑也不在排队", f"Task {prompt_id} is neither running nor queued"),
        }[was]
        return {"prompt_id": prompt_id, "was": was, "interrupted": was != "not-found", "summary": said}
    if not running:
        return {"interrupted": False, "was": "idle", "summary": say(locale, "ComfyUI 现在没有在跑的任务", "ComfyUI is idle")}
    comfy.post("/interrupt", {})
    return {"interrupted": True, "was": "running", "prompt_ids": running,
            "summary": say(locale, f"已中断正在跑的任务 {', '.join(running)}", f"Interrupted {', '.join(running)}")}


def clear_queue(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    """清掉**排队中**的任务(在跑的那个不动 —— 要停它用 interrupt)。"""
    _, pending = comfy.queue()
    if pending:
        comfy.post("/queue", {"clear": True})
    return {"cleared": len(pending), "prompt_ids": pending,
            "summary": say(locale, f"清掉了 {len(pending)} 个排队中的任务", f"Cleared {len(pending)} queued task(s)")}


def free_memory(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    """让 ComfyUI 卸载模型、释放显存(`/free`)。下一次生成要重新加载模型,会慢一些。"""
    unload = payload.get("unload_models") is not False
    comfy.post("/free", {"unload_models": unload, "free_memory": True})
    return {"freed": True, "unloaded_models": unload,
            "summary": say(locale, "已让 ComfyUI 释放显存" + ("并卸载模型" if unload else ""),
                           "Asked ComfyUI to free memory" + (" and unload models" if unload else ""))}
