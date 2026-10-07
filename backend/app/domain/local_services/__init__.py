"""本机服务(ADR 0041):插件声明一个常驻进程,宿主替它起停、看健康、收日志。

**宿主不认识 ComfyUI。** 它只认插件清单里的 `services`(`{key, title, tool}`)和那个工具回答的几个 `service_*` 操作:
认出一个装好的目录、给出命令行和健康检查的路径、补装节点、本机发现。算出来的地址写进连接的 `server_url` ——
插件、工作台、模型库、工作流库读的还是那一个地址,一行都不用改。以后别的插件要常驻进程,走同一套。

分几层:

- `records`:人定下的东西(`local_services` 表,一行对一个连接):在哪跑、目录、解释器、端口、局域网、保持运行、附加参数,
  让 Mosael 装的那一份装好时的 Python 小版本;
- `plugin_ops`:问插件(只描述、不起进程 —— 安装那一件除外),核对它交回来的东西;
- `supervisor`:进程本身 —— 起、就绪、崩溃退避、停、pid 文件与接回、同一个目录只起一份。不认识库,也不认识插件;
- `installer`:让 Mosael 装的那一次安装 —— 后台线程、到了哪一步、取消;`sources`:从哪儿下(「管理 → 下载源」)。

这里把它们接起来,对外的几件事:配置、起 / 停 / 重启、**用到时起**(`ensure_running`,经插件域的 `service_gate` 接进
每一次插件调用)、启动时接回上一个后端没来得及停的、「保持运行」的跟着起、退出时全部停掉;**让 Mosael 装**:安装计划、
装(或接着装、重建运行环境)、取消,装好的那一份试起一次、健康检查通过才算装好;**换版本**:更新到更新的钉死版本(试起没通过
就换回去)、回到上一版;**卸载**:删连接、卸载插件时问要不要一起删安装目录,可以保留模型。

**让 Mosael 装的那一份**(`mode = managed`)装在宿主分的 `<数据目录>/local-services/<连接>/`,目录就记这个(插件在里面认
源码和 `.venv`,认目录、怎么起和「用我自己装的」走同一条路)。它的 venv 是随包的 Python 建的:装好时记下 Python 小版本,
以后对不上(Mosael 升级换了随包的 Python)就不让起,连接页说「运行环境要重建」—— 再装一次,插件只重建 venv 和装进去的包,
源码和模型不动。

**谁能动它**:建、改、起、停都要部署管理员(路由那一层 `ensure_deployment_admin`)—— 起一个目录里的代码就是在这台
机器上运行它。用到时起不要:那是用一个管理员建好的连接,和用别人建好的连接一样。
"""

from __future__ import annotations

import functools
import json
import logging
import errno
import os
import shutil
import threading
import time
from collections.abc import Callable, Collection
from functools import partial
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.i18n import LocalizedError, fragment, is_message_key, t, tr
from app.core.interpreter import base_python, python_minor
from app.core.run_log import logs_dir
from app.core.unit_of_work import unit_of_work
from app.db.models import LocalService, PluginInstance, PluginPackage
from app.domain.local_services import installer, pidfiles, plugin_ops, records, sources, supervisor
from app.domain.local_services.errors import LocalServiceError
from app.domain.local_services.logs import ServiceLog
from app.domain.local_services.supervisor import (
    ACTIVE,
    FAILED,
    RESTARTING,
    RUNNING,
    STARTING,
    STATES,
    STOPPED,
    LaunchSpec,
    ServiceProcess,
)
from app.domain.plugins import egress as plugin_egress
from app.domain.plugins import host_capabilities
from app.domain.plugins import instances as inst
from app.domain.plugins import service_gate
from app.domain.plugins.manifest import SERVICE_ADDRESS_FIELD, manifest_of
from app.domain.plugins.runtime import StreamHooks
from mosael_formats.plugin_env import EGRESS_KEYS, HOST_PREFIX

logger = logging.getLogger(__name__)

#: 插件进程里的这个变量说「这个连接的服务器归宿主起停」,值是服务的 key。插件据此不自己去重启它
#: (ComfyUI:装完节点不调 Manager 的重启,交回 `host_restart`,由宿主停了再起)。
SERVICE_ENV = "MOSAEL_LOCAL_SERVICE"
#: 插件进程里的这个变量列出共用的那几处(JSON,绝对路径):服务只读它们,插件别往里写(下载的新文件、预览图都落在服务自己那一处)。
SHARED_ENV = "MOSAEL_LOCAL_SERVICE_SHARED"
#: 最多共用几处。
MAX_SHARED = 20
#: 闲置多少分钟自动停:0 = 不停,最多一天。
IDLE_MINUTES_RANGE = (0, 1440)
#: 闲置自动停多久看一眼;一分钟按多少秒算(测试里调小)。
IDLE_CHECK_SECONDS = 60.0
SECONDS_PER_MINUTE = 60.0
#: 等它就绪时,在插件给的就绪上限之外多等的余量(崩溃重启的退避、健康检查本身的那一两秒)。
ENSURE_MARGIN_SECONDS = 30.0
#: 日志里最多一次交给界面多少行。
MAX_LOG_LINES = 2000


def log_path(instance_id: str) -> Path:
    return logs_dir() / f"service-{instance_id}.log"


def install_log_path(instance_id: str) -> Path:
    """让 Mosael 装的那几步的完整输出(每一步的命令、pip 说的话;插件往里写)。每装一次滚一份,上一次的留成 `.1`。"""
    return logs_dir() / f"service-install-{instance_id}.log"


@functools.lru_cache(maxsize=4)
def _minor_of(python: str) -> str:
    return python_minor(python)


def base_minor() -> str:
    """建 venv 用的那个 Python(随包的)现在是哪个「主.次」版本;找不到是空串。按路径缓存:换解释器就是换了应用,后端会重启。"""
    base = base_python()
    return _minor_of(base) if base else ""


def needs_rebuild(row: LocalService) -> bool:
    """让 Mosael 装的那一份装好了,但建它 venv 的 Python 小版本和现在随包的对不上:venv 跑不起来,要重建。"""
    current = base_minor()
    return row.mode == records.MANAGED and bool(row.python_minor) and bool(current) and row.python_minor != current


def _runnable(db: Session, instance: PluginInstance, row: LocalService) -> None:
    """让 Mosael 装的那一份,起之前先看它装好没有、运行环境对不对 —— 对不上就别起(起了只会在日志里崩一遍),说清楚下一步。"""
    if row.mode != records.MANAGED:
        return
    title = _title(db, instance, row)
    if installer.installing(instance.id):
        raise LocalServiceError("localServiceErr_installing")
    if not row.python_minor:
        raise LocalServiceError("localServiceErr_notInstalled", name=title)
    if needs_rebuild(row):
        raise LocalServiceError("localServiceErr_rebuildNeeded", name=title, have=row.python_minor, want=base_minor())


