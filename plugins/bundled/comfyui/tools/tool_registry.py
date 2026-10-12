"""工具注册表的**只读那一面**:一张图 / 一个入口叫什么工具名、这张图跑不跑得起来、一份产出记在哪个具名输出上。

按入口分工具那件事在 `tooling`(它从这里取名字去拼工具的入参、说明与迁移);`workflows` 列工作流时也要这份
名字与这个判据(每张图报的是哪个工具、跑得起来才报)。两边都要,所以它住在两者**下面**这个叶子里:
`tooling` 与 `workflows` 都认识它,它不认识它们 —— 先前 `workflows` 反借 `tooling` 的这三样、
`tooling` 又在函数里 `from workflows import deliver`,把这两个模块圈成了一个环。

**只读**:这里不写文件、不碰 `Comfy`(工具名 → 入口 id 的那份对照表在 tooling,它按服务器分开记在持久目录里)。
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

import graph
import models

#: 不在 ComfyUI 里存着的那张图(内置文生图):名字写死(它没有路径,也没有 ComfyUI 给的 id)。
BUILTIN_TOOL = "wf_builtin_txt2img"


def safe(node: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(node)).strip("_") or "0"


def short_hash(text: str) -> str:
    """短哈希(sha1 前 12 位):按路径起的工具名、每台服务器一份的工具名对照表都用它。"""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def output_key(media: str, node: str) -> str:
    prefix = media if media in ("image", "video", "audio", "text") else "output"
    return f"{prefix}_{safe(node)}"


def _ident_key(workflow: models.Workflow) -> str:
    ident = re.sub(r"[^0-9a-fA-F]", "", workflow.ident).lower()
    # 全零的 UUID 是老版本前端的占位(新版前端存盘前会换掉它),不是这张图自己的 id
    return ident[:12] if len(ident) >= 12 and ident.strip("0") else ""


#: 名字写死的那几个入口:内置文生图没有路径、也没有 ComfyUI 给的 id。
FIXED_NAMES = {models.BUILTIN: BUILTIN_TOOL}


def path_name(workflow_id: str, form_id: str = "") -> str:
    """按路径哈希起的那个工具名(表单入口在后面接 `_<表单 id>`)—— 老版本存的图没有 id 时用的就是它。"""
    return f"wf_{short_hash(workflow_id)}" + (f"_{form_id}" if form_id else "")


def _workflow_names(workflows: list[models.Workflow]) -> dict[str, str]:
    """图的 id → 它的完整工作流入口的工具名。转不过来的图没有工具。

    **几张图带着同一个 id**(在 ComfyUI 外面拷了一份文件、老版本「另存为」带着原来的 id)时,它们都退到路径的
    哈希:谁拿那个 id 的名字要是按路径顺序定,新拷出来的「a 副本.json」排在前面就抢走了原来那张的名字,存着的
    工作流节点从此悄悄跑的是另一张图。宁可名字变了、调用时说「找不到」,也不张冠李戴。
    """
    counts: dict[str, int] = {}
    for workflow in workflows:
        key = _ident_key(workflow)
        if key and not workflow.problem:
            counts[key] = counts.get(key, 0) + 1
    names: dict[str, str] = {}
    for workflow in workflows:
        if workflow.problem:
            continue
        if workflow.id in FIXED_NAMES:
            names[workflow.id] = FIXED_NAMES[workflow.id]
            continue
        key = _ident_key(workflow)
        names[workflow.id] = f"wf_{key}" if key and counts[key] == 1 else path_name(workflow.id)
    return names


def tool_names(entries: list[models.Entry]) -> dict[str, str]:
    """入口 id(模型 id)→ 工具名。完整工作流入口是这张图的名字(见 `_workflow_names`),表单入口在它后面接 `_<表单 id>`:
    一张图退到路径哈希时,它的表单入口跟着退。撞 id 要看同一台上的每一张图,所以 `entries` 要给全。"""
    workflows = list({one.workflow.id: one.workflow for one in entries}.values())
    base = _workflow_names(workflows)
    return {one.id: f"{base[one.workflow.id]}_{one.form_id}" if one.form_id else base[one.workflow.id]
            for one in entries if one.workflow.id in base}


def runnable(workflow: models.Workflow, object_info: dict[str, Any]) -> bool:
    """这张图跑得起来吗:一个输出节点(保存、预览、显示文字……)都没有的,ComfyUI 不跑(`Prompt has no outputs`),
    原样跑一遍什么也交不回 —— 不做成工具(此前它的工具写着「交回它全部 0 个输出节点的产出」)。"""
    return bool(graph.output_nodes(workflow.api, object_info, workflow.titles))
