"""插件替宿主做的那几件事,**目录变了就刷新**(生成模型、运行时报出的工具……)。

插件说的目录(ComfyUI 上有哪些工作流 → 哪些模型、哪些工具)住在用户的另一个程序里,那边随时会变。
每次打开选择器都现问一遍太贵(一个 ComfyUI 上百张工作流);只在启动、改配置、点「刷新」时问,又会让
「刚在 ComfyUI 里存了一张图」要回插件页点一下才看得见。所以分两步:

- 插件在目录里带一个**指纹**(`fingerprint`),再支持一个便宜的 `op: "fingerprint"`(只列目录,不拉任何一张图);
- 这里每分钟问一次,和上次记下的(`capability_status[<能力>].fingerprint`)不一样,才让那项能力的宿主侧重新
  刷一遍(`host_capabilities`)。

**不认识任何一项具体能力**:哪项能力的宿主侧登记过、上次刷新时插件给过指纹,就问哪项。问指纹不留调用记录
(那不是一次「调用」,每分钟一行会把插件页的调用记录淹掉);问不到(服务没开)不记失败,下一分钟再问。
"""

from __future__ import annotations

import logging
import threading
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.db.models import PluginInstance, PluginPackage
from app.domain.plugins import host_capabilities
from app.domain.plugins import instances as inst
from app.domain.plugins import service_gate
from app.domain.plugins import tools
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.manifest import manifest_of
from app.domain.plugins.runtime import PluginRuntimeError

logger = logging.getLogger(__name__)

#: 多久问一次指纹。ComfyUI 里刚存了一张工作流,一分钟内它就出现在选择器和工具表里。
WATCH_INTERVAL_SECONDS = 60.0
#: 问一次指纹最多等多久。它该是一个只列目录的请求,几秒还没回就当这一轮没问到。
FINGERPRINT_TIMEOUT_SECONDS = 20.0
#: 指纹变了、目录却没刷出来(插件那一头 object_info 出错、目录拉到超时……)之后,多久再试:第一次失败等一分钟,之后每次翻倍,
#: 最多半小时。指纹又变了(那一头又改了东西)立刻再试;人点「刷新」不走这里。不退避的话,便宜的指纹每分钟都说「变了」,
#: 每分钟就把上百张工作流全拉一遍、留一条失败的调用记录(PLG-7)。
RETRY_BASE_SECONDS = 60.0
RETRY_MAX_SECONDS = 30 * 60.0
#: 刷不出来的那几项:(实例, 能力) → (那时的指纹, 连着失败几次, 下次最早什么时候试)。只在内存里 —— 重启时 refresh_all 本来就整轮刷一遍。
_failed: dict[tuple[str, str], tuple[str, int, float]] = {}
#: 退避用的钟(测试里换掉它,不碰全局的 time.monotonic)。
_clock = time.monotonic

_watch_stop = threading.Event()
_watch_thread: threading.Thread | None = None


def _instances_with_capabilities(db: Session) -> list[tuple[PluginInstance, list[str]]]:
    """每个声明了宿主能力的实例,和它那些有宿主侧登记的能力。"""
    out: list[tuple[PluginInstance, list[str]]] = []
    for instance in db.scalars(select(PluginInstance)):
        package = db.get(PluginPackage, instance.package_id)
        if package is None:
            continue
        watched = [one for one in manifest_of(package).provides if host_capabilities.handles(one)]
        if watched:
            out.append((instance, watched))
    return out


def fingerprint(db: Session, instance: PluginInstance, capability: str) -> str:
    """问插件某项能力的目录指纹。答不上来就抛 —— 不能把「没问到」当成「没变」或「变了」。"""
    output = tools.invoke_host(
        db, instance.id, capability, {"op": "fingerprint", "capability": capability},
        timeout=FINGERPRINT_TIMEOUT_SECONDS, record=False,
    )
    found = output.get("fingerprint")
    if not isinstance(found, str) or not found.strip():
        raise PluginDomainError("pluginErr_generationNoFingerprint", name=instance.name)
    return found.strip()[:200]