def _process(instance_id: str) -> ServiceProcess:
    return supervisor.ensure(instance_id, ServiceLog(log_path(instance_id)))


def _directory_key(directory: str) -> str:
    """同一个目录只起一份:按真实路径比(符号链接、`..`、大小写不敏感的盘上的写法差别都抹平)。"""
    return os.path.normcase(os.path.realpath(os.path.expanduser(directory)))


def _require_row(db: Session, instance: PluginInstance) -> LocalService:
    row = records.row_of(db, instance.id)
    if row is None:
        raise LocalServiceError("localServiceErr_notConfigured", status=404)
    return row


def _title(db: Session, instance: PluginInstance, row: LocalService | None = None) -> str:
    return records.service_of(db, instance, row).title


# ---------------------------------------------------------------------------
# 用不了的时候,为什么
# ---------------------------------------------------------------------------

#: 本机服务此刻为什么用不了 → 那一句话的 key。插件说「连不上这台服务器,确认它在运行、地址填对」只适合「连一台服务器」:
#: 本机服务的地址和进程都归宿主管,该说的是它此刻的状态。
ISSUE_KEYS = {
    "installing": "localServiceIssue_installing",
    "updating": "localServiceIssue_updating",
    "not_installed": "localServiceIssue_notInstalled",
    "rebuild": "localServiceIssue_rebuild",
    "stopped": "localServiceIssue_stopped",
    "starting": "localServiceIssue_starting",
    "failed": "localServiceIssue_failed",
    "unresponsive": "localServiceIssue_unresponsive",
}


def issue_of(db: Session, instance: PluginInstance) -> tuple[str, LocalServiceError] | None:
    """这个连接背后的本机服务此刻为什么用不了:(哪一种, 那一句话)。没有本机服务、或者它在跑而且应答,是 None。

    按状态说,不认识是哪个插件:正在装 / 还没装好 / 要重建(让 Mosael 装的那一份)、停着(用到时会起)、正在起、起不来
    (带它停下时的原因)、**进程在却没有应答**(健康检查不过 —— 只在它说自己在跑时问一次,本机回环,几毫秒)。"""
    row = records.row_of(db, instance.id)
    if row is None:
        return None
    name = _title(db, instance, row)
    process = supervisor.get(instance.id)
    state = process.state if process is not None else STOPPED

    def said(kind: str, **params: object) -> tuple[str, LocalServiceError]:
        return kind, LocalServiceError(ISSUE_KEYS[kind], name=name, **params)

    if row.mode == records.MANAGED:
        run = installer.current(instance.id)
        if run is not None and run.state == installer.INSTALLING:
            return said("installing" if run.kind == installer.INSTALL else "updating")
        if not row.python_minor:
            return said("not_installed")
        if needs_rebuild(row):
            return said("rebuild", have=row.python_minor, want=base_minor())
    if state == STOPPED or process is None:
        if process is not None and process.idle_stopped:
            return "stopped", LocalServiceError("localServiceIssue_idleStopped", name=name, minutes=row.idle_stop_minutes)
        return said("stopped")
    if state in (STARTING, RESTARTING):
        return said("starting")
    if state == FAILED:
        error = process.error
        reason = fragment(error.key, **error.params) if error is not None and is_message_key(error.key) else \
            str(error or "") or (process.failure_lines[-1] if process.failure_lines else "")
        return said("failed", reason=reason)
    if process.health_url and not supervisor.healthy(process.health_url):
        return said("unresponsive")
    return None


def _explain(db: Session, instance: PluginInstance) -> LocalServiceError | None:
    """插件域的 `service_gate.explain`:一次插件调用失败了,背后的本机服务此刻为什么用不了(它好好的就是 None,失败原因照旧)。"""
    found = issue_of(db, instance)
    return found[1] if found is not None else None


# ---------------------------------------------------------------------------
# 看
# ---------------------------------------------------------------------------


def status(db: Session, instance: PluginInstance) -> dict[str, Any] | None:
    """这个连接的本机服务:人定下的配置 + 进程此刻的状态。没用本机服务是 None。"""
    row = records.row_of(db, instance.id)
    if row is None:
        return None
    process = supervisor.get(instance.id)
    state = process.state if process is not None else STOPPED
    run = installer.current(instance.id)
    found = issue_of(db, instance)
    return {
        "instance_id": instance.id,
        "service": row.service,
        "title": _title(db, instance, row),
        "mode": row.mode,
        "directory": row.directory,
        "python": row.python,
        "port": row.port,
        "url": records.address(row.port),
        "listen_lan": row.listen_lan,
        "keep_running": row.keep_running,
        "extra_args": list(row.extra_args or []),
        "shared_models": list(row.shared_models or []),
        "idle_stop_minutes": row.idle_stop_minutes,
        # 上一次停下是因为闲置太久(停着、而且没人手动起停过)
        "idle_stopped": bool(process is not None and state == STOPPED and process.idle_stopped),
        "state": state,
        "pid": process.pid if process is not None and state in ACTIVE else None,
        "started_at": process.started_at.isoformat() if process is not None and process.started_at and state in ACTIVE
        else None,
        "ready_seconds": process.ready_seconds if process is not None else None,
        "adopted": bool(process is not None and process.adopted and state in ACTIVE),
        "restarts": process.restarts() if process is not None else 0,
        "error": str(process.error) if process is not None and state == FAILED and process.error else "",
        "failure_lines": list(process.failure_lines) if process is not None and state == FAILED else [],
        # 让 Mosael 装的那一份:装好了没有、建 venv 的 Python 小版本、要不要重建、这一次安装到了哪一步(后端重启后没了)
        "installed": row.mode != records.MANAGED or bool(row.python_minor),
        "python_minor": row.python_minor or "",
        "base_python_minor": base_minor() if row.mode == records.MANAGED else "",
        "needs_rebuild": needs_rebuild(row),
        "install": run.snapshot() if run is not None and row.mode == records.MANAGED else None,
        # 此刻用不了的话为什么(连接页的「出错了」、生成模型那一行、模型库、工作流库照它说,不说「检查地址」)
        "issue": {"kind": found[0], "text": str(found[1])} if found is not None else None,
    }


def recent_logs(instance_id: str, limit: int = 400) -> list[str]:
    """最近的日志行(子进程自己说的话,原样)。"""
    process = supervisor.get(instance_id)
    log = process.log if process is not None else ServiceLog(log_path(instance_id))
    return log.tail(max(1, min(limit, MAX_LOG_LINES)))


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


