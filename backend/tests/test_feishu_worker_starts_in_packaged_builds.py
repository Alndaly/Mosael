"""打包版的长连接子进程怎么起。

真机事故(2026-10-23):设置页写着「长连接进程退出(code 2)」,后端日志里是

    python3: Error while finding module specification for 'app.integrations.feishu.worker'
    (ModuleNotFoundError: No module named 'app.integrations')

原因是打包版的后端是**冻结二进制**:`sys.executable` 是应用自己,`app` 这个包并不在磁盘上,
`python -m app…` 那句在那一版里根本不可能成立。修法是用**同一个二进制 + 管理命令**
(`mosael-backend feishu-worker <bot_id>`)。这条测试把两条路的命令钉住。
"""

from __future__ import annotations

from app.integrations.feishu import connections
from app.core import interpreter


def test_开发版走_python_m_模块(monkeypatch) -> None:
    monkeypatch.setattr(interpreter, "is_frozen", lambda: False)
    command = connections.worker_command("bot-1")
    #: 解释器是哪一份随环境变,命令的形状不该变。
    assert command[1:] == ["-m", "app.integrations.feishu.worker", "bot-1"]


def test_打包版用同一个二进制加管理命令(monkeypatch) -> None:
    monkeypatch.setattr(interpreter, "is_frozen", lambda: True)
    monkeypatch.setattr(connections.sys, "executable", "/Applications/Mosael.app/mosael-backend")
    assert connections.worker_command("bot-1") == ["/Applications/Mosael.app/mosael-backend", "feishu-worker", "bot-1"]


def test_管理命令认得_feishu_worker() -> None:
    from app import cli

    assert "feishu-worker" in cli.COMMANDS
