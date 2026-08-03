"""服务端执行代码是**隔离问题**,不是授权问题。

跑出来的现状(第 5 步动手前,`run_python` 的实际能力):

    读应用数据库   允许   53514c69746520666f726d6174203300   ← 整个库,含所有人的密钥
    写文件到主目录  允许   ~/.open-studio/PWNED
    起子进程      允许   uid=501(kinda) ...
    连本机服务     允许   连上了                              ← 后端自己就在 127.0.0.1
    读环境变量     允许   ['LC_CTYPE', 'PATH', ...]

于是"谁有资格写 code 节点"成了唯一的防线 —— 而那道防线是自助的(注册一个号,建自己的工作区,
在里面就是 owner)。两个问题叠在一起才有了 ADR 0008 §2.1 那条链。

正确的问题不是「谁能写代码」,是**任何人写的代码跑起来能不能伤到别人**。这一组用例锁住的就是
后者:代码跑得起来,但读不到别人的东西、连不上后端、写不出自己的临时目录。

**没有可用的隔离后端时拒绝执行**(fail closed)。这一条比上面几条都重要:它意味着"能不能跑代码"
由**是否真的隔离得住**决定,而不是由一个开关决定 —— 开关只是止血,不是设计。
"""

from __future__ import annotations

import pytest

from app.domain import sandbox


def _run(code: str) -> object:
    return sandbox.run_code(code, {})["output"]


def _skip_without_backend() -> None:
    if sandbox.active_backend() is None:
        pytest.skip("这台机器上没有可用的隔离后端(见 domain/sandbox)")


# ---------------- 隔离得住什么 ----------------


def test_it_still_runs_ordinary_code() -> None:
    """先确认没把它锁死 —— 隔离到「什么都跑不了」不叫隔离。"""
    _skip_without_backend()
    assert _run("output = sum(range(10))") == 45
    assert _run("import json, math\noutput = json.dumps({'x': math.floor(2.7)})") == '{"x": 2}'


def test_it_cannot_read_the_application_database() -> None:
    """库里有所有人的密钥、会话、发布账号 —— 这是"伤到别人"最直接的一条路。"""
    _skip_without_backend()
    code = (
        "import os\n"
        "p = os.path.expanduser('~/.open-studio/open-studio.db')\n"
        "try:\n"
        "    output = open(p, 'rb').read(16).hex()\n"
        "except OSError as exc:\n"
        "    output = f'blocked:{type(exc).__name__}'\n"
    )
    got = _run(code)
    assert str(got).startswith("blocked:"), f"读到了应用数据库:{got}"


def test_it_cannot_read_the_home_directory() -> None:
    _skip_without_backend()
    code = (
        "import os\n"
        "try:\n"
        "    output = os.listdir(os.path.expanduser('~'))[:3]\n"
        "except OSError as exc:\n"
        "    output = f'blocked:{type(exc).__name__}'\n"
    )
    assert str(_run(code)).startswith("blocked:")


def test_it_cannot_write_outside_its_own_scratch_space() -> None:
    _skip_without_backend()
    code = (
        "import os\n"
        "try:\n"
        "    open(os.path.expanduser('~/OPEN_STUDIO_SANDBOX_ESCAPE'), 'w').write('x')\n"
        "    output = 'wrote'\n"
        "except OSError as exc:\n"
        "    output = f'blocked:{type(exc).__name__}'\n"
    )
    assert str(_run(code)).startswith("blocked:")


def test_it_cannot_read_the_backends_environment() -> None:
    """后端进程的环境里有各家模型的密钥、库路径、内部服务地址。

    文件与网络已经挡住了,但环境变量是**另一条独立的路** —— 它不经过任何文件系统调用,所以
    再严的文件策略也拦不住它。
    """
    _skip_without_backend()
    code = "import os\noutput = sorted(os.environ)"
    names = _run(code)
    # __CF_USER_TEXT_ENCODING 是 macOS 自己往子进程里塞的(区域设置),不是后端的东西。
    allowed = {"PATH", "LANG", "PYTHONDONTWRITEBYTECODE", "PWD", "HOME", "HOSTNAME", "__CF_USER_TEXT_ENCODING"}
    assert set(names) <= allowed, f"后端的环境漏进了沙箱:{sorted(set(names) - allowed)}"


def test_it_has_no_network() -> None:
    """后端自己就在 127.0.0.1 —— 有网就等于代码能拿着自己的会话去打内部接口。"""
    _skip_without_backend()
    code = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 80), timeout=2)\n"
        "    output = 'connected'\n"
        "except OSError as exc:\n"
        "    output = f'blocked:{type(exc).__name__}'\n"
    )
    assert str(_run(code)).startswith("blocked:")


def test_a_child_process_is_confined_too() -> None:
    """起子进程本身不是逃逸 —— 只要子进程也在同一层隔离里。这一条锁住的正是"也在"。"""
    _skip_without_backend()
    code = (
        "import subprocess, sys, os\n"
        "r = subprocess.run([sys.executable, '-c', "
        "\"import os;print(os.listdir(os.path.expanduser('~'))[:1])\"], capture_output=True)\n"
        "output = 'blocked' if r.returncode else 'escaped:' + r.stdout.decode()[:40]\n"
    )
    assert str(_run(code)) == "blocked", "子进程逃出了隔离"


# ---------------- 资源上限 ----------------


def test_it_times_out_instead_of_running_forever() -> None:
    _skip_without_backend()
    with pytest.raises(sandbox.SandboxError) as caught:
        sandbox.run_code("while True: pass", {}, timeout=2.0)
    assert "超时" in str(caught.value)


def test_output_is_capped() -> None:
    _skip_without_backend()
    with pytest.raises(sandbox.SandboxError):
        sandbox.run_code("output = 'x' * (50 * 1024 * 1024)", {})


# ---------------- 没有隔离就不跑 ----------------


def test_without_an_isolating_backend_it_refuses(monkeypatch) -> None:
    """**fail closed**。「能不能跑代码」由是否真的隔离得住决定,而不是由一个开关决定。

    这一条替换掉第 0 步那个 `server_side_code_execution` 开关 —— 那是止血,不是设计。
    """
    monkeypatch.setattr(sandbox, "_BACKENDS", ())
    sandbox.active_backend.cache_clear()
    try:
        with pytest.raises(sandbox.SandboxUnavailable):
            sandbox.run_code("output = 1", {})
    finally:
        sandbox.active_backend.cache_clear()


def test_the_error_says_what_to_do_about_it(monkeypatch) -> None:
    """「跑不了」得能看懂:没有隔离后端时告诉部署方装什么,而不是一句 500。"""
    monkeypatch.setattr(sandbox, "_BACKENDS", ())
    sandbox.active_backend.cache_clear()
    try:
        with pytest.raises(sandbox.SandboxUnavailable) as caught:
            sandbox.run_code("output = 1", {})
        assert "Docker" in str(caught.value)
    finally:
        sandbox.active_backend.cache_clear()


# ---------------- 输入输出仍然照旧 ----------------


def test_inputs_reach_the_code_and_output_comes_back() -> None:
    _skip_without_backend()
    assert sandbox.run_code("output = inputs['a'] + inputs['b']", {"a": 2, "b": 3})["output"] == 5


def test_a_syntax_error_is_reported_not_swallowed() -> None:
    _skip_without_backend()
    with pytest.raises(sandbox.SandboxError) as caught:
        sandbox.run_code("def (:", {})
    assert "SyntaxError" in str(caught.value) or "语法" in str(caught.value)
