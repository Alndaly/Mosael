"""插件**一次性的改名**(`moved`,ADR 0045 §6):从这一版起,`from` 说的那件事改叫 `to`,`from` 这个名字以后另有所指。

和 `replaces`(见 domain/workflows/plugin_references)不一样:那是「老工具不在了 / 换了写法,存着的老节点改写过来」,每次清单
刷新都对一遍账;这里的 `from` **还在**,只是意思变了 —— ComfyUI 一张有表单的工作流,它的路径、工具名以前指那张表单,从插件
1.20 起指完整工作流,表单搬到 `<路径>#app` / `wf_<id>_app`。所以每个名字只能改**一次**:改两次的话,改过之后才有人特意选的
完整工作流也会被改走。插件每次都报(它不知道宿主做没做过),宿主按 `key` **和旧名字**记账,每个连接、每种清单(生成目录 /
工具清单)、每个旧名字只做一次:

    {"op": "models"} → {"models": [...], "moved": [{"key": "form-entries", "from": "a.json", "to": "a.json#app"}], ...}
    {"op": "tools"}  → {"tools": [...],  "moved": [{"key": "form-entries", "from": "wf_x", "to": "wf_x_app"}], ...}

账记在连接上(`plugin_instances.applied_moves`:`{"generation": {key: [旧名字…]}, "tools": {key: [旧名字…]}}`)。**按旧名字记,
不只按 key**:同一批改名的几个名字不一定同一次报出来 —— 从 1.20 之前直接升到 1.21 的人,上一版格式的表单要在工作流库里
「查看并升级」之后才报,一张刚在 ComfyUI 里改过被跳过、下次再升级,它的那条改名晚一次才来;只按 key 记的话,先来的那张做了、
记了 key,晚来的那张被当成「做过了」,它的老引用悄悄变成跑完整工作流(PLG-2)。存着的引用怎么改由各个领域自己做(生成目录
的见 providers.moved_models,工具的由这里的监听转给工作流、画板),插件域不认识它们。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import PluginInstance

#: 一次清单最多报几条改名;改名的 key 长什么样。
MAX_MOVES = 1000
_KEY = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_MAX_NAME = 600

#: 改名:key → {旧名字: 新名字}。
Moves = dict[str, dict[str, str]]
#: 一种清单上一个 key 最多记多少个旧名字(同 MAX_MOVES:一次清单最多报这么多条)。
MAX_RECORDED = MAX_MOVES


def clean_moves(raw: Any, known: set[str]) -> Moves:
    """插件说的 `moved` 收成规整的形状:`to` 必须是这份清单里真有的一项(`known`),`from` 和 `to` 不同。认不出的条目丢掉。"""
    found: Moves = {}
    if not isinstance(raw, list):
        return found
    for entry in raw[:MAX_MOVES]:
        if not isinstance(entry, dict):
            continue
        key, source, target = entry.get("key"), entry.get("from"), entry.get("to")
        if not (isinstance(key, str) and _KEY.match(key) and isinstance(source, str) and isinstance(target, str)):
            continue
        source, target = source.strip(), target.strip()
        if not source or source == target or len(source) > _MAX_NAME or target not in known:
            continue
        found.setdefault(key, {}).setdefault(source, target)
    return found


def _done(instance: PluginInstance, capability: str) -> dict[str, set[str]]:
    ledger = (instance.applied_moves or {}).get(capability)
    if not isinstance(ledger, dict):
        return {}
    return {key: {one for one in names if isinstance(one, str)} for key, names in ledger.items() if isinstance(names, list)}


def pending(instance: PluginInstance, capability: str, moves: Moves) -> Moves:
    """这个连接在这种清单上还没做过的那几条:按 key 和旧名字认,同一个 key 下没改过的旧名字照样做(见模块说明)。"""
    done = _done(instance, capability)
    out: Moves = {}
    for key, renames in moves.items():
        left = {source: target for source, target in renames.items() if source not in done.get(key, set())}
        if left:
            out[key] = left
    return out


def record(db: Session, instance: PluginInstance, capability: str, moves: Moves) -> None:
    """记下这几条在这个连接上做过了(不提交:和改写本身在同一个事务里)。整份换掉:JSON 列上的就地修改 ORM 看不见。"""
    applied = {name: (dict(value) if isinstance(value, dict) else value)
               for name, value in (instance.applied_moves or {}).items()}
    ledger = {key: list(names) for key, names in _done(instance, capability).items()}
    for key, renames in moves.items():
        ledger[key] = sorted(set(ledger.get(key, [])) | set(renames))[-MAX_RECORDED:]
    applied[capability] = ledger
    instance.applied_moves = applied
    db.flush()


def follow_renames(db: Session, instance: PluginInstance, capability: str, renames: dict[str, str]) -> None:
    """在 Mosael 的工作流库里改了名、挪了目录(ADR 0045 修订之二 D2,`renames`:旧名字 → 新名字):账上做过的旧名字换了地方,
    新名字也算做过 —— 不然下一次目录刷新,插件照常报的一次性改名(`归档/x.json` → `归档/x.json#app`)在账上找不到它,又把
    刚跟过去的引用改走一次。改名这件事本身不进账(它不是插件报的一次性改名)。不提交。"""
    ledger = _done(instance, capability)
    if not any(source in names for names in ledger.values() for source in renames):
        return
    applied = {name: (dict(value) if isinstance(value, dict) else value) for name, value in (instance.applied_moves or {}).items()}
    applied[capability] = {key: sorted(names | {renames[one] for one in names if one in renames})[-MAX_RECORDED:]
                           for key, names in ledger.items()}
    instance.applied_moves = applied
    db.flush()


def merged(moves: Moves) -> dict[str, str]:
    """几批改名并成一张「旧 → 新」的表(同一个旧名字只认第一批说的)。"""
    renames: dict[str, str] = {}
    for one in moves.values():
        for source, target in one.items():
            renames.setdefault(source, target)
    return renames


#: 工具改了名之后要跟着动的那些(工作流节点、画板格子)。插件域不认识它们 —— 由那边在组装根登记进来。
#: (db, 连接, 旧工具名 → 新工具名, *, why):`why` 和模型那一侧同一个意思(providers.moved_models.MOVED / RENAMED)。
ToolsListener = Callable[..., None]
_tool_listeners: list[ToolsListener] = []


def on_tools_moved(listener: ToolsListener) -> None:
    if listener not in _tool_listeners:
        _tool_listeners.append(listener)


def tools_moved(db: Session, instance: PluginInstance, renames: dict[str, str], *, why: str = "moved") -> None:
    """这个连接的工具改了名(`renames`:旧工具名 → 新工具名):每个监听改自己的数据。`why`:`"moved"` 插件报的一次性改名,
    `"renamed"` 在 Mosael 的工作流库里改名、挪目录(那时新名字还没进工具清单,见 workflows.plugin_references.moved_tools)。不提交。"""
    for listener in _tool_listeners:
        listener(db, instance, renames, why=why)


__all__ = ["MAX_MOVES", "Moves", "clean_moves", "follow_renames", "merged", "on_tools_moved", "pending", "record",
           "tools_moved"]
