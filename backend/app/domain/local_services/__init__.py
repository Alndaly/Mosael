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
装(或接着装、重建运行环境)、取消,装好的那一份试起一次、健康检查通过才算装好。

**让 Mosael 装的那一份**(`mode = managed`)装在宿主分的 `<数据目录>/local-services/<连接>/`,目录就记这个(插件在里面认
源码和 `.venv`,认目录、怎么起和「用我自己装的」走同一条路)。它的 venv 是随包的 Python 建的:装好时记下 Python 小版本,
以后对不上(Mosael 升级换了随包的 Python)就不让起,连接页说「运行环境要重建」—— 再装一次,插件只重建 venv 和装进去的包,
源码和模型不动。

**谁能动它**:建、改、起、停都要部署管理员(路由那一层 `ensure_deployment_admin`)—— 起一个目录里的代码就是在这台
机器上运行它。用到时起不要:那是用一个管理员建好的连接,和用别人建好的连接一样。
"""

from __future__ import annotations

import functools
import logging
import os
import threading
import time
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.i18n import fragment, is_message_key, tr
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
        if installer.installing(instance.id):
            return said("installing")
        if not row.python_minor:
            return said("not_installed")
        if needs_rebuild(row):
            return said("rebuild", have=row.python_minor, want=base_minor())
    if state == STOPPED or process is None:
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
    db.flush()


def remove(db: Session, instance: PluginInstance) -> None:
    """不用本机服务了(回到「连一台服务器」):停掉,删掉这一行。连接的地址留着,用户自己改成要连的那台。
    让 Mosael 装的那一份的安装目录留着(再选「让 Mosael 装」就接着用它;删它是第三步的卸载)。正在装的先取消。"""
    if installer.installing(instance.id):
        raise LocalServiceError("localServiceErr_installing")
    supervisor.forget(instance.id)
    row = records.row_of(db, instance.id)
    if row is not None:
        db.delete(row)


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
    if process.state == RUNNING:
        return _ready_now
    title = _title(db, instance, row)
    if progress is not None:
        progress(0.0, tr("localService_starting", name=title))
    start(db, instance)
    return partial(_wait_ready, process, title)


def _ready_now() -> None:
    return None


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
    env = {SERVICE_ENV: row.service}
    if start_it:
        return service_gate.Prepared(env=env, wait_ready=begin_using(db, instance, progress=progress))
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


def _install(instance_id: str, service: str, base: str, flavour: str, run: installer.InstallRun) -> None:
    """安装线程:插件做它那几步(流式),宿主试起一次;健康检查通过了才记成装好(`python_minor`)。起来之后就让它开着 ——
    装完下一步多半就是去模型库(退出 Mosael 时照样停)。"""
    with SessionLocal() as db:
        instance = inst.get(db, instance_id)
        row = _require_row(db, instance)
        payload = {
            "directory": row.directory, "python": base, "flavour": flavour, "sources": sources.for_plugin(),
            "log": str(install_log_path(instance_id)), "pip_cache": str(records.pip_cache_dir()),
        }
        hooks = StreamHooks(on_progress=lambda _fraction, _message: None, on_task=lambda _task: None,
                            is_cancelled=run.cancel.is_set, on_step=run.on_step)
        plugin_ops.install(db, instance, service, payload, hooks)
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
        # 停在「试起一次」这一步(界面写明是哪一步);原因原样转述(带着 key,按看的人的语言说),日志在服务自己的日志里
        if state == FAILED and process.error is not None:
            raise LocalServiceError.relay(process.error)
        stop(instance_id)
        raise LocalServiceError("localServiceErr_readyTimeout", seconds=int(process.ready_timeout))
    with unit_of_work() as db:
        row = _require_row(db, inst.get(db, instance_id))
        row.python_minor = base_minor()


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


def stop_all() -> None:
    """后端退出时:Mosael 起的进程不留在后台(拍板 4)。正在装的先取消(插件停掉 pip、记下停在哪一步,下次接着装),
    再停全部本机服务 —— 几个一起停,不让一个慢的拖着别的。"""
    installer.cancel_all()
    running = [process for process in supervisor.everyone() if process.active]
    threads = [threading.Thread(target=process.stop, daemon=True) for process in running]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=supervisor.STOP_GRACE_SECONDS + 5.0)


__all__ = [
    "ACTIVE", "FAILED", "GATE", "RESTARTING", "RUNNING", "SERVICE_ENV", "STARTING", "STATES", "STOPPED",
    "LocalServiceError", "add_nodes", "adopt_orphans", "base_minor", "begin_install", "begin_using", "cancel_install",
    "configure", "detect", "discover", "ensure_running", "forget_instance", "forget_package", "install_log_path", "log_path",
    "needs_rebuild", "plan", "prepare_install", "recent_install_logs", "recent_logs", "remove", "restart", "start",
    "start_kept_running", "status", "stop", "stop_all",
]
