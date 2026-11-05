"""随插件发布的长视频 ComfyUI 工作流:检查缺什么、一键写进当前 ComfyUI 的 workflows/。

这不是 Mosael 自己的工作流(domain/workflows):它是插件包里的 `.json`,给「任意长度连续视频」和「任意时长数字人」当
ComfyUI 执行后端。示例原本只在 ComfyUI-Mosael-Plugins 仓库里 —— 用户装了 ComfyUI 也未必有它们,所以这里把文件随插件
发布,并在**写入之前**把缺的节点 / 模型说清楚。

宿主按 `op` 问(见 main._generation):

    {"op": "bundled_workflows"}              → 包里有哪些工作流、当前 ComfyUI 有没有、各自缺什么
    {"op": "install_bundled_workflows", "folder"?} → 只写缺的(不覆盖),回 install/skip 和目标目录

**只写当前连接的 ComfyUI**:`comfy` 由宿主按实例地址构造。写之前界面上会确认目标服务器;这里再查路径、只新建、
不覆盖。缺的节点 / 模型不替用户自动装 —— 节点包和模型是另外两步,同一个工作流库详情里补。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from comfy_http import Comfy
from lines import ComfyError, say
from workflow_library import check_folder, check_path, describe, missing_types, model_options

#: 插件包里的资源目录(和 tools/ 同级)。
ROOT = Path(__file__).resolve().parent.parent / "workflows" / "long_video"
MANIFEST = ROOT / "manifest.json"


def _manifest(locale: str) -> dict[str, Any]:
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ComfyError(say(locale, "插件里没有可用的长片工作流资源", "This plugin has no long-video workflow resources")) from exc
    if not isinstance(data, dict) or not isinstance(data.get("workflows"), list):
        raise ComfyError(say(locale, "长片工作流清单坏了", "The long-video workflow manifest is invalid"))
    return data


def _label(value: Any, locale: str) -> str:
    if isinstance(value, dict):
        return str(value.get("zh" if locale.startswith("zh") else "en") or next(iter(value.values()), ""))
    return str(value or "")


def _target(manifest: dict[str, Any], spec: dict[str, Any], folder: str, locale: str) -> str:
    name = str(spec.get("file") or "").strip()
    if not name:
        raise ComfyError(say(locale, "长片工作流清单里有一项没有文件名", "A long-video workflow entry has no filename"))
    return check_path(f"{folder}/{name}", locale)


def _source(spec: dict[str, Any], locale: str) -> dict[str, Any]:
    path = ROOT / str(spec.get("file") or "")
    try:
        source = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ComfyError(say(locale, f"插件里的 {path.name} 读不出来", f"Can't read {path.name} from this plugin")) from exc
    if not isinstance(source, dict) or not isinstance(source.get("nodes"), list):
        raise ComfyError(say(locale, f"插件里的 {path.name} 不是界面格式工作流",
                             f"{path.name} in this plugin is not a UI-format workflow"))
    return source


def status(comfy: Comfy, locale: str) -> dict[str, Any]:
    """包里每张工作流在当前 ComfyUI 上的状态。**不改那台机器**,只读 files 和 object_info。"""
    manifest = _manifest(locale)
    folder = check_folder(str(manifest.get("folder") or "mosael/long-video"), locale)
    saved, _others = comfy.saved_files()
    installed = set(saved)
    object_info = comfy.object_info()
    options = model_options(object_info)
    rows: list[dict[str, Any]] = []
    for spec in manifest["workflows"]:
        if not isinstance(spec, dict):
            continue
        path = _target(manifest, spec, folder, locale)
        row: dict[str, Any] = {"path": path, "installed": path in installed}
        try:
            #: 已装的那张可能被用户改过:缺项要照**那台机器上的文件**判,不照插件里的原始副本。
            source = comfy.fetch_workflow(path) if row["installed"] else _source(spec, locale)
        except Exception as exc:  # noqa: BLE001 — 一张读不出来只影响这一行
            row.update({"name": _label(spec.get("name"), locale), "missing_nodes": [], "missing_models": [],
                        "problem": str(exc) or type(exc).__name__})
            rows.append(row)
            continue
        try:
            missing = missing_types(source, object_info)
            #: 安装前只报**缺什么**(节点类型、模型文件);节点包由工作流详情里的检查去查 Manager。
            #: 这里传空表,免得打开一个安装框先等一次 Manager 的映射。
            described = describe(row, source, object_info, options, comfy, locale, missing=missing, packs={})
            row.update({
                "name": _label(spec.get("name"), locale),
                "missing_nodes": described.get("missing_nodes") or [],
                "missing_models": described.get("missing_models") or [],
                "problem": described.get("problem") or "",
            })
        except Exception as exc:  # noqa: BLE001 — 一张坏图不能拖垮整份清单
            row.update({
                "name": _label(spec.get("name"), locale),
                "missing_nodes": [],
                "missing_models": [],
                "problem": str(exc) or type(exc).__name__,
            })
        rows.append(row)
    return {
        "id": str(manifest.get("id") or ""),
        "title": _label(manifest.get("title"), locale),
        "description": _label(manifest.get("description"), locale),
        "folder": folder,
        "workflows": rows,
    }


def install(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    """写缺的工作流到当前 ComfyUI。**只新建、不覆盖**;已有同名文件跳过。"""
    manifest = _manifest(locale)
    folder = check_folder(str(payload.get("folder") or manifest.get("folder") or "mosael/long-video"), locale)
    saved, _others = comfy.saved_files()
    installed = set(saved)
    written: list[str] = []
    skipped: list[str] = []
    for spec in manifest["workflows"]:
        if not isinstance(spec, dict):
            continue
        path = _target(manifest, spec, folder, locale)
        if path in installed or path in written:
            skipped.append(path)
            continue
        source = _source(spec, locale)
        if not comfy.write_userdata(f"workflows/{path}", source):
            skipped.append(path)
            continue
        written.append(path)
    return {
        "folder": folder,
        "installed": written,
        "skipped": skipped,
        "workflows": status(comfy, locale)["workflows"],
    }


__all__ = ["install", "status"]
