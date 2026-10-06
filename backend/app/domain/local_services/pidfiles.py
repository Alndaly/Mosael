"""起进程时记一份 pid 文件,下次后端启动时据此**接回**还活着的那一个(ADR 0041 §2「没来得及停」)。

后端正常退出时会停掉它起的每一个本机服务(lifespan);被强杀、断电时来不及。那个进程自成一组,不跟着后端走,
还占着端口和显存。下次启动时三样都对得上才接回来:

1. 那个 pid 还在;
2. 它的命令行和记下的那一行一模一样(pid 会被系统复用,只看 pid 会把别人的进程当成自己的);
3. 健康检查通过(在、命令行也对,但不响应的,不算「运行中」)。

**对不上就不碰它**:不是我们能确定起过的东西,不杀。pid 文件删掉,这个连接照常是「已停止」;要是那个进程还占着
端口,用户点「启动」时会看到「端口被占」,而不是被我们悄悄杀掉一个不认识的进程。
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from app.core.child_process import command_line_of, process_alive, process_command_line
from app.core.config import settings

logger = logging.getLogger(__name__)


def pid_dir() -> Path:
    return settings.data_dir / "local-services" / "pids"


@dataclass(frozen=True)
class PidRecord:
    instance_id: str
    pid: int
    argv: list[str]
    port: int
    health_path: str
    #: 起的时刻(ISO 8601,UTC),给人看。
    started_at: str
    directory: str = ""
    cwd: str = ""


def path_for(instance_id: str) -> Path:
    return pid_dir() / f"{instance_id}.json"


def write(record: PidRecord) -> None:
    try:
        target = path_for(record.instance_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(".part")
        partial.write_text(json.dumps(asdict(record), ensure_ascii=False), encoding="utf-8")
        partial.replace(target)
    except OSError:
        logger.warning("本机服务 %s 的 pid 文件没写下", record.instance_id, exc_info=True)


def remove(instance_id: str) -> None:
    try:
        path_for(instance_id).unlink(missing_ok=True)
    except OSError:
        logger.debug("删本机服务 %s 的 pid 文件失败", instance_id, exc_info=True)


def read_all() -> list[PidRecord]:
    """数据目录里记着的每一份。读不懂的删掉(它说不出是谁起的,也就接不回来)。"""
    found: list[PidRecord] = []
    directory = pid_dir()
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            record = PidRecord(
                instance_id=str(raw["instance_id"]), pid=int(raw["pid"]), argv=[str(one) for one in raw["argv"]],
                port=int(raw["port"]), health_path=str(raw["health_path"]), started_at=str(raw.get("started_at") or ""),
                directory=str(raw.get("directory") or ""), cwd=str(raw.get("cwd") or ""),
            )
        except (OSError, ValueError, KeyError, TypeError):
            path.unlink(missing_ok=True)
            continue
        found.append(record)
    return found


def same_process(record: PidRecord) -> bool:
    """那个 pid 还在、命令行和记下的一模一样。健康检查由调用方做(它知道怎么问)。"""
    if not process_alive(record.pid):
        return False
    line = process_command_line(record.pid)
    return line is not None and _normalized(line) == _normalized(command_line_of(record.argv))


def _normalized(line: str) -> str:
    return " ".join(line.split())


__all__ = ["PidRecord", "path_for", "pid_dir", "read_all", "remove", "same_process", "write"]