def detect(db: Session, instance: PluginInstance, directory: str, python: str) -> dict[str, Any]:
    """认这个目录(会试跑一次插件说的那几行,比如 `import torch` —— 调用方要先确认过)。不存任何东西。"""
    directory = directory.strip()
    if not directory:
        raise LocalServiceError("localServiceErr_noDirectory", status=422)
    service = records.service_of(db, instance, records.row_of(db, instance.id))
    return plugin_ops.detect(db, instance, service.key, directory, python.strip())


def configure(
    db: Session,
    instance: PluginInstance,
    *,
    directory: str | None = None,
    python: str | None = None,
    listen_lan: bool | None = None,
    keep_running: bool | None = None,
    extra_args: str | None = None,
    port: int | None = None,
    mode: str | None = None,
    shared_models: list[str] | None = None,
    idle_stop_minutes: int | None = None,
    confirm_run_code: bool = False,
) -> None:
    """建或改这个连接的本机服务。**换一个要运行的东西(目录、解释器)要确认过**(`confirm_run_code`):起它就是在这台
    机器上运行那个目录里的代码。端口只能停着改(改完让插件把按旧地址存的本地数据搬过去)。在跑的时候改别的,下次起生效。

    这里建、改的是「用我自己装的」;让 Mosael 装的那一份由安装建(`prepare_install`)。它的端口、局域网、保持运行、附加参数
    照样在这里改;给了目录就是换成「用我自己装的」(安装目录留着,第三步的卸载再管它)。正在装的时候不能换。"""
    if mode is not None and mode != records.DIRECTORY:
        raise LocalServiceError("localServiceErr_unknownMode", status=422, mode=mode)
    row = records.row_of(db, instance.id)
    switching = row is not None and row.mode != records.DIRECTORY and (mode is not None or directory is not None)
    if (switching or directory is not None) and installer.installing(instance.id):
        raise LocalServiceError("localServiceErr_installing")
    if switching and directory is None:
        raise LocalServiceError("localServiceErr_noDirectory", status=422)
    new_directory = directory.strip() if directory is not None else (row.directory if row else "")
    new_python = python.strip() if python is not None else (row.python if row else "")
    if not new_directory:
        raise LocalServiceError("localServiceErr_noDirectory", status=422)
    runs_something_new = row is None or switching or new_directory != row.directory or new_python != row.python
    if runs_something_new and not confirm_run_code:
        raise LocalServiceError("localServiceErr_confirmRequired", status=422)
    args = records.split_args(extra_args) if extra_args is not None else None
    if row is None:
        records.create(
            db, instance, directory=new_directory, python=new_python, listen_lan=bool(listen_lan),
            keep_running=bool(keep_running), extra_args=args or [],
        )
        return
    process = supervisor.get(instance.id)
    if port is not None and port != row.port:
        if process is not None and process.active:
            raise LocalServiceError("localServiceErr_stopFirst")
        records.check_port(db, instance.id, port)
        before, after = records.address(row.port), records.address(port)
        row.port = port
        db.flush()
        inst.set_config(db, instance, {SERVICE_ADDRESS_FIELD: after}, notify=False)
        try:
            plugin_ops.readdress(db, instance, row, before, after)
        except Exception:  # noqa: BLE001 — 搬不过去只是少了缓存(下次列模型库时重建),不挡改端口
            logger.warning("本机服务 %s 改端口后,插件没搬动按旧地址存的数据", instance.id, exc_info=True)
    if switching:
        row.mode, row.python_minor = records.DIRECTORY, ""
    row.directory, row.python = new_directory, new_python
    if listen_lan is not None:
        row.listen_lan = listen_lan
    if keep_running is not None:
        row.keep_running = keep_running
    if args is not None:
        row.extra_args = args
    if shared_models is not None:
        row.shared_models = _checked_shared(db, instance, row, shared_models)
    if idle_stop_minutes is not None:
        low, high = IDLE_MINUTES_RANGE
        if not low <= idle_stop_minutes <= high:
            raise LocalServiceError("localServiceErr_badIdleMinutes", status=422, low=low, high=high)
        row.idle_stop_minutes = idle_stop_minutes
    db.flush()


def create_connection(
    db: Session,
    package_id: str,
    *,
    mode: str,
    config: dict[str, Any] | None = None,
    name: str = "",
    owner_user_id: str = "",
    directory: str = "",
    python: str = "",
    confirm_run_code: bool = False,
    grant: Collection[str] = (),
) -> PluginInstance:
    """新建一个连接,一开始就定下它在本机哪种方式跑(插件页「新建连接」弹窗)。建连接、建这一行、选端口、把地址写进
    `server_url`,**同一个事务里做完、不提交**:哪一步不成(没确认过、目录空着、插件没声明服务、找不到空端口),调用方回滚,
    连接也不留下;成了由调用方 `inst.commit_created`。

    **地址归宿主分**:`server_url`(SERVICE_ADDRESS_FIELD)客户端给了也不用 —— 清单里它是必填的,本机的两种填的是宿主选的
    那个端口,不是让客户端先编一个。用我自己装的走 `configure`(要 `confirm_run_code`);让 Mosael 装的只建这一行(目录是宿主分的
    安装目录、还没装好),不开始装:装之前人要先看安装计划。"""
    if mode not in records.MODES:
        raise LocalServiceError("localServiceErr_unknownMode", status=422, mode=mode)
    fields = {key: value for key, value in (config or {}).items() if key != SERVICE_ADDRESS_FIELD}
    instance = inst.add(db, package_id, fields, name, owner_user_id=owner_user_id, grant=grant)
    if mode == records.DIRECTORY:
        configure(db, instance, directory=directory, python=python, confirm_run_code=confirm_run_code)
    else:
        records.make_managed(db, instance)
    return instance


def _checked_shared(db: Session, instance: PluginInstance, row: LocalService, folders: list[str]) -> list[str]:
    """共用的模型文件夹存之前:去掉空的、重复的,最多 MAX_SHARED 处;**插件认得出每一处**才存(要么 ComfyUI 的 models、要么
    A1111 / Forge,而且不是它自己的模型文件夹),认不出的照插件的原话说是哪一处、为什么。在跑的话下次起生效。"""
    cleaned = list(dict.fromkeys(one.strip() for one in folders if one and one.strip()))
    if len(cleaned) > MAX_SHARED:
        raise LocalServiceError("localServiceErr_tooManyShared", status=422, limit=MAX_SHARED)
    if not cleaned:
        return []
    found = plugin_ops.model_folders(db, instance, row, cleaned)
    bad = next((one for one in found["folders"] if not one["ok"]), None)
    if bad is not None or len(found["folders"]) != len(cleaned):
        raise LocalServiceError("localServiceErr_sharedNotRecognized", status=422,
                                detail=bad["problem"] if bad is not None else ", ".join(cleaned))
    return cleaned


