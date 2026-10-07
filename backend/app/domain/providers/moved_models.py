"""连接上的模型**改了名**之后,存着的 (连接, 模型) 引用跟着改(ADR 0045 §6)。

一个插件连接可以说「从这一版起,模型 `from` 改叫 `to`,`from` 以后另有所指」(一次性的改名,见 domain/plugins/moves)。
ComfyUI 插件 1.19 就是这样:有表单的工作流,它的路径以前指那张表单,从这一版起指完整工作流,表单搬到 `<路径>#app`。
引用以前指的是表单,所以改到 `to` —— 跑起来、看到的都和以前一样。

`apply` 先把模型行原地改名(providers.models.rename_declared_models:默认模型、停用跟着走),再交给每个存着引用的领域
(生成的会话和记录、用量、定时任务、画板、工作流)各改各的 —— 它们在组装根登记(`on_moved`),这里不认识它们。

存着的引用有两种写法,`renamed` 一处认:

- 一个字典里 `provider_profile_id` 是这个连接、`model` 是旧名字(画板的生成格、工作流的 `ai_generate`、定时任务、任务回执);
- 一个生成选项 id 的字符串 `<连接 id>:<种类>:<模型 id>`(工作流里资产「补全多角度」、说话这类节点选的模型)。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ProviderProfile
from app.domain.providers import models as provider_models

#: (db, 连接 id, 旧名字 → 新名字)。
Listener = Callable[[Session, str, dict[str, str]], None]
_listeners: list[Listener] = []

#: 生成选项 id 里的种类(见 generation.resolution.generation_options)。
_KINDS = ("image", "video", "audio")


def on_moved(listener: Listener) -> None:
    if listener not in _listeners:
        _listeners.append(listener)


def apply(db: Session, profile: ProviderProfile, renames: dict[str, str]) -> None:
    """这条连接的模型改了名:模型行原地改名,再让每个领域改它存着的引用。不提交 —— 和记账在同一个事务里。"""
    if not renames:
        return
    provider_models.rename_declared_models(db, profile, renames)
    for listener in _listeners:
        listener(db, profile.id, renames)
    db.flush()


def renamed(value: Any, profile_id: str, renames: dict[str, str]) -> Any:
    """一份存着的数据(字典、列表、字符串,任意嵌套)里指着这条连接旧模型名的引用,换成新名字;别的原样。"""
    if isinstance(value, dict):
        out = {key: renamed(item, profile_id, renames) for key, item in value.items()}
        model = out.get("model")
        if out.get("provider_profile_id") == profile_id and isinstance(model, str) and model in renames:
            out["model"] = renames[model]
        return out
    if isinstance(value, list):
        return [renamed(item, profile_id, renames) for item in value]
    if isinstance(value, str) and value.startswith(f"{profile_id}:"):
        kind, sep, model = value[len(profile_id) + 1:].partition(":")
        if sep and kind in _KINDS and model in renames:
            return f"{profile_id}:{kind}:{renames[model]}"
    return value


__all__ = ["apply", "on_moved", "renamed"]
