"""插件实例变了,**替宿主做事的那一侧**要跟着变 —— 这里只负责**转发通知**。

插件可以声明自己能替宿主做成某件事(`provides`):把本地素材换成公网直链、做一次生成……
做成之后,宿主那边往往还有一份跟着它走的东西 —— 生成能力就是一条连接和一串模型(见
domain/generation/plugin_connections)。实例改了名、换了服务器地址、被停用、被授权,那一份都要
跟着对上。

**钩子登记在能力表里**(domain/capabilities 的 `on_instance_change` / `listing`,ADR 0032 §1:只剩一张表)。
插件域不 import 能力表 —— 能力表要读插件实例,反过来就成环 —— 所以组装根把查钩子的函数交给这里
(`use_table`),和 `media_bridge` 同一个手法。没接上时(只 import 了插件域的脚本)什么都不通知。

处理函数拿到 `refresh`:这次变动会不会让「插件能做什么」变了(换了服务器、刚授权、用户点了刷新)
—— 变了就该重新问插件一遍,只是改了个名就不必。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import PluginInstance

logger = logging.getLogger(__name__)

Handler = Callable[[Session, PluginInstance, bool], None]
#: 这个实例替宿主做出来的**东西**(生成能力就是它提供的那些模型),给插件页列出来。
Listing = Callable[[Session, PluginInstance], list[dict[str, Any]]]
#: 能力名 → (对齐钩子, 列清单钩子)。由组装根给(见 `use_table`)。
Lookup = Callable[[str], tuple[Handler | None, Listing | None]]


def _nothing(_capability: str) -> tuple[Handler | None, Listing | None]:
    return None, None


_lookup: Lookup = _nothing


def use_table(lookup: Lookup) -> None:
    """组装根调一次:从能力表查钩子(`capabilities.instance_hooks`)。"""
    global _lookup
    _lookup = lookup


def handles(capability: str) -> bool:
    """这项能力有没有宿主侧的对齐钩子。"""
    return _lookup(capability)[0] is not None


def refresh(db: Session, instance: PluginInstance, capability: str) -> None:
    """只让**这一项**能力的宿主侧重新问一遍插件(目录指纹变了,见 catalog_watch)。失败照抛。"""
    handler = _lookup(capability)[0]
    if handler is not None:
        handler(db, instance, True)


def listing(db: Session, instance: PluginInstance, capability: str) -> list[dict[str, Any]] | None:
    """这个实例在 `capability` 上提供的东西。宿主侧没给列法(或这项能力不产出可列的东西)回 None。"""
    lister = _lookup(capability)[1]
    return lister(db, instance) if lister is not None else None


def notify(db: Session, instance: PluginInstance, *, refresh: bool) -> None:
    """这个实例变了。它声明的每一项能力,有对齐钩子的就通知一声。

    **失败不往外抛。** 调用方是在改名、改配置、授权 —— 那件事已经做成了;宿主侧没跟上
    (比如 ComfyUI 没开,目录刷不出来)要记在它自己的状态里(`capability_status`),而不是让
    「改配置」这个操作报错,那会让用户以为配置没存上。
    """
    from app.domain.plugins import instances as inst

    try:
        provides = inst.manifest_for(db, instance).provides
    except Exception:  # noqa: BLE001 — 包刚被卸载之类:没有宿主侧可对齐
        return
    for capability in provides:
        handler = _lookup(capability)[0]
        if handler is None:
            continue
        try:
            handler(db, instance, refresh)
        except Exception:  # noqa: BLE001 — 见上:宿主侧的失败不回灌给插件操作
            db.rollback()
            logger.exception("插件实例 %s 的「%s」宿主侧没能对齐", instance.id, capability)


__all__ = ["Handler", "Listing", "Lookup", "handles", "listing", "notify", "refresh", "use_table"]