def model_folders(db: Session, instance: PluginInstance) -> dict[str, Any]:
    """连接页上「共用的模型文件夹」那一块:每一处认成什么、对上哪几个模型目录;它在跑的话加载了没有、看到几个模型(刚加的要
    重启才加载)。另外列出卸载时保留下来的模型(`kept-models` 下),可以一键加进来。"""
    row = _require_row(db, instance)
    shared = list(row.shared_models or [])
    found = plugin_ops.model_folders(db, instance, row, shared) if shared else {"folders": [], "running": False}
    taken = {_directory_key(one) for one in shared}
    found["suggestions"] = [str(one) for one in records.kept_models() if _directory_key(str(one)) not in taken]
    return found


def remove(db: Session, instance: PluginInstance) -> None:
    """不用本机服务了(回到「连一台服务器」):停掉,删掉这一行。连接的地址留着,用户自己改成要连的那台。
    让 Mosael 装的那一份的安装目录留着(再选「让 Mosael 装」就接着用它;删它是第三步的卸载)。正在装的先取消。"""
    if installer.installing(instance.id):
        raise LocalServiceError("localServiceErr_installing")
    supervisor.forget(instance.id)
    row = records.row_of(db, instance.id)
    if row is not None:
        db.delete(row)


# ---------------------------------------------------------------------------
# 卸载(删连接、卸载插件时;ADR 0041 §4)
# ---------------------------------------------------------------------------


def _tree_bytes(path: Path) -> int:
    """一个目录占多少字节(不跟着链接走)。"""
    total = 0
    for folder, _dirs, names in os.walk(path):
        for name in names:
            try:
                total += os.lstat(os.path.join(folder, name)).st_size
            except OSError:
                continue
    return total


def _remove_tree(path: Path) -> None:
    """删宿主分的那个安装目录:它本身是链接就只删链接;里面的链接 rmtree 也只删链接,不跟着出去删别处的东西。"""
    if path.is_symlink():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def footprint(db: Session, instance: PluginInstance) -> dict[str, Any] | None:
    """这个连接在 `<数据目录>/local-services/<连接>/` 下留着什么:没有这个目录是 None;有就问插件是不是一份让 Mosael 装的
    (`installed`;选目录那一种这里只有宿主写的共用模型配置)、模型文件夹多大,再量一下整个目录。删连接、卸载插件的确认框照它问。"""
    root = records.install_root(instance.id)
    if not (root.is_dir() or root.is_symlink()):
        return None
    service = records.service_of(db, instance, records.row_of(db, instance.id))
    told = plugin_ops.uninstall(db, instance, service.key, root)
    return {
        "instance_id": instance.id,
        "name": instance.name,
        "directory": str(root),
        "installed": told["installed"],
        "bytes": _tree_bytes(root) if not root.is_symlink() else 0,
        "models_bytes": told["models_bytes"] if told["models"] is not None else 0,
        "has_models": told["models"] is not None,
        "keep_to": str(records.kept_models_target(instance.name)),
    }


