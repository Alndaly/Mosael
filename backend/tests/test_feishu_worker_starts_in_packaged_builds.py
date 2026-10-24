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
    """冻结版里 `sys.executable` 是应用自己 —— 用它跑**自己的管理命令**,不是拿它当解释器。"""
    monkeypatch.setattr(interpreter, "is_frozen", lambda: True)
    monkeypatch.setattr(interpreter.sys, "executable", "/Applications/Mosael.app/mosael-backend")
    assert connections.worker_command("bot-1") == ["/Applications/Mosael.app/mosael-backend", "feishu-worker", "bot-1"]


def test_管理命令认得_feishu_worker() -> None:
    from app import cli

    assert "feishu-worker" in cli.COMMANDS


def test_凭据解不开时不拉进程_而是说清该重填(monkeypatch) -> None:
    """`EncryptedText` 解不出来给的是空串;子进程只看到"没有凭据"→ exit 2,
    设置页上就只剩「长连接进程退出(code 2)」,该做的动作一个字没说。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core import secrets_at_rest
    from app.db.models import Base, FeishuBot
    from app.domain.feishu import bots

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    written: list[tuple[str, str, str]] = []
    monkeypatch.setattr(connections, "SessionLocal", Session)
    monkeypatch.setattr(bots, "write_status", lambda bot_id, status, detail="": written.append((bot_id, status, detail)))

    with Session() as db:
        db.add(
            FeishuBot(id="bot-1", workspace_id="ws-1", name="助手", app_id="cli_x", app_secret="s3cret")
        )
        db.commit()

    #: 模拟"主密钥换了":盘上有密文(`EncryptedText` 写进去就加密),但解不开 → 读出来是空串。
    monkeypatch.setattr(secrets_at_rest, "decrypt", lambda _value: None)

    def _fail(*_args, **_kwargs):
        raise AssertionError("凭据不可用时不该起子进程")

    monkeypatch.setattr(connections, "popen_text", _fail)
    monkeypatch.setattr(connections.interpreter, "is_frozen", lambda: False)

    connections.start_connection("bot-1")

    assert written and written[0][1] == "error"
    assert "App Secret" in written[0][2] or "App Secret" in str(written[0][2])
