"""节点定义从哪来(ADR 0042):给智能体的几样操作只在一处取 ComfyUI 的节点定义。

- **只要几类节点**(诊断一张图、摘要画布、照这台机器改模板):一类一类问 `/object_info/{类名}`。一类几 KB,局域网里几十
  毫秒;这台 ComfyUI 上没有的那一类回 `{}` —— 「缺这个节点类型」照样判得出。整份 `/object_info` 有好几 MB(维护者那台
  5.9 MB,加上 `/i18n` 0.85 MB),慢的局域网上一次要传十几秒,不为一张二十个节点的图把它整个取一遍。
- **要在全部节点里找**(`node_types` 按名字、类别、说明搜):只有 `catalog` 取整份,记在插件的持久目录里;下次先问一句
  `/object_info` 有多大(HEAD,不收正文),大小变了(装了节点包、重启后多了 / 少了节点、模型目录里多了文件 —— 下拉的可选值
  也在里面)才重取。

别的老调用(生成、工作流库)还在用 `Comfy.object_info()`,不归这里管。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterable
from urllib import parse

from comfy_http import Comfy
from lines import ComfyError
from model_files import data_file, load_json, save_json

#: 一次最多同时问几类。ComfyUI 是别人的机器、可能正在出图:几个并发就够。
WORKERS = 6
#: 一次最多问多少类(一张图里见过两百多个节点,类型远没有这么多)。
MAX_CLASSES = 400


def _one(comfy: Comfy, name: str) -> tuple[str, dict[str, Any] | None]:
    try:
        found = comfy.get(f"/object_info/{parse.quote(name, safe='')}")
    except ComfyError as exc:
        if exc.status == 404:
            return name, None
        raise
    spec = found.get(name) if isinstance(found, dict) else None
    return name, spec if isinstance(spec, dict) else None


def classes(comfy: Comfy, names: Iterable[str]) -> dict[str, dict[str, Any]]:
    """这几类节点的定义(类名 → `/object_info` 里那一项)。这台 ComfyUI 上没有的不在结果里。"""
    wanted = sorted({str(one) for one in names if str(one).strip()})[:MAX_CLASSES]
    if not wanted:
        return {}
    with ThreadPoolExecutor(max_workers=min(WORKERS, len(wanted))) as pool:
        answers = list(pool.map(lambda one: _one(comfy, one), wanted))
    return {name: spec for name, spec in answers if spec is not None}


def fingerprint(comfy: Comfy) -> str:
    """整份 `/object_info` 的指纹:它有多大(HEAD)。问不出就是空串 —— 那就每次都重取。"""
    size = comfy.head_length("/object_info")
    return f"len:{size}" if size else ""


def catalog(comfy: Comfy) -> dict[str, dict[str, Any]]:
    """**全部**节点的定义 —— 只给要在全部节点里找的那一种用(见模块说明)。记在持久目录里,指纹变了才重取。"""
    path = data_file(comfy, "object-info")
    mark = fingerprint(comfy)
    saved = load_json(path)
    if mark and saved.get("fingerprint") == mark and isinstance(saved.get("nodes"), dict):
        return saved["nodes"]
    found = comfy.get("/object_info")
    nodes = {str(key): value for key, value in found.items() if isinstance(value, dict)} if isinstance(found, dict) else {}
    if mark:
        save_json(path, {"fingerprint": mark, "nodes": nodes})
    return nodes


__all__ = ["MAX_CLASSES", "catalog", "classes", "fingerprint"]
