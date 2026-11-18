"""本机命令是结构化 argv,不是 shell;白名单、超时和输出上限都要有。"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.domain import host_command


def test_allowlisted_command_runs_without_shell(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "local_desktop", True)
    result = host_command.run("python3", ["-c", "print('ok')"], cwd=tmp_path)
    assert result["exit_code"] == 0
    assert result["stdout"].strip() == "ok"
    assert result["cwd"] == str(tmp_path)


def test_shell_strings_are_arguments_not_executed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "local_desktop", True)
    result = host_command.run("python3", ["-c", "print('a;b')"], cwd=tmp_path)
    assert result["stdout"].strip() == "a;b"


def test_disallowed_command_and_unbounded_args_are_rejected(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "local_desktop", True)
    with pytest.raises(host_command.HostCommandError) as refused:
        host_command.run("rm", ["-rf", str(tmp_path)], cwd=tmp_path)
    assert refused.value.key == "hostCmdErr_notAllowed"
    with pytest.raises(host_command.HostCommandError) as timeout:
        host_command.run("python3", ["-c", "print(1)"], cwd=tmp_path, timeout=0)
    assert timeout.value.key == "hostCmdErr_timeoutRange"