def remove_install(db: Session, instance: PluginInstance, *, keep_models: bool) -> str:
    """删掉这个连接的安装目录(调用方先 forget 停掉它、取消正在装的)。`keep_models`:先问插件模型文件夹在哪,挪到
    `kept-models/<连接的名字>`(下次加共用的模型文件夹时会提示它)。只删宿主分的那个目录 —— 选目录那一种指向的用户目录从来不碰。
    最后一份让 Mosael 装的没了,共用的 pip 缓存一起清。交回模型挪到了哪(没保留是空串)。"""
    root = records.install_root(instance.id)
    if not (root.is_dir() or root.is_symlink()):
        return ""
    kept = ""
    if keep_models and not root.is_symlink():
        service = records.service_of(db, instance, records.row_of(db, instance.id))
        models = plugin_ops.uninstall(db, instance, service.key, root)["models"]
        if models is not None:
            target = records.kept_models_target(instance.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                models.replace(target)
            except OSError as exc:
                if exc.errno != errno.EXDEV:
                    raise
                shutil.move(str(models), str(target))  # 数据目录跨盘挂载时
            kept = str(target)
            logger.info("本机服务 %s 的模型保留到 %s", instance.id, target)
    _remove_tree(root)
    logger.info("删掉了本机服务 %s 的安装目录 %s", instance.id, root)
    others = db.scalars(select(LocalService.instance_id).where(LocalService.mode == records.MANAGED,
                                                               LocalService.instance_id != instance.id)).first()
    if others is None:
        _remove_tree(records.pip_cache_dir())
    return kept


def package_roots(db: Session, package_id: str) -> list[PluginInstance]:
    """这个插件的连接里,在 `<数据目录>/local-services/` 下留着目录的那几个(卸载插件前要问一声的;不问插件,它可能用不了)。"""
    return [instance for instance in db.scalars(select(PluginInstance).where(PluginInstance.package_id == package_id))
            if records.install_root(instance.id).is_dir() or records.install_root(instance.id).is_symlink()]


def package_installs(db: Session, package_id: str) -> list[dict[str, Any]]:
    """卸载插件的确认框要的:留着目录的每个连接,是不是一份让 Mosael 装的、多大、模型多大(问插件)。"""
    return [one for instance in package_roots(db, package_id) if (one := footprint(db, instance)) is not None]


def forget_instance(instance_id: str) -> None:
    """连接要删了:正在装的先取消、等它停下,再停掉它的本机服务(那一行随外键级联删)。"""
    installer.forget(instance_id)
    supervisor.forget(instance_id)


def forget_package(db: Session, package_id: str) -> None:
    """插件要卸载了:它每个连接正在装的先取消,本机服务都先停掉。"""
    for instance_id in db.scalars(select(PluginInstance.id).where(PluginInstance.package_id == package_id)):
        installer.forget(instance_id)
        supervisor.forget(instance_id)


# ---------------------------------------------------------------------------
# 起、停
# ---------------------------------------------------------------------------


def _service_env(db: Session, instance: PluginInstance, plugin_env: dict[str, str]) -> dict[str, str]:
    """本机服务进程的环境:后端自己的环境(PATH、显卡驱动要的那些)去掉宿主内部的几样,加上插件那一半,再加宿主决定的:
    HuggingFace 镜像(沿用设置里的)和这个连接的出站代理。

    去掉的:`MOSAEL_*`(宿主和自己、和插件之间的约定,不该漏给别人的程序)、代理变量(后端进程里装的是全局那份,
    这个连接可能直连或走自己的代理 —— 由 egress 重新给)、PyInstaller 冻结版自己用的 `_PYI*` / `_MEI*`。
    插件给的盖不掉宿主决定的这几样。
    """
    from app.ai.runtime import config as runtime_config

    def host_only(key: str) -> bool:
        upper = key.upper()
        return upper.startswith(HOST_PREFIX) or upper in EGRESS_KEYS or upper.startswith(("_PYI", "_MEI"))

    env = {key: value for key, value in os.environ.items() if not host_only(key)}
    env.update({key: value for key, value in plugin_env.items() if not host_only(key) and key.upper() != "HF_ENDPOINT"})
    manifest = inst.manifest_for(db, instance)
    env.update(plugin_egress.resolve(db, instance, manifest).child_env())
    env["HF_ENDPOINT"] = runtime_config.get().hf_endpoint
    return env


def _launch_spec(db: Session, instance: PluginInstance, row: LocalService) -> LaunchSpec:
    told = plugin_ops.launch(db, instance, row)
    return LaunchSpec(
        argv=told["argv"], env=_service_env(db, instance, told["env"]), cwd=told["cwd"], port=row.port,
        health_path=told["health_path"], ready_timeout=told["ready_timeout"], directory=row.directory,
    )


def _respawn(instance_id: str) -> LaunchSpec:
    """崩了要重起时(在看护线程里):自开一个会话,按现在的配置再问插件一次怎么起。"""
    with SessionLocal() as db:
        instance = inst.get(db, instance_id)
        return _launch_spec(db, instance, _require_row(db, instance))


def _became_ready(instance_id: str) -> None:
    """就绪了:让替宿主做事的那一侧重新问一遍插件(目录在它停着时没刷新,见 host_capabilities.notify)。"""
    with SessionLocal() as db:
        instance = db.get(PluginInstance, instance_id)
        if instance is not None:
            host_capabilities.notify(db, instance, refresh=True)


def start(db: Session, instance: PluginInstance) -> None:
    """起(已经在跑、正在起、正在重启就什么都不做)。起不来当场抛:目录被别的连接占着、端口被占、插件说这个目录不对、
    找不到解释器;让 Mosael 装的那一份还没装好、正在装、运行环境要重建。抛之前状态停在「起不来」的(插件说不行、起不来),
    界面上看得到原因。"""
    row = _require_row(db, instance)
    _runnable(db, instance, row)
    _launch(db, instance, row)


def _launch(db: Session, instance: PluginInstance, row: LocalService) -> None:
    """真的起进程(不看装没装好:安装的最后一步「试起一次」也走这里)。"""
    process = _process(instance.id)
    with process.start_lock:
        if process.active:
            return
        holder = supervisor.claim(instance.id, _directory_key(row.directory))
        if holder is not None:
            other = db.get(PluginInstance, holder)
            raise LocalServiceError("localServiceErr_directoryBusy", name=other.name if other else holder)
        try:
            if supervisor.port_in_use(row.port):
                raise LocalServiceError("localServiceErr_portBusy", port=row.port)
            spec = _launch_spec(db, instance, row)
            process.on_ready = partial(_became_ready, instance.id)
            process.launch(spec, respawn=partial(_respawn, instance.id))
        except Exception:
            supervisor.release(instance.id)
            raise


def stop(instance_id: str) -> None:
    """停(先请它自己退,10 秒后强杀整组)。没在跑就什么都不做。"""
    process = supervisor.get(instance_id)
    if process is not None:
        process.stop()


def restart(db: Session, instance: PluginInstance, *, wait: bool = False) -> None:
    """宿主自己重启:停了再起(插件装完节点要重启时也走这里,不让插件去重启它 —— 那会让宿主以为它崩了)。
    `wait`:等它就绪再回来(起不来照抛)。"""
    stop(instance.id)
    if wait:
        ensure_running(db, instance)
    else:
        start(db, instance)


def ensure_running(db: Session, instance: PluginInstance) -> None:
    """**用到时起**(拍板 4):停着就起,等它就绪再回来;已经在跑就立刻回来。起不来照抛,原因是它停在「起不来」时的那一句。

    等的时候调用方的会话还拿着一条连接(只读过,SQLite 那头没有攥着的事务)。插件调用那条路不走这里:它先交还
    连接再等(见 begin_using)。"""
    begin_using(db, instance)()


def begin_using(
    db: Session, instance: PluginInstance, *, progress: service_gate.Progress | None = None,
) -> Callable[[], None]:
    """「用到时起」的前一半:停着就替它起进程(报一句进度),**不等**;交回「等它就绪」。后一半不碰数据库,
    调用方可以先交还连接再调它(插件调用在 plugins/tools._plugin_slot 里等)。本来就在跑,交回的那个立刻回来。"""
    row = _require_row(db, instance)
    process = _process(instance.id)
    process.touch()
    if process.state == RUNNING:
        return _ready_now
    title = _title(db, instance, row)
    if progress is not None:
        progress(0.0, tr("localService_starting", name=title))
    start(db, instance)
    return partial(_wait_ready, process, title)


def _ready_now() -> None:
    return None


def touch(instance_id: str) -> None:
    """有人在用它(插件调用用完了、工作台 / 内嵌编辑器还开着):闲置的钟从现在算。没在管的就什么都不做,也不替它起。"""
    process = supervisor.get(instance_id)
    if process is not None:
        process.touch()


def _wait_ready(process: ServiceProcess, title: str) -> None:
    """等它从「启动中 / 重启中」落定。起不来照抛,原因是它停在「起不来」时的那一句。"""
    state = process.wait_settled(process.ready_timeout + ENSURE_MARGIN_SECONDS)
    if state == RUNNING:
        return
    if state == FAILED and process.error is not None:
        raise LocalServiceError.relay(process.error)
    if state == STOPPED:
        raise LocalServiceError("localServiceErr_stopped", name=title)
    raise LocalServiceError("localServiceErr_readyTimeout", seconds=int(process.ready_timeout))


def _prepare(
    db: Session, instance: PluginInstance, start_it: bool, progress: service_gate.Progress,
) -> service_gate.Prepared:
    """插件域的 `service_gate.prepare`:每一次插件调用之前。`start_it` 为假(后台刷新目录)时只看、不起。"""
    row = records.row_of(db, instance.id)
    if row is None:
        return service_gate.NO_SERVICE
    env = {SERVICE_ENV: row.service, SHARED_ENV: json.dumps(list(row.shared_models or []), ensure_ascii=False)}
    if start_it:
        return service_gate.Prepared(env=env, wait_ready=begin_using(db, instance, progress=progress),
                                     done=partial(touch, instance.id))
    process = supervisor.get(instance.id)
    if process is None or process.state != RUNNING:
        # 后台刷新目录不替它起:说它此刻是什么状态(停着 / 正在起 / 起不来 / 还没装好……),连接页照这一句摆
        found = issue_of(db, instance)
        raise found[1] if found is not None else LocalServiceError("localServiceIssue_stopped", name=_title(db, instance, row))
    return service_gate.Prepared(env=env)


def _idle(db: Session, instance: PluginInstance) -> bool:
    """插件域的 `service_gate.idle`:有本机服务、而它现在没在跑。"""
    if records.row_of(db, instance.id) is None:
        return False
    process = supervisor.get(instance.id)
    return process is None or process.state != RUNNING


#: 组装根交给插件域的那道缝(见 app.main._wire_seams)。
GATE = service_gate.Gate(prepare=_prepare, idle=_idle, explain=_explain)


# ---------------------------------------------------------------------------
# 本机发现、补装
# ---------------------------------------------------------------------------


def discover(db: Session, package_id: str) -> list[dict[str, str]]:
    """本机有没有已经在跑的这种服务(插件页上的「本机发现一个,要连上吗」)。插件没声明服务就是空的。"""
    package = db.get(PluginPackage, package_id)
    if package is None:
        return []
    manifest = manifest_of(package)
    if not manifest.services:
        return []
    return plugin_ops.discover(db, package_id, manifest.services[0].key, manifest)


def add_nodes(db: Session, instance: PluginInstance) -> dict[str, Any]:
    """补装插件说缺的节点(用户确认过之后)。装进去要下次起才加载 —— 在跑的话由界面提示重启。"""
    return plugin_ops.add_nodes(db, instance, _require_row(db, instance))


# ---------------------------------------------------------------------------
# 让 Mosael 装(ADR 0041 §4)
# ---------------------------------------------------------------------------


def _base_python_or_fail() -> str:
    base = base_python()
    if not base:
        raise LocalServiceError("localServiceErr_noBasePython", status=422)
    return base


def plan(db: Session, instance: PluginInstance) -> dict[str, Any]:
    """确认页要的:插件说这台机器能不能装、装哪种 PyTorch、要多少空间、分几步(接着装时哪几步已经做完)、要从哪几处下载;
    宿主再加上自己那一步(试起一次)和装在哪。只问、不写(会跑一次随包的 Python、Windows 上问 nvidia-smi)。"""
    row = records.row_of(db, instance.id)
    service = records.service_of(db, instance, row)
    root = str(records.install_root(instance.id))
    found = plugin_ops.plan(db, instance, service.key, {"directory": root, "python": _base_python_or_fail(),
                                                         "sources": sources.for_plugin()})
    installed = row is not None and row.mode == records.MANAGED and bool(row.python_minor) and not needs_rebuild(row)
    found["steps"].append({"key": installer.TRIAL, "title": tr("localServiceInstall_trial"), "done": installed})
    egress = plugin_egress.resolve(db, instance, inst.manifest_for(db, instance))
    configured = sources.labels()
    downloads = [{**one, "bypass": egress.bypasses(one["url"]), "setting": configured.get(one["source"], "")}
                 for one in found["downloads"]]
    return {**found, "downloads": downloads, "route": _route(instance, egress), "directory": root}


def _route(instance: PluginInstance, egress: plugin_egress.Egress) -> dict[str, str]:
    """装的时候下载走哪条路 —— 插件进程拿到的就是这一份(`egress.resolve`,和 child_env 同一个决定),安装计划照着说:
    `global` 跟随全局、全局设了代理;`own` 这个连接自己的代理;`direct` 这个连接直连;`system` 跟随全局、全局没设代理
    (Mosael 什么都不给,下载和 pip 照系统的代理设置走,系统也没设就是直连)。代理地址里的账号密码不摆出来。"""
    if instance.network_mode == plugin_egress.DIRECT:
        return {"kind": "direct", "proxy": ""}
    if instance.network_mode == plugin_egress.PROXY:
        return {"kind": "own", "proxy": egress.shown_proxy}
    if egress.proxy_url:
        return {"kind": "global", "proxy": egress.shown_proxy}
    return {"kind": "system", "proxy": ""}


def prepare_install(db: Session, instance: PluginInstance) -> None:
    """装之前:这个连接改成(或建成)「让 Mosael 装」,端口选好、地址写进 `server_url`。在跑的先停(重建运行环境要换掉 venv;
    原来是「用我自己装的」的也不该接着跑那一份)。**调用方提交之后**再 `begin_install`:安装线程要读这一行。"""
    if installer.installing(instance.id):
        raise LocalServiceError("localServiceErr_installing")
    _base_python_or_fail()
    stop(instance.id)
    records.make_managed(db, instance)


def begin_install(db: Session, instance: PluginInstance, *, flavour: str) -> None:
    """开始装(或接着装、重建运行环境):后台线程里先让插件做它那几步,再试起一次。`flavour` 是确认页上那种 PyTorch ——
    插件装之前再看一次这台机器,对不上就不装(换了驱动之类),请人重新看一眼安装计划。"""
    row = _require_row(db, instance)
    if row.mode != records.MANAGED:
        raise LocalServiceError("localServiceErr_notManaged", status=422)
    base = _base_python_or_fail()
    manifest = inst.manifest_for(db, instance)
    installer.begin(instance.id, install_log_path(instance.id), author_locale=manifest.default_locale,
                    work=partial(_install, instance.id, row.service, base, flavour))


def cancel_install(instance_id: str) -> bool:
    """取消正在装的(插件停在手上那一步,下次接着装)。没在装回 False。"""
    return installer.cancel(instance_id)


def recent_install_logs(instance_id: str, limit: int = 400) -> list[str]:
    """安装的日志(每一步的命令、pip 说的话)。"""
    run = installer.current(instance_id)
    log = run.log if run is not None else ServiceLog(install_log_path(instance_id))
    return log.tail(max(1, min(limit, MAX_LOG_LINES)))


#: 试起那一步等就绪时多久看一眼取消了没有。
_TRIAL_POLL_SECONDS = 0.5


def _plugin_payload(instance_id: str, row: LocalService) -> dict[str, Any]:
    """装、换版本都给插件的那几样:安装目录、下载源、日志文件、共用的 pip 缓存。"""
    return {"directory": row.directory, "sources": sources.for_plugin(), "log": str(install_log_path(instance_id)),
            "pip_cache": str(records.pip_cache_dir())}


def _hooks(run: installer.InstallRun, *, cancellable: bool = True) -> StreamHooks:
    """插件那几步的流式进度交给这一次;`cancellable` 为假时不看取消(试起没通过、正在换回去 —— 半截的环境不能留)。"""
    return StreamHooks(on_progress=lambda _fraction, _message: None, on_task=lambda _task: None,
                       is_cancelled=run.cancel.is_set if cancellable else _never, on_step=run.on_step)


def _never() -> bool:
    return False


def _install(instance_id: str, service: str, base: str, flavour: str, run: installer.InstallRun) -> None:
    """安装线程:插件做它那几步(流式),宿主试起一次;健康检查通过了才记成装好(`python_minor`)。起来之后就让它开着 ——
    装完下一步多半就是去模型库(退出 Mosael 时照样停)。"""
    with SessionLocal() as db:
        instance = inst.get(db, instance_id)
        row = _require_row(db, instance)
        payload = {**_plugin_payload(instance_id, row), "python": base, "flavour": flavour}
        plugin_ops.install(db, instance, service, payload, _hooks(run))
    _trial(instance_id, run)
    with unit_of_work() as db:
        row = _require_row(db, inst.get(db, instance_id))
        row.python_minor = base_minor()


def _trial(instance_id: str, run: installer.InstallRun) -> None:
    """宿主那一步:试起一次 —— 走的就是以后真起它的那条路,健康检查通过才算成。取消就停下它;起不来停在这一步,原因原样转述
    (带着 key,按看的人的语言说),日志在服务自己的日志里。"""
    run.begin_trial()
    with SessionLocal() as db:
        instance = inst.get(db, instance_id)
        _launch(db, instance, _require_row(db, instance))
    process = _process(instance_id)
    deadline = time.monotonic() + process.ready_timeout + ENSURE_MARGIN_SECONDS
    state = process.state
    while state in (STARTING, RESTARTING) and time.monotonic() < deadline and not run.cancel.is_set():
        state = process.wait_settled(_TRIAL_POLL_SECONDS)
    if run.cancel.is_set():
        stop(instance_id)
        raise installer.InstallCancelled
    if state != RUNNING:
        if state == FAILED and process.error is not None:
            raise LocalServiceError.relay(process.error)
        stop(instance_id)
        raise LocalServiceError("localServiceErr_readyTimeout", seconds=int(process.ready_timeout))


# ---------------------------------------------------------------------------
# 让 Mosael 装的那一份换版本(ADR 0041 §4「更新、回滚」)
# ---------------------------------------------------------------------------


def versions(db: Session, instance: PluginInstance) -> dict[str, str]:
    """装着哪个版本、能更新到哪个、能回到哪个、有没有被打断没做完的(插件读安装目录里的记录;只看)。"""
    row = _require_row(db, instance)
    if row.mode != records.MANAGED:
        raise LocalServiceError("localServiceErr_notManaged", status=422)
    return plugin_ops.versions(db, instance, row)


def _changeable(db: Session, instance: PluginInstance) -> tuple[LocalService, dict[str, str]]:
    """换版本之前:是让 Mosael 装的、装好了、运行环境不用重建、没在装也没在换。交回这一行和插件说的版本。"""
    row = _require_row(db, instance)
    if row.mode != records.MANAGED:
        raise LocalServiceError("localServiceErr_notManaged", status=422)
    _runnable(db, instance, row)
    return row, plugin_ops.versions(db, instance, row)


def begin_update(db: Session, instance: PluginInstance, *, version: str = "") -> str:
    """开始更新到 `version`(没说就是插件钉死的最新那个):先停下它(源码要换),后台让插件换源码、装依赖,再试起一次 ——
    没通过就换回去。上一次换版本没做完的先「换回」。交回要换到的版本。"""
    row, told = _changeable(db, instance)
    if told["unfinished"]:
        raise LocalServiceError("localServiceErr_changeUnfinished", version=told["previous"])
    target = version.strip() or told["update"]
    if not target:
        raise LocalServiceError("localServiceErr_noUpdate", version=told["current"])
    stop(instance.id)
    manifest = inst.manifest_for(db, instance)
    installer.begin(instance.id, install_log_path(instance.id), author_locale=manifest.default_locale,
                    work=partial(_update, instance.id, row.service, target), kind=installer.UPDATE, target=target)
    return target


def begin_rollback(db: Session, instance: PluginInstance) -> str:
    """开始回到上一版(也是收拾被打断的更新 / 回退的那一下):先停下它,后台让插件换回源码、装回依赖,再试起一次。交回要回到的版本。"""
    row, told = _changeable(db, instance)
    if not told["previous"]:
        raise LocalServiceError("localServiceErr_noPrevious")
    stop(instance.id)
    manifest = inst.manifest_for(db, instance)
    installer.begin(instance.id, install_log_path(instance.id), author_locale=manifest.default_locale,
                    work=partial(_rollback, instance.id, row.service), kind=installer.ROLLBACK, target=told["previous"])
    return told["previous"]


def _reason(error: LocalizedError) -> Any:
    """一句失败原因拼进另一句里时:我们自己的文案留成 key(按读的人的语言再翻),别的原样。"""
    return fragment(error.key, **error.params) if is_message_key(error.key) else str(error)


def _update(instance_id: str, service: str, version: str, run: installer.InstallRun) -> None:
    """更新线程:插件换源码、装依赖(没成它自己换回去,原因照说);宿主试起一次。**试起没通过(或者这时取消)就换回去**:
    让插件回到上一版(不看取消),再说「没成,已经换回 x」;换回去也出错就两件都说,请人点「换回」。成了就让它开着。"""
    with SessionLocal() as db:
        instance = inst.get(db, instance_id)
        row = _require_row(db, instance)
        told = plugin_ops.update(db, instance, service, {**_plugin_payload(instance_id, row), "version": version}, _hooks(run))
    previous = str(told.get("previous") or "")
    try:
        _trial(instance_id, run)
    except (LocalizedError, installer.InstallCancelled) as failed:
        stop(instance_id)
        run.say({one: t("localServiceUpdate_goingBack", one, version=previous) for one in ("zh", "en")})
        try:
            with SessionLocal() as db:
                instance = inst.get(db, instance_id)
                plugin_ops.rollback(db, instance, service, _plugin_payload(instance_id, _require_row(db, instance)),
                                    _hooks(run, cancellable=False))
        except Exception as back:  # noqa: BLE001 — 换回去失败的原因要说给人听,连同试起没通过的那个
            logger.warning("本机服务 %s 更新到 %s 试起没通过,换回 %s 也没成", instance_id, version, previous, exc_info=True)
            detail = _reason(back) if isinstance(back, LocalizedError) else f"{type(back).__name__}: {back}"
            reason = _reason(failed) if isinstance(failed, LocalizedError) else fragment("localServiceUpdate_cancelled")
            raise LocalServiceError("localServiceErr_updateRollbackFailed", version=version, previous=previous, reason=reason,
                                    detail=detail) from back
        if isinstance(failed, installer.InstallCancelled):
            raise
        raise LocalServiceError("localServiceErr_updateRolledBack", version=version, previous=previous,
                                reason=_reason(failed)) from failed


def _rollback(instance_id: str, service: str, run: installer.InstallRun) -> None:
    """回退线程:插件换回源码、装回依赖,宿主试起一次。"""
    with SessionLocal() as db:
        instance = inst.get(db, instance_id)
        plugin_ops.rollback(db, instance, service, _plugin_payload(instance_id, _require_row(db, instance)), _hooks(run))
    _trial(instance_id, run)


# ---------------------------------------------------------------------------
# 后端起来、退出
# ---------------------------------------------------------------------------


def adopt_orphans() -> int:
    """后端启动时:上一个后端起的、没来得及停的那几个,三样都对得上(pid 在、命令行一样、健康检查通过)就接回来当作
    运行中;对不上的不碰它,只删掉 pid 文件。返回接回了几个。"""
    adopted = 0
    with SessionLocal() as db:
        for record in pidfiles.read_all():
            row = records.row_of(db, record.instance_id)
            spec_health = f"http://127.0.0.1:{record.port}{record.health_path}"
            if row is None or not pidfiles.same_process(record) or not supervisor.healthy(spec_health):
                logger.info("本机服务 %s 上次记下的进程 %s 对不上,不接回(也不动它)", record.instance_id, record.pid)
                pidfiles.remove(record.instance_id)
                continue
            if supervisor.claim(record.instance_id, _directory_key(row.directory)) is not None:
                pidfiles.remove(record.instance_id)
                continue
            process = _process(record.instance_id)
            process.on_ready = partial(_became_ready, record.instance_id)
            process.adopt(record, respawn=partial(_respawn, record.instance_id))
            adopted += 1
            logger.info("接回了本机服务 %s(pid %s)", record.instance_id, record.pid)
    return adopted


def start_kept_running() -> threading.Thread:
    """「保持运行」的:Mosael 一启动就起,不等用到(在后台起,一台起得慢的不该拖慢启动)。"""

    def run() -> None:
        with SessionLocal() as db:
            for row in list(db.scalars(select(LocalService).where(LocalService.keep_running.is_(True)))):
                instance = db.get(PluginInstance, row.instance_id)
                process = supervisor.get(row.instance_id)
                if instance is None or (process is not None and process.active):
                    continue
                try:
                    start(db, instance)
                except Exception:  # noqa: BLE001 — 一个起不来不该挡住下一个;原因在它的状态里
                    db.rollback()
                    logger.warning("保持运行的本机服务 %s 没起来", row.instance_id, exc_info=True)

    thread = threading.Thread(target=run, daemon=True, name="local-services-keep-running")
    thread.start()
    return thread


def check_idle() -> list[str]:
    """闲置自动停,看一遍(看护线程每分钟一次;测试直接调):在跑的、不是「保持运行」的、设了闲置分钟数的,闲置够久了就**先问它
    有没有活**(插件问它的任务队列):有在跑、在排的就当它在用(钟重新算);问不到(插件失败、它不应答)不停 —— 宁可多开一会儿;
    空的就停,记下是闲置停的(界面说「闲置 N 分钟,自动停了」)。下次用到时照常起(用到时起)。交回停了哪几个连接。"""
    stopped: list[str] = []
    for process in supervisor.everyone():
        if process.state != RUNNING:
            continue
        instance_id = process.instance_id
        with SessionLocal() as db:
            row = records.row_of(db, instance_id)
            instance = db.get(PluginInstance, instance_id)
            if row is None or instance is None or row.keep_running or row.idle_stop_minutes <= 0:
                continue
            if process.idle_seconds() < row.idle_stop_minutes * SECONDS_PER_MINUTE or installer.installing(instance_id):
                continue
            asked_at = process.last_used
            try:
                busy = plugin_ops.busy(db, instance, row)
            except Exception:  # noqa: BLE001 — 问不到它有没有活就不停(在跑的任务比显存要紧)
                logger.warning("本机服务 %s 闲置够久了,但问不到它有没有活,先不停", instance_id, exc_info=True)
                continue
        if busy:
            process.touch()
            continue
        if process.last_used != asked_at:
            continue  # 问的这一会儿又有人用上了
        logger.info("本机服务 %s 闲置 %s 分钟,自动停下(释放显存)", instance_id, row.idle_stop_minutes)
        process.stop()
        process.idle_stopped = True
        stopped.append(instance_id)
    return stopped


class _IdleWatch:
    """闲置自动停的看护线程:每 IDLE_CHECK_SECONDS 看一遍(check_idle)。后端起来时开,退出时停。"""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="local-services-idle")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(IDLE_CHECK_SECONDS):
            try:
                check_idle()
            except Exception:  # noqa: BLE001 — 看一遍出错不该让看护线程死掉
                logger.exception("闲置自动停看一遍时出错")


