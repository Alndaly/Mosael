"""模型的预览图:这台 ComfyUI 上能不能按哈希找、能不能写回,以及写回(ADR 0038 §9)。

**写回走 ComfyUI-Custom-Scripts(pysssss)自己那条路**(它的「Use as preview」就是这么做的):先把图(或视频)经 ComfyUI
核心的 `/upload/image` 传进 temp 目录,再 `POST /pysssss/save/{目录}%2F{文件}`,`{"filename", "subfolder", "type": "temp"}`
—— 它把 temp 里那一份拷到模型旁边,名字是模型的名字换上传上去那一份的扩展名(`x.safetensors` → `x.png` / `x.mp4`)。
**同名的会被覆盖**:所以只给那台服务器上还没有预览图的模型写(宿主先查过)。

**按哈希找**走它的 `/pysssss/metadata/{目录}%2F{文件}`:那台机器把整个文件读一遍算 SHA256,记在模型旁边的 `.sha256`
里,第二次直接读。

有没有这两条路,看 ComfyUI 的 `/extensions`(每个自定义节点包的前端脚本):pysssss 的 `betterCombos.js` 和 `/pysssss/save`、
`/pysssss/view` 是同一个模块,`modelInfo.js` 和 `/pysssss/metadata` 是同一个。只读这一个接口就知道,不去试写。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any
from urllib import parse

from comfy_http import Comfy
from lines import ComfyError, say

#: 传进 temp 目录时放在哪个子目录(和 Mosael 别的上传分开,一眼认得出是谁传的)。
TEMP_SUBFOLDER = "mosael-previews"
#: 能当预览图写回的种类:图,和(示例只有视频的模型)那段视频。
PREVIEW_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm")
#: 模型旁边能当预览的视频(Mosael 认,ComfyUI 自己的列表和 pysssss 只认图)。
VIDEO_SUFFIXES = (".mp4", ".webm")
#: ComfyUI 的预览接口认的图(和模型同名,或 `<名字>.preview.<扩展名>`)。文件名带 `[ ]` 时它按通配符找、找不到,这几样要
#: 按名字直接读。
IMAGE_SIDECARS = (".png", ".jpg", ".jpeg", ".webp", ".preview.png", ".preview.jpeg")


def sidecars(folder: str, name: str) -> list[str]:
    """模型旁边可能的预览文件(相对 `/pysssss/view/` 的一段,按先后试):文件名带 `[ ]` 的先是那几种图(ComfyUI 的预览
    接口找不到它们),再是预览视频。宿主在 ComfyUI 的预览接口说没有之后按这个顺序按名字直接读。"""
    stem = name.rsplit(".", 1)[0] if "." in name.replace("\\", "/").rsplit("/", 1)[-1] else name
    suffixes = (IMAGE_SIDECARS if "[" in name or "]" in name else ()) + VIDEO_SUFFIXES
    return [model_path(folder, f"{stem}{suffix}") for suffix in suffixes]


def originals(comfy: Comfy, folders: list[str]) -> dict[tuple[str, str], str]:
    """每个模型那张预览图的**原文件**(相对 `/pysssss/view/` 的一段):ComfyUI-Custom-Scripts 的 `/pysssss/images/{目录}`
    一个目录问一次,回「模型名 → 目录/那张图的文件名」(它只认 png、jpg、jpeg、.preview.png、.preview.jpeg)。

    ComfyUI 自己的预览接口把图现转成有损的 WebP 再给;宿主的本机识别要看原图(同一张图,转过一次 WebP 的分数能从
    0.47 变成 0.69,沙盒实测),按这一段经 `/pysssss/view` 原样取。问不到的目录跳过。键是 (目录, 名字),名字统一成正斜杠。"""
    found: dict[tuple[str, str], str] = {}
    for folder in folders:
        try:
            listed = comfy.get(f"/pysssss/images/{parse.quote(folder, safe='')}")
        except ComfyError:
            continue
        for name, image in (listed.items() if isinstance(listed, dict) else ()):
            if isinstance(name, str) and isinstance(image, str) and image.startswith(f"{folder}/"):
                found[(folder, name.replace("\\", "/"))] = parse.quote(image, safe="")
    return found


def tools(comfy: Comfy) -> dict[str, bool]:
    """这台 ComfyUI 上 pysssss 的那两条路在不在:`hash`(按哈希找)、`save`(写回预览图)。读不到就当都不在。"""
    try:
        found = comfy.get("/extensions")
    except ComfyError:
        return {"hash": False, "save": False}
    scripts = [str(one).lower() for one in found] if isinstance(found, list) else []
    return {
        "hash": any(one.endswith("/js/modelinfo.js") for one in scripts),
        "save": any(one.endswith("/js/bettercombos.js") for one in scripts),
    }


def missing_tool(locale: str) -> str:
    """没有写回的路时说缺什么、怎么补。"""
    return say(locale,
               "这台 ComfyUI 没装 ComfyUI-Custom-Scripts(pysssss):写回预览图走的是它的接口。在 ComfyUI-Manager 里装上它、"
               "重启 ComfyUI 之后就能存",
               "This ComfyUI doesn't have ComfyUI-Custom-Scripts (pysssss) installed; saving previews uses its API. Install it "
               "from ComfyUI-Manager and restart ComfyUI to save previews")


def model_path(folder: str, name: str) -> str:
    """pysssss 的地址里「目录/文件」是一整段(斜杠编码成 %2F)。"""
    return parse.quote(f"{folder}/{name}", safe="")


def save(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    """`{"op": "save_preview", "folder", "name", "path"}`:把宿主交来的那一份(`path`,宿主暂存目录里的副本)写成这个模型的
    预览图。回 `{"saved": "目录/新文件名"}`。"""
    folder, name = str(payload.get("folder") or ""), str(payload.get("name") or "")
    source = Path(str(payload.get("path") or ""))
    if not folder or not name or not source.is_file():
        raise ComfyError(say(locale, "要写回的预览图没交过来", "The preview to save wasn't provided"))
    suffix = source.suffix.lower()
    if suffix not in PREVIEW_SUFFIXES:
        raise ComfyError(say(locale, f"这种文件不能当预览图:{suffix}", f"This kind of file can't be a preview: {suffix}"))
    if not tools(comfy)["save"]:
        raise ComfyError(missing_tool(locale))
    stored = comfy.upload_file(source, f"mosael-{uuid.uuid4().hex[:12]}{suffix}", kind="temp", subfolder=TEMP_SUBFOLDER)
    answer = comfy.post(f"/pysssss/save/{model_path(folder, name)}",
                        {"filename": stored["name"], "subfolder": stored["subfolder"], "type": "temp"})
    saved = str(answer.get("image") or "") if isinstance(answer, dict) else ""
    return {"folder": folder, "name": name, "saved": saved}
