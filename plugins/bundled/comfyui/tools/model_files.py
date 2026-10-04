"""读这台 ComfyUI 的模型目录(模型库的几处共用):有哪些目录、在磁盘上的哪儿、里面有哪些文件、文件头里的元数据。

用的是 ComfyUI 0.3x 起的 `/experiment/models*` 与 `/view_metadata/*`(见 ADR 0034 的表)。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib import parse

from comfy_http import Comfy
from lines import ComfyError

#: 不是模型的目录:自定义节点的代码、模型配置文件(yaml)。
SKIPPED_FOLDERS = frozenset({"custom_nodes", "configs"})


def norm(name: str) -> str:
    """ComfyUI 在 Windows 上报的相对路径用反斜杠,工作流里存的有时是正斜杠:比较前统一。"""
    return name.replace("\\", "/").strip()


def folder_info(comfy: Comfy) -> dict[str, list[str]] | None:
    """目录名 → 它在磁盘上的位置(可能几处)。老版本没有这个接口 → None。"""
    try:
        found = comfy.get("/experiment/models")
    except ComfyError as exc:
        if exc.status == 404:
            return None
        raise
    out: dict[str, list[str]] = {}
    for one in found if isinstance(found, list) else []:
        if isinstance(one, dict) and isinstance(one.get("name"), str) and one["name"] not in SKIPPED_FOLDERS:
            out[one["name"]] = [str(path) for path in one.get("folders") or [] if isinstance(path, str)]
    return out


def files_in(comfy: Comfy, folder: str) -> list[dict[str, Any]]:
    """一个目录里的文件:`name`(相对路径)、`pathIndex`、`size`、`modified`。"""
    try:
        found = comfy.get(f"/experiment/models/{parse.quote(folder, safe='')}")
    except ComfyError as exc:
        if exc.status == 404:
            return []
        raise
    return [one for one in found if isinstance(one, dict) and isinstance(one.get("name"), str)] \
        if isinstance(found, list) else []


def names_in(comfy: Comfy, folder: str) -> set[str]:
    """一个目录里的文件名(统一成正斜杠),判「同名文件在不在」用。"""
    return {norm(str(item["name"])) for item in files_in(comfy, folder)}


def metadata_of(comfy: Comfy, folder: str, name: str) -> dict[str, Any] | None:
    """文件头里的 `__metadata__`。不是 safetensors、没有元数据 → None(ComfyUI 回 404)。"""
    if not name.lower().endswith(".safetensors"):
        return None
    try:
        found = comfy.get(f"/view_metadata/{parse.quote(folder, safe='')}", {"filename": name})
    except ComfyError as exc:
        if exc.status in (400, 404):
            return None
        raise
    return found if isinstance(found, dict) else None


def plain(value: str) -> bool:
    """文件名、目录名只能是一段:不带路径分隔符、不是 `.` / `..`、没有控制字符。"""
    text = (value or "").strip()
    return bool(text) and text not in (".", "..") and not any(mark in text for mark in ("/", "\\", ":", "\x00")) \
        and all(ord(char) >= 32 for char in text)


def data_file(comfy: Comfy, kind: str) -> Path | None:
    """插件持久目录里这台服务器的一份记录(按服务器地址分开:几台 ComfyUI 记在一个文件里会互相覆盖)。"""
    root = os.environ.get("MOSAEL_PLUGIN_DATA_DIR", "")
    if not root:
        return None
    return Path(root) / f"{kind}-{hashlib.sha1(comfy.base.encode()).hexdigest()[:12]}.json"


def load_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def save_json(path: Path | None, value: dict[str, Any]) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".part")
        partial.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        partial.replace(path)
    except OSError:
        pass  # 记不下就下次再读一遍,不该让列表失败