_idle_watch = _IdleWatch()


def start_idle_watch() -> None:
    """后端起来时:开闲置自动停的看护线程。"""
    _idle_watch.start()


def stop_all() -> None:
    """后端退出时:Mosael 起的进程不留在后台(拍板 4)。正在装的先取消(插件停掉 pip、记下停在哪一步,下次接着装),
    再停全部本机服务 —— 几个一起停,不让一个慢的拖着别的。"""
    _idle_watch.stop()
    installer.cancel_all()
    running = [process for process in supervisor.everyone() if process.active]
    threads = [threading.Thread(target=process.stop, daemon=True) for process in running]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=supervisor.STOP_GRACE_SECONDS + 5.0)


__all__ = [
    "ACTIVE", "FAILED", "GATE", "ISSUE_KEYS", "RESTARTING", "RUNNING", "SERVICE_ENV", "SHARED_ENV", "STARTING", "STATES",
    "STOPPED", "LocalServiceError", "add_nodes", "adopt_orphans", "base_minor", "begin_install", "begin_rollback",
    "begin_update", "begin_using", "check_idle",
    "cancel_install", "configure", "create_connection", "detect", "discover", "ensure_running", "footprint", "forget_instance",
    "forget_package",
    "install_log_path", "issue_of", "log_path", "model_folders", "needs_rebuild", "package_installs", "package_roots", "plan", "prepare_install",
    "recent_install_logs", "recent_logs", "remove", "remove_install", "restart", "start", "start_idle_watch", "start_kept_running", "status",
    "stop", "stop_all", "touch", "versions",
]
