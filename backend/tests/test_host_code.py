"""代码执行分两条路:沙箱(`run_code`)和不隔离(`run_host_code`)。

不隔离那条存在的理由是有些事的全部意义就是动本机 —— 在沙箱里整理下载目录只会得到"找不到文件"。
这里钉住它的边界:只在本机桌面版、能真的动到本机文件、不把后端手里的凭据交给子进程,以及
**和沙箱是两档独立的放行**:对「算个数」放开,不连带放开「动我的文件」。
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.domain import host_code
from app.domain.agent import rules


@pytest.fixture
def desktop(monkeypatch):
    monkeypatch.setattr(settings, "local_desktop", True)


def test_远程部署上不跑_开卡前就说清(monkeypatch) -> None:
    from app.domain.agent.confirmable.registry import tool_spec
    from app.domain.agent.errors import ConfirmationError

    monkeypatch.setattr(settings, "local_desktop", False)
    assert "本机桌面版" in (host_code.available() or "")
    with pytest.raises(ConfirmationError):
        tool_spec("run_host_code").validate(None, "ws", {"code": "output = 1"})


def test_真的能动本机文件_print_单独交回(desktop, tmp_path) -> None:
    target = tmp_path / "note.txt"
    result = host_code.run(
        "from pathlib import Path\nprint('写入中')\nPath(inputs['path']).write_text('hi')\noutput = Path(inputs['path']).read_text()",
        {"path": str(target)},
    )
    assert result == {"output": "hi", "printed": "写入中\n"}
    assert target.read_text() == "hi"


def test_后端的凭据不交给子进程(desktop, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setenv("MOSAEL_WORKER_KEY", "k")
    monkeypatch.setenv("SOME_PLAIN_SETTING", "ok")
    result = host_code.run("import os\noutput = sorted(k for k in os.environ if k in inputs['keys'])",
                           {"keys": ["OPENAI_API_KEY", "MOSAEL_WORKER_KEY", "SOME_PLAIN_SETTING"]})
    assert result["output"] == ["SOME_PLAIN_SETTING"]


def test_出错时指出原因(desktop) -> None:
    with pytest.raises(host_code.HostCodeError, match="ZeroDivisionError"):
        host_code.run("output = 1 / 0", {})


def test_沙箱与不隔离是两档独立的放行() -> None:
    assert rules.default_rules()["run_host_code"] == "ask"
    loose_sandbox = {**rules.default_rules(), "run_code": "always"}
    assert rules.evaluate("run_code", {}, loose_sandbox).allowed
    assert rules.evaluate("run_host_code", {}, loose_sandbox).denied
    assert rules.evaluate("run_host_code", {}, {**rules.default_rules(), "run_host_code": "always"}).allowed


def test_两个工具都是确认卡_外部档() -> None:
    import mcp_server
    from app.domain.agent.confirmable.registry import tool_spec

    assert {"run_code", "run_host_code"} <= set(mcp_server.CONFIRMATION_TOOLS)
    assert tool_spec("run_host_code").permission == "external"
