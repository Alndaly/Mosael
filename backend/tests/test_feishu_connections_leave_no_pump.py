"""停掉飞书长连接之后,不许留一条泵线程还在背后写库。

每个机器人一个 worker 子进程,主进程里一条泵线程读它的输出;子进程退出时泵要写最后一次状态。此前停连接只停子进程,
不等泵 —— 子进程自己先退出的那条更是早就不在连接表里,停机时谁也不等它。测试里它写进下一条用例刚清过的库,
CI 上报成「no such table: feishu_bots」,时红时绿;生产上是关机后还在写库。
"""

from __future__ import annotations

import sys
import threading
import time

from app.core.db import SessionLocal
from app.db.models import FeishuBot
from app.integrations.feishu import connections
from tests.util import fresh_client


def _pumps_alive() -> list[str]:
    return [one.name for one in threading.enumerate() if one.name.startswith("feishu-") and one.is_alive()]


def test_子进程自己退出_停机时也等它的泵写完最后一次状态(monkeypatch) -> None:
    #: 读完凭据就退出的替身 worker:不出网,退出码 3 —— 泵该把「进程退出」写成错误状态。
    quick_exit = [sys.executable, "-c", "import sys; sys.stdin.readline(); sys.exit(3)"]
    monkeypatch.setattr(connections, "popen_text", lambda _argv, **kwargs: connections.subprocess.Popen(
        quick_exit, text=True, **kwargs))
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    #: 写状态放慢一点:真机上它快得几乎看不见,但「停机时它还在写」这个窗口是真的,放大它才测得到。
    write_status = connections.bots.write_status
    writing_error = threading.Event()

    def slow_write(bot_id: str, status: str, detail: str = "") -> None:
        if status == "error":
            writing_error.set()
            time.sleep(0.5)
        write_status(bot_id, status, detail)

    monkeypatch.setattr(connections.bots, "write_status", slow_write)
    bot = client.post("/api/feishu/bots", json={"workspace_id": ws["id"], "app_id": "cli_q", "app_secret": "s"}).json()
    #: 等子进程**自己**退出(不是被停掉的):这时它可能已经不在连接表里,泵还在写最后一次状态。
    connections._processes[bot["id"]].process.wait(timeout=10)
    #: 等泵**已经在写**「出错」那一笔了再停机 —— 要测的正是「停机时它还在写」。此前子进程一退就停机:泵的线程起步晚一点、
    #: 还没读到 EOF,停机就把它当成「被停掉的」记了离线(线程起步推后 0–0.3 秒时实测 `'offline' == 'error'`)。
    assert writing_error.wait(30), "子进程退出了,泵一直没去写「出错」"

    connections.stop_all_connections()

    assert _pumps_alive() == [], "停机返回时泵还在跑 —— 它会在库关掉之后才写状态"
    with SessionLocal() as db:
        row = db.get(FeishuBot, bot["id"])
        assert row.status == "error" and "code 3" in row.status_detail, "子进程自己退出的原因要在返回前写好"


def test_停一条连接_等它的泵读完再写离线(monkeypatch) -> None:
    """钉的是「被停掉的不算出错,最后留下离线」。抓泄漏的是上一条 —— 这条单独在旧实现上也过:被终止的子进程
    输出立刻见底,泵退得比断言快。"""
    #: 一直挂着的替身 worker:停连接时才被终止。
    hang = [sys.executable, "-c", "import sys, time; sys.stdin.readline(); time.sleep(60)"]
    monkeypatch.setattr(connections, "popen_text", lambda _argv, **kwargs: connections.subprocess.Popen(
        hang, text=True, **kwargs))
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    bot = client.post("/api/feishu/bots", json={"workspace_id": ws["id"], "app_id": "cli_h", "app_secret": "s"}).json()
    assert _pumps_alive(), "连接起来了,泵应该在读"

    connections.stop_connection(bot["id"])

    assert _pumps_alive() == []
    with SessionLocal() as db:
        assert db.get(FeishuBot, bot["id"]).status == "offline", "被停掉的不算出错:最后留下的是「离线」"
