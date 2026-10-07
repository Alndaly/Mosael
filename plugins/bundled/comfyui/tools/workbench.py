"""工作台(ADR 0038 §3、§6)要插件回答的两件事。画布是 ComfyUI 自己的,开在 Mosael 的内嵌视图里;这两个 op 不碰那台机器上的
文件,只按插件对工作流的理解回答:

    {"op": "node_folders", "nodes": [{"class_type", "input"}]}
                                                        → 选中的加载节点那一格选的是哪个模型目录的文件(模型库面板据此筛);
                                                          CLIP 加载节点再说它每一种 type 配哪几种编码器(界面照节点现在
                                                          的 type 挑,据此排)
    {"op": "app_marks", "content", "app", "results"}           → 应用表单写进画布要改的那几处标记(节点上的
                                                                  `properties.mosael`、图上的 `extra.mosael`)

`app_marks` 和 `annotate` 写的是同一种形状(都是 app_form.apply):画布开着时改的是画布上的节点,存盘是 ComfyUI 自己的保存;
画布没开时 `annotate` 改文件。标记的格式只在 app_form 一处。
"""

from __future__ import annotations

from typing import Any

import app_form
import encoders
import labels
from comfy_http import Comfy
from lines import ComfyError, say
from workflow_library import live_graph

#: 一次最多问几格(选中的节点上选模型文件的输入,一个节点见过最多的是四个 CLIP)。
MAX_NODE_FOLDERS = 64


def node_folders(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    """每一格(节点类型 + 输入名)选的是哪个模型目录的文件,和生成表单的 `x-model-folder` 同一张对照(labels.model_folder);
    不是选模型文件的格子回空串。选文本编码器的格子再交回 `encoders` 那一项:这种节点每一种 type 配哪几种编码器
    (encoders.recipes_for);别的格子是 None。**答案只看节点类型和输入名**,不看节点上现在选了什么 —— 界面在节点上填一个
    模型、换一个 type 都不用再问。只查表,不问 ComfyUI。"""
    nodes = payload.get("nodes")
    if not isinstance(nodes, list) or len(nodes) > MAX_NODE_FOLDERS:
        raise ComfyError(say(locale, "要查的格子形状不对", "The inputs to look up are malformed."))
    folders: list[str] = []
    recipes: list[dict[str, Any] | None] = []
    for one in nodes:
        if not isinstance(one, dict):
            raise ComfyError(say(locale, "要查的格子形状不对", "The inputs to look up are malformed."))
        class_type = str(one.get("class_type") or "")
        folder = labels.model_folder(class_type, str(one.get("input") or ""))
        folders.append(folder)
        recipes.append(encoders.recipes_for(class_type) if encoders.applies(folder) else None)
    return {"folders": folders, "encoders": recipes}


def app_marks(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    """应用表单和结果标记写进**画布上现在这张**要改成的样子:按 `app` / `results` 换上新标记(app_form.apply,和 annotate 写文件
    同一个函数),交回每个带标记的根图节点上的 `properties.mosael` 和图上的 `extra.mosael`。别的节点上的标记要摘掉 ——
    宿主那一侧的桥按这份清单改画布(不在清单里的节点去掉 `mosael` 那一格,别的一个字都不动)。"""
    content = live_graph(payload, locale)
    app = payload.get("app")
    if app is not None and not isinstance(app, dict):
        raise ComfyError(say(locale, "应用表单的形状不对", "The app form is malformed."))
    results = payload.get("results") or []
    if not isinstance(results, list) or len(results) > app_form.MAX_RESULTS:
        raise ComfyError(say(locale, "标成结果的节点形状不对", "The result nodes are malformed."))
    updated = app_form.apply(content, app, [str(one) for one in results], locale)
    nodes: dict[str, Any] = {}
    for node in updated.get("nodes") or []:
        props = node.get("properties") if isinstance(node, dict) else None
        if isinstance(props, dict) and isinstance(props.get(app_form.KEY), dict):
            nodes[str(node.get("id"))] = props[app_form.KEY]
    extra = updated.get("extra") if isinstance(updated.get("extra"), dict) else {}
    head = extra.get(app_form.KEY)
    return {"nodes": nodes, "extra": head if isinstance(head, dict) else None}


__all__ = ["MAX_NODE_FOLDERS", "app_marks", "node_folders"]