def refresh_all() -> None:
    """把每个实例替宿主做的每件事都刷一遍。启动时做:ComfyUI 里昨晚新存的工作流,今天打开就在。"""
    with SessionLocal() as db:
        for instance, _ in _instances_with_capabilities(db):
            try:
                host_capabilities.notify(db, instance, refresh=True)
            except Exception:  # noqa: BLE001 — 一个实例刷不出来不该挡住下一个
                db.rollback()
                logger.exception("启动时刷新插件实例 %s 失败", instance.id)


def check_for_changes() -> int:
    """问一遍每个**可用、上次交过指纹**的(实例, 能力):指纹变了就让那项能力重新刷。返回刷了几项。

    不替本机服务起进程(ADR 0041):停着的那几个直接跳过,问的这一会儿里它停了也不替它起(`no_autostart`)。"""
    refreshed = 0
    with SessionLocal() as db, service_gate.no_autostart():
        for instance, capabilities in _instances_with_capabilities(db):
            # 停着的本机服务不问(ADR 0041):为了看一眼指纹把它起起来违背「用到时才起」;它起来时会自己刷新一次。
            if inst.blocked_reason(db, instance) or service_gate.idle(db, instance):
                continue
            for capability in capabilities:
                known = str(((instance.capability_status or {}).get(capability) or {}).get("fingerprint") or "")
                if not known:
                    continue
                try:
                    current = fingerprint(db, instance, capability)
                except (PluginDomainError, PluginRuntimeError) as exc:
                    db.rollback()
                    logger.debug("插件实例 %s 的「%s」指纹没问到:%s", instance.id, capability, exc)
                    continue
                key = (instance.id, capability)
                if current == known:
                    _failed.pop(key, None)
                    continue
                failed = _failed.get(key)
                if failed is not None and failed[0] == current and _clock() < failed[2]:
                    continue  # 同一个指纹上次没刷出来,还在等(见 RETRY_BASE_SECONDS)
                try:
                    host_capabilities.refresh(db, instance, capability)
                except Exception:  # noqa: BLE001 — 一项刷不出来不该挡住下一项
                    db.rollback()
                    logger.exception("插件实例 %s 的「%s」目录变了,但没刷出来", instance.id, capability)
                # 刷成了,那一项的指纹就换成了这一个;没换就是没刷出来(宿主侧把原因记在 capability_status 上,不一定抛)
                db.refresh(instance)
                now = str(((instance.capability_status or {}).get(capability) or {}).get("fingerprint") or "")
                if now == current:
                    _failed.pop(key, None)
                    refreshed += 1
                    continue
                times = failed[1] + 1 if failed is not None and failed[0] == current else 1
                wait = min(RETRY_BASE_SECONDS * 2 ** (times - 1), RETRY_MAX_SECONDS)
                _failed[key] = (current, times, _clock() + wait)
                logger.info("插件实例 %s 的「%s」目录变了但没刷出来(连着 %d 次),%d 秒内不再试", instance.id, capability, times,
                            int(wait))
    return refreshed


def _watch() -> None:
    refresh_all()
    while not _watch_stop.wait(WATCH_INTERVAL_SECONDS):
        try:
            check_for_changes()
        except Exception:  # noqa: BLE001 — 后台线程死了就再也不会刷新,宁可记一笔接着转
            logger.exception("检查插件目录时出错")


def start_watching() -> threading.Thread:
    """后端启动时调一次:先在后台把每个实例刷一遍,然后每隔 WATCH_INTERVAL_SECONDS 看一眼指纹。

    后台做:一台没开的 ComfyUI 不该拖慢启动。
    """
    global _watch_thread
    _watch_stop.clear()
    _watch_thread = threading.Thread(target=_watch, daemon=True, name="plugin-catalog-watch")
    _watch_thread.start()
    return _watch_thread


def stop_watching() -> None:
    _watch_stop.set()


__all__ = [
    "FINGERPRINT_TIMEOUT_SECONDS",
    "WATCH_INTERVAL_SECONDS",
    "check_for_changes",
    "fingerprint",
    "refresh_all",
    "start_watching",
    "stop_watching",
]
