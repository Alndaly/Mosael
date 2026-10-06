"""问插件本机服务的事(ADR 0041 §2 那张表),把它交回来的东西逐项核对、按看的人的语言整理好。

插件只描述、不起进程 —— 起进程是宿主的事(supervisor)。插件交回的东西是**别人写的数据**:形状不对就说清楚是
哪个插件、哪一格不对(`localServiceErr_badLaunch`),不猜它的意思;给人看的那几句(事实的名字、问题)可以按
语言分着给,宿主按读的人挑。

| 操作 | 什么时候问 |
| --- | --- |
| `service_detect` | 连接页上选了目录、点「检查」(会试跑一次 `import torch` 这类,所以要先确认) |
| `service_launch` | 每次起之前(崩了重起也问一次:配置可能改过) |
| `service_add_nodes` | 连接页上点「补装」并确认之后 |
| `service_discover` | 插件页打开时(本机有没有已经在跑的,建「连一台服务器」那一种) |
| `service_readdress` | 端口改了:插件按服务器地址分文件存的本地数据搬到新地址名下 |
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.i18n import get_current_locale
from app.db.models import LocalService, PluginInstance
from app.domain.local_services.errors import LocalServiceError
from app.domain.local_services.supervisor import DEFAULT_READY_TIMEOUT
from app.domain.plugins import instances as inst
from app.domain.plugins import tools
from app.domain.plugins.manifest import Manifest, text_of

#: 认目录:插件给试跑 `import torch` 那一步 30 秒上限,前后再读几个文件。
DETECT_TIMEOUT_SECONDS = 90
LAUNCH_TIMEOUT_SECONDS = 30
#: 补装节点要下载一个压缩包(几百 KB),走慢一点的代理也够。
ADD_NODES_TIMEOUT_SECONDS = 300
DISCOVER_TIMEOUT_SECONDS = 20
READDRESS_TIMEOUT_SECONDS = 30
#: 插件给的就绪上限,收在这个范围里:太短的第一次启动(解包前端、加载自定义节点)根本等不到,太长的让「起不来」迟迟说不出来。
READY_TIMEOUT_RANGE = (5.0, 1800.0)
#: 一次认目录最多摆几条事实、几个问题。
MAX_FACTS = 30
MAX_PROBLEMS = 20
MAX_TEXT = 1000


def _said(value: Any, manifest: Manifest) -> str:
    """插件写的一句话(字符串,或 `{"zh": …, "en": …}`)按读的人的语言挑出来。"""
    return text_of(value, get_current_locale(), author_locale=manifest.default_locale).strip()[:MAX_TEXT]


def detect(db: Session, instance: PluginInstance, service: str, directory: str, python: str) -> dict[str, Any]:
    """这个目录认不认得出、用哪个解释器、显卡怎样、缺什么 —— 摆给人看的事实和问题。"""
    manifest = inst.manifest_for(db, instance)
    output = tools.invoke_service(
        db, instance.package_id, service, {"op": "service_detect", "directory": directory, "python": python},
        instance=instance, timeout=DETECT_TIMEOUT_SECONDS,
    )
    facts = [
        {"label": _said(one.get("label"), manifest), "value": str(one.get("value") or "")[:MAX_TEXT]}
        for one in (output.get("facts") or [])[:MAX_FACTS]
        if isinstance(one, dict) and _said(one.get("label"), manifest)
    ]
    problems = [
        {"level": "error" if one.get("level") == "error" else "warning", "text": _said(one.get("text"), manifest)}
        for one in (output.get("problems") or [])[:MAX_PROBLEMS]
        if isinstance(one, dict) and _said(one.get("text"), manifest)
    ]
    offer = output.get("add_nodes")
    add_nodes = (
        {"title": _said(offer.get("title"), manifest), "description": _said(offer.get("description"), manifest)}
        if isinstance(offer, dict) and _said(offer.get("title"), manifest) else None
    )
    return {
        # 插件说能起、而且没有一条是 error:两样都要,一个说「能起」却同时报着错误的回答不算数
        "ok": output.get("ok") is True and not any(one["level"] == "error" for one in problems),
        "facts": facts,
        "problems": problems,
        "add_nodes": add_nodes,
    }


def launch(db: Session, instance: PluginInstance, row: LocalService) -> dict[str, Any]:
    """起这一次要的命令行、插件那一半环境、工作目录、健康检查的路径、就绪上限。形状不对就抛,说清楚哪一格。"""
    manifest = inst.manifest_for(db, instance)
    output = tools.invoke_service(
        db, instance.package_id, row.service,
        {"op": "service_launch", "directory": row.directory, "python": row.python, "port": row.port,
         "listen_lan": row.listen_lan, "extra_args": list(row.extra_args or [])},
        instance=instance, timeout=LAUNCH_TIMEOUT_SECONDS,
    )

    def bad(field: str) -> LocalServiceError:
        return LocalServiceError("localServiceErr_badLaunch", status=422, name=manifest.name, detail=field)

    argv = output.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(one, str) and one for one in argv):
        raise bad("argv")
    env = output.get("env") or {}
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        raise bad("env")
    cwd = output.get("cwd")
    if not isinstance(cwd, str) or not cwd or not Path(cwd).is_dir():
        raise bad("cwd")
    health_path = output.get("health_path")
    if not isinstance(health_path, str) or not health_path.startswith("/") or any(ch.isspace() for ch in health_path):
        raise bad("health_path")
    ready = output.get("ready_timeout", DEFAULT_READY_TIMEOUT)
    if isinstance(ready, bool) or not isinstance(ready, (int, float)):
        raise bad("ready_timeout")
    low, high = READY_TIMEOUT_RANGE
    return {"argv": list(argv), "env": dict(env), "cwd": cwd, "health_path": health_path,
            "ready_timeout": float(min(max(ready, low), high))}


def add_nodes(db: Session, instance: PluginInstance, row: LocalService) -> dict[str, Any]:
    """补装节点(用户确认过之后)。交回装了什么、装到了哪儿。"""
    manifest = inst.manifest_for(db, instance)
    output = tools.invoke_service(
        db, instance.package_id, row.service,
        {"op": "service_add_nodes", "directory": row.directory, "python": row.python},
        instance=instance, timeout=ADD_NODES_TIMEOUT_SECONDS,
    )
    installed = [str(one)[:200] for one in (output.get("installed") or []) if isinstance(one, str)]
    return {"installed": installed, "path": str(output.get("path") or "")[:MAX_TEXT],
            "message": _said(output.get("message"), manifest)}


def discover(db: Session, package_id: str, service: str, manifest: Manifest) -> list[dict[str, str]]:
    """本机有没有已经在跑的(插件知道去哪几个端口、问哪条路径)。"""
    output = tools.invoke_service(db, package_id, service, {"op": "service_discover"}, timeout=DISCOVER_TIMEOUT_SECONDS)
    found: list[dict[str, str]] = []
    for one in (output.get("servers") or [])[:10]:
        url = str(one.get("url") or "") if isinstance(one, dict) else ""
        if url.startswith(("http://127.0.0.1:", "http://localhost:", "http://[::1]:")):
            found.append({"url": url, "label": _said(one.get("label"), manifest) or url})
    return found


def readdress(db: Session, instance: PluginInstance, row: LocalService, before: str, after: str) -> None:
    """地址变了(改了端口):让插件把按旧地址存的本地数据搬到新地址名下。插件不认这个操作、搬失败,都只是少了一些缓存。"""
    tools.invoke_service(
        db, instance.package_id, row.service, {"op": "service_readdress", "from": before, "to": after},
        instance=instance, timeout=READDRESS_TIMEOUT_SECONDS,
    )


__all__ = ["add_nodes", "detect", "discover", "launch", "readdress"]
