"""每个机器人一个长连接子进程(`python -m app.integrations.feishu.worker <bot_id>`)的起停,以及它转发来的事件。

独立进程是 lark_oapi SDK 的硬约束:它的 ws 客户端共享模块级事件循环,同一进程跑多条连接会互相污染。
但子进程**只转发**(协议见 worker.py):消息、卡片点击、连接状态都经管道回到这里,在主进程里处理 ——
和桌面端同一条 turn 管线、同一个数据库连接池,子进程既不开库也不拿主密钥。连接凭据(app_id/app_secret)
由这里解密后经 stdin 交给它,不进命令行、不进环境变量。
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core import interpreter
from app.core.child_process import popen_text
from app.core.db import SessionLocal
from app.db.models import FeishuBot
from app.domain.feishu import bots
from app.integrations.feishu import approvals, inbound
from app.integrations.feishu.worker import PROTOCOL

logger = logging.getLogger(__name__)


class Connection:
    """一个机器人的 worker 进程、读它 stdout 的那条泵线程,和往它 stdin 写答复的那把锁。"""

    def __init__(self, bot_id: str, process: subprocess.Popen) -> None:
        self.bot_id = bot_id
        self.process = process
        self.pump: threading.Thread | None = None
        self._write_lock = threading.Lock()
        #: worker 最后报上来的**出错原因**。它自己退出时,泵还要写一句「进程退出」——
        #: 那句话不该把真正的原因盖掉(此前正是这样:凭据被拒的原因被一句 code 1 顶掉)。
        self.last_error_detail = ""

    def send(self, payload: dict[str, Any]) -> None:
        stdin = self.process.stdin
        if stdin is None:
            return
        with self._write_lock:
            try:
                stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                logger.warning("feishu worker stdin closed bot=%s", self.bot_id)


_processes: dict[str, Connection] = {}
#: 还活着的泵线程。子进程自己退出时,它的连接先从 `_processes` 里摘掉,泵还要写最后一次状态 ——
#: 停机时要等的是**所有**还在跑的泵,不只是表里那几条。
_pumps: set[threading.Thread] = set()
_process_lock = threading.Lock()
#: 停一条连接时等它的泵读完剩下的输出、写完状态。子进程已被终止,管道很快见底,正常远到不了这么久。
_PUMP_JOIN_SECONDS = 5


def _is_current(connection: Connection) -> bool:
    """这条连接还是这个机器人**现在**的那条吗(而不是被停掉 / 被换掉的上一辈子那条)。"""
    with _process_lock:
        return _processes.get(connection.bot_id) is connection


def dispatch(connection: Connection, event: dict[str, Any]) -> None:
    """worker 转来的一条事件。慢活(一轮对话、一次批准)都丢给线程,读管道的循环不能停。"""
    kind = event.get("event")
    if kind == "message":
        threading.Thread(
            target=inbound.handle_incoming,
            args=(connection.bot_id, str(event.get("chat_id") or ""), str(event.get("message_id") or "")),
            kwargs={
                "sender_open_id": str(event.get("open_id") or ""),
                "message_type": str(event.get("message_type") or ""),
                "content_json": str(event.get("content") or ""),
            },
            daemon=True,
            name="feishu-inbound",
        ).start()
    elif kind == "card":

        def decide() -> None:
            try:
                value = event.get("value")
                #: 点击者的 open_id 是**收到这次回调的那台机器人(那个飞书应用)**眼里的 id ——
                #: 绑定按 (工作区, 机器人, open_id) 记,所以这一维必须传下去(见 approvals.handle_card_action)。
                result = approvals.handle_card_action(
                    str(event.get("open_id") or ""),
                    value if isinstance(value, dict) else {},
                    connection.bot_id,
                )
            except Exception:  # noqa: BLE001 —— 回一句总比让飞书那头超时强
                logger.exception("feishu card decision crashed bot=%s", connection.bot_id)
                result = {"toast": {"type": "error", "content": "处理失败,请到 Mosael 里查看"}}
            connection.send({"id": event.get("id"), "result": dict(result)})

        threading.Thread(target=decide, daemon=True, name="feishu-card").start()
    elif kind == "status":
        status = str(event.get("status") or "").strip()
        detail = str(event.get("detail") or "").strip()
        #: 只有**现在**那条连接有资格替这个机器人说它是什么状态:被停掉的那条晚一步报上来的
        #: 「在线」是上一辈子的事。此前挡这件事的是"只有当前是 connecting 才落 online" ——
        #: 那条规矩反过来会让真的「在线」写不进去(残留的 error 会把它吃掉)。
        if not status or not _is_current(connection):
            return
        if status == "error":
            connection.last_error_detail = detail
        bots.write_status(connection.bot_id, status, detail)


def _pump(connection: Connection) -> None:
    """读 worker 的 stdout 直到它退出。协议行分发,其余当日志。"""
    try:
        _drain(connection)
    finally:
        with _process_lock:
            _pumps.discard(threading.current_thread())


def _drain(connection: Connection) -> None:
    stdout = connection.process.stdout
    if stdout is None:
        return
    for line in stdout:
        if not line.startswith(PROTOCOL):
            if line.strip():
                logger.info("feishu[%s] %s", connection.bot_id, line.rstrip())
            continue
        try:
            dispatch(connection, json.loads(line[len(PROTOCOL):]))
        except Exception:  # noqa: BLE001 —— 一条坏事件不该掐断整条连接
            logger.exception("feishu event dispatch failed bot=%s", connection.bot_id)
    code = connection.process.wait()
    with _process_lock:
        still_current = _processes.get(connection.bot_id) is connection
        if still_current:
            del _processes[connection.bot_id]
    # 被 stop_connection 停掉的不算出错;自己退出的要让设置页看得见 —— **连同 worker 最后说的原因**:
    # 只写一句"进程退出"会把它真正为什么死掉这件事盖掉(凭据被拒 / 连不上)。
    if still_current:
        reason = connection.last_error_detail
        detail = f"长连接进程退出(code {code})" + (f":{reason}" if reason else "")
        bots.write_status(connection.bot_id, "error", detail)


def start_connection(bot_id: str) -> None:
    backend_dir = Path(__file__).resolve().parents[3]
    python = backend_dir / ".venv" / "bin" / "python"
    with SessionLocal() as db:
        bot = db.get(FeishuBot, bot_id)
        if bot is None:
            raise LookupError(bot_id)
        credentials = {"app_id": bot.app_id, "app_secret": bot.app_secret}
    with _process_lock:
        existing = _processes.get(bot_id)
        if existing is not None and existing.process.poll() is None:
            return
        bots.write_status(bot_id, "connecting")
        process = popen_text(
            [str(python) if python.exists() else interpreter.base_python(), "-m", "app.integrations.feishu.worker", bot_id],
            cwd=backend_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        connection = Connection(bot_id, process)
        connection.send(credentials)
        _processes[bot_id] = connection
        connection.pump = threading.Thread(target=_pump, args=(connection,), daemon=True, name=f"feishu-{bot_id[:8]}")
        _pumps.add(connection.pump)
    connection.pump.start()


def stop_connection(bot_id: str) -> None:
    """停掉这条连接,**等它的泵退出**再写「离线」。不等的话泵还在后台读剩下的输出、写状态 —— 停机时它会
    在库关掉之后才写(测试里是写进下一条用例清过的库:CI 上的「no such table: feishu_bots」)。"""
    with _process_lock:
        connection = _processes.pop(bot_id, None)
    if connection is not None:
        if connection.process.poll() is None:
            connection.process.terminate()
            try:
                connection.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                connection.process.kill()
        if connection.pump is not None and connection.pump is not threading.current_thread():
            connection.pump.join(_PUMP_JOIN_SECONDS)
    bots.write_status(bot_id, "offline")


def _start_failure_detail(exc: BaseException) -> str:
    """起不来时说给用户听的那一句:**带上异常原文**。

    只 `logger.exception` 的话,设置页上永远是「连接中」而没有人知道为什么 —— 凭据错、没有
    libffi、工作区被删,在那一页上都长得一模一样。
    """
    return f"启动长连接失败:{exc}"


def autostart_enabled_bots() -> None:
    """后端起来时:**先把残留的连接状态归零**,再启用在用的那几条。

    上一次进程被杀(或被换掉)会在库里留下 `connecting` / `online` —— 而那一刻并没有连接在跑,
    这正是"设置页说在线、后端根本没起来"的来源。归零之后每一条都由真实过程重新写:启起来的
    写 connecting、真连上才写 online(见 worker.watch_connection)、起不来写 error。

    归零覆盖**所有**机器人,不只启用的那些:没有连接在跑这件事与它启不启用无关。
    """
    with SessionLocal() as db:
        rows = db.scalars(select(FeishuBot)).all()
        enabled_ids: list[str] = []
        for bot in rows:
            bot.status = "offline"
            bot.status_detail = ""
            if bot.enabled:
                enabled_ids.append(bot.id)
        db.commit()
    for bot_id in enabled_ids:
        try:
            start_connection(bot_id)
        except Exception as exc:  # noqa: BLE001 —— 起不来也要留下原因,不只是日志
            logger.exception("feishu autostart failed bot=%s", bot_id)
            bots.write_status(bot_id, "error", _start_failure_detail(exc))


def stop_all_connections() -> None:
    """停掉所有连接,并等所有还在跑的泵收尾 —— 包括子进程自己先退出、已经不在表里、还在写最后一次状态的那几条。"""
    with _process_lock:
        ids = list(_processes)
    for bot_id in ids:
        stop_connection(bot_id)
    with _process_lock:
        leftovers = [pump for pump in _pumps if pump is not threading.current_thread()]
    for pump in leftovers:
        pump.join(_PUMP_JOIN_SECONDS)


def start_or_report(bot_id: str) -> None:
    """起连接;起不来就把原因写进机器人状态,而不是让建机器人的那个请求失败 —— 机器人已经存好了。"""
    try:
        start_connection(bot_id)
    except Exception as exc:  # noqa: BLE001 —— 见上
        logger.exception("feishu connection failed to start bot=%s", bot_id)
        bots.write_status(bot_id, "error", _start_failure_detail(exc))


def restart_connection(bot_id: str) -> None:
    stop_connection(bot_id)
    start_connection(bot_id)
