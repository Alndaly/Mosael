"""本机服务的那一行(`local_services` 表):人定下的东西 —— 在哪跑、哪个目录、哪个解释器、端口、局域网、保持运行、附加参数。

**端口建的时候选定**(从 FIRST_PORT 往上找第一个空的:没人在听、也没分给别的连接),写进连接的 `server_url`,以后一直用它:
插件按服务器地址分文件存每台服务器的本地数据,端口一变就对不上(ADR 0041 §1)。改端口在「高级」里,由调用方顺带让插件搬数据。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import LocalService, PluginInstance
from app.domain.local_services.errors import LocalServiceError
from app.domain.local_services.supervisor import port_in_use
from app.domain.plugins import instances as inst
from app.domain.plugins.manifest import SERVICE_ADDRESS_FIELD, Service

#: 在哪跑:「用我自己装的」(选一个目录)、「让 Mosael 装」(装在宿主分的目录里,ADR 0041 §4)。
DIRECTORY = "directory"
MANAGED = "managed"
MODES = (DIRECTORY, MANAGED)
#: 让 Mosael 装的那些装在数据目录下的这里,一个连接一个子目录。**不放插件的持久目录**:那个卸载插件时一起删,模型也会跟着没。
INSTALLS = "local-services"
#: 它们共用的 pip 缓存(接着装、重建运行环境时已经下过的包不重下;不撑大这个人自己的 pip 缓存)。
PIP_CACHE = "pip-cache"
#: 卸载时保留下来的模型(一份一个子目录)。
KEPT_MODELS = "kept-models"
#: 从这里往上找空端口。常见的本机 AI 服务缺省端口(ComfyUI 的 8188 一类)留给用户自己开的那一台。
FIRST_PORT = 8189
#: 往上最多找多少个。
PORT_SCAN = 200
PORT_RANGE = (1024, 65535)
#: 附加参数最多几项、每项多长。
MAX_ARGS = 40
MAX_ARG_CHARS = 500


def row_of(db: Session, instance_id: str) -> LocalService | None:
    return db.get(LocalService, instance_id)


def service_of(db: Session, instance: PluginInstance, row: LocalService | None = None) -> Service:
    """这个连接用的是清单里哪一种本机服务:记着的那种,还没记就是清单里的第一种。清单里一种都没有就抛。"""
    manifest = inst.manifest_for(db, instance)
    recorded = manifest.service(row.service) if row is not None else None
    if recorded is not None:
        return recorded
    if not manifest.services:
        raise LocalServiceError("localServiceErr_noService", status=422, name=manifest.name)
    return manifest.services[0]


def install_root(instance_id: str) -> Path:
    """让 Mosael 装的那一份装在哪:`<数据目录>/local-services/<连接>/`(里面是插件放的源码和 `.venv`)。"""
    return settings.data_dir / INSTALLS / instance_id


def pip_cache_dir() -> Path:
    return settings.data_dir / INSTALLS / PIP_CACHE


def kept_models_dir() -> Path:
    """卸载让 Mosael 装的那一份时选了「保留模型」,模型挪到这里(一份一个子目录),下次能当共用的模型文件夹加回来。"""
    return settings.data_dir / INSTALLS / KEPT_MODELS


def kept_models_target(name: str) -> Path:
    """保留下来的模型挪到哪:`kept-models/<连接的名字>`(去掉路径里不能有的字符;同名的已经在了就加「 (2)」这样的后缀)。"""
    safe = "".join("_" if char in '/\\:*?"<>|' or ord(char) < 32 else char for char in name).strip(" .")[:80] or "models"
    target = kept_models_dir() / safe
    number = 2
    while target.exists() or target.is_symlink():
        target = kept_models_dir() / f"{safe} ({number})"
        number += 1
    return target


def kept_models() -> list[Path]:
    """保留下来的那几份(按名字排)。"""
    try:
        return sorted(one for one in kept_models_dir().iterdir() if one.is_dir() and not one.name.startswith("."))
    except OSError:
        return []


def address(port: int) -> str:
    """本机服务的地址:写进连接的 `server_url`,插件、工作台、模型库读的都是它。听局域网时本机照样经回环连它。"""
    return f"http://127.0.0.1:{port}"


def free_port(db: Session) -> int:
    """从 FIRST_PORT 往上第一个空着的:没人在听,也没分给别的连接。"""
    taken = set(db.scalars(select(LocalService.port)))
    for port in range(FIRST_PORT, FIRST_PORT + PORT_SCAN):
        if port not in taken and not port_in_use(port):
            return port
    raise LocalServiceError("localServiceErr_noFreePort", start=FIRST_PORT)


def check_port(db: Session, instance_id: str, port: int) -> None:
    """改端口时:在范围里、没分给别的连接。有没有人正在听由起的那一刻再看(它可能只是暂时被占)。"""
    low, high = PORT_RANGE
    if not low <= port <= high:
        raise LocalServiceError("localServiceErr_badPort", status=422, low=low, high=high)
    holder = db.scalars(select(LocalService).where(LocalService.port == port, LocalService.instance_id != instance_id)).first()
    if holder is not None:
        other = db.get(PluginInstance, holder.instance_id)
        raise LocalServiceError("localServiceErr_portTaken", port=port, name=other.name if other else holder.instance_id)


def split_args(text: str) -> list[str]:
    """「高级」里填的附加参数 → 一项一个。空白分隔,双引号把带空格的一项括起来;**反斜杠原样留着**(Windows 路径
    `D:\\models` 不该被当成转义)。引号没配对就说清楚,不猜。"""
    args: list[str] = []
    current: list[str] = []
    quoted = False
    started = False
    for char in text:
        if char == '"':
            quoted, started = not quoted, True
            continue
        if char.isspace() and not quoted:
            if started:
                args.append("".join(current))
                current, started = [], False
            continue
        current.append(char)
        started = True
    if quoted:
        raise LocalServiceError("localServiceErr_badArgs", status=422, detail='"')
    if started:
        args.append("".join(current))
    if len(args) > MAX_ARGS or any(len(one) > MAX_ARG_CHARS for one in args):
        raise LocalServiceError("localServiceErr_badArgs", status=422, detail=f"≤ {MAX_ARGS} × {MAX_ARG_CHARS}")
    return args


def create(
    db: Session, instance: PluginInstance, *, directory: str, python: str, listen_lan: bool, keep_running: bool,
    extra_args: list[str],
) -> LocalService:
    """建这一行:选端口,把地址写进连接的 `server_url`。只 flush、不提交(和新建连接同一个事务时,哪一步不成都一起回滚);
    不通知宿主侧刷新目录 —— 它还没起,起来之后会自己通知。"""
    service = service_of(db, instance)
    row = LocalService(
        instance_id=instance.id, service=service.key, mode=DIRECTORY, directory=directory, python=python,
        port=free_port(db), listen_lan=listen_lan, keep_running=keep_running, extra_args=extra_args,
    )
    db.add(row)
    db.flush()
    inst.write_config(db, instance, {SERVICE_ADDRESS_FIELD: address(row.port)})
    return row


def make_managed(db: Session, instance: PluginInstance) -> LocalService:
    """改成(或建成)「让 Mosael 装」:目录是宿主分的安装目录,解释器留空(插件在安装目录里认 `.venv`),还没装好
    (`python_minor` 空)。已经是这一种的不动 —— 接着装、重建运行环境都是同一个目录。端口、局域网、保持运行、附加参数照旧。
    新建这一行时和 `create` 一样选端口、写地址,只 flush、不提交。"""
    root = str(install_root(instance.id))
    row = row_of(db, instance.id)
    if row is None:
        service = service_of(db, instance)
        row = LocalService(instance_id=instance.id, service=service.key, mode=MANAGED, directory=root, python="",
                           port=free_port(db), listen_lan=False, keep_running=False, extra_args=[], python_minor="")
        db.add(row)
        db.flush()
        inst.write_config(db, instance, {SERVICE_ADDRESS_FIELD: address(row.port)})
        return row
    if row.mode != MANAGED:
        row.mode, row.directory, row.python, row.python_minor = MANAGED, root, "", ""
        db.flush()
    return row


__all__ = [
    "DIRECTORY", "FIRST_PORT", "MANAGED", "MODES", "address", "check_port", "create", "free_port", "install_root",
    "kept_models", "kept_models_dir", "kept_models_target", "make_managed", "pip_cache_dir", "row_of", "service_of", "split_args",
]
