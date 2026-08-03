from __future__ import annotations

import functools
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

"""跑别人写的代码。

**这是隔离问题,不是授权问题。**「谁有资格写 code 节点」是个错问题 —— 正确的问题是:任何人写的
代码跑起来,能不能伤到别人。此前的执行器只是"子进程 + 超时",跑出来的结果是:

    读应用数据库   允许   ← 整个库,含所有人的密钥
    写文件到主目录  允许
    连本机服务     允许   ← 后端自己就在 127.0.0.1
    起子进程      允许

于是只好用角色去挡,而那道角色闸恰好是自助的(注册→建自己的工作区→在里面是 owner)。

现在换成:**跑得起来,但读不到别人的东西、连不上后端、写不出自己的临时目录**。做不到这一点的
机器上,`run_code` **拒绝执行**(fail closed)—— 「能不能跑代码」由是否真的隔离得住决定,而不是
由一个开关决定。开关是止血,不是设计。

后端按平台选(见 `_BACKENDS`),每个后端自己回答「我在这台机器上能用吗」:

    darwin   sandbox-exec:内核强制,且**子进程继承**
    docker   独立容器、--network=none、只读根、非 root、内存与进程数上限

Linux 主机上目前只有 docker 一条路。原生 seccomp 后端(dify-sandbox 那种系统调用白名单)是下一步;
在它到位之前,没装 docker 的 Linux 主机会如实拒绝,而不是退回到"没有隔离但照跑"。
"""

#: 用户代码在沙箱里的样子。inputs 从 stdin 进,output 从 stdout 出 —— 沙箱里没有别的通路。
_WRAPPER = """\
import json, sys
payload = json.load(sys.stdin)
scope = {"inputs": payload.get("inputs") or {}}
exec(payload["code"], scope)
sys.stdout.write(json.dumps({"output": scope.get("output")}, ensure_ascii=False, default=str))
"""

TIMEOUT_SECONDS = 15.0
OUTPUT_CAP = 256 * 1024
MEMORY_MB = 256


class SandboxError(RuntimeError):
    """代码本身出错、超时、或输出超限。"""


class SandboxUnavailable(SandboxError):
    """这台机器上没有能真正隔离的后端 —— 于是不跑。"""


@dataclass(frozen=True)
class Attempt:
    returncode: int
    stdout: bytes
    stderr: bytes


class Backend(Protocol):
    name: str

    def available(self) -> bool: ...

    def run(self, payload: bytes, timeout: float) -> Attempt: ...


#: 沙箱里的环境。**不继承**后端进程的 —— 那里面有各家模型的密钥、数据库路径、内部服务地址。
#: 文件与网络已经挡住了,但环境变量是另一条独立的路:它不经过任何文件系统调用。
_MINIMAL_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}


def _spawn(argv: list[str], payload: bytes, timeout: float) -> Attempt:
    """共用的进程外壳:喂 stdin、限时、截断输出、给一份最小环境。

    输出**在这里截断**而不是让沙箱自己管:一个能写出 500MB 的程序不该先把这个进程撑爆再被发现。
    """
    try:
        completed = subprocess.run(
            argv, input=payload, capture_output=True, timeout=timeout, env=dict(_MINIMAL_ENV)
        )
    except subprocess.TimeoutExpired as exc:
        raise SandboxError(f"代码执行超时({timeout:g}s)") from exc
    return Attempt(completed.returncode, completed.stdout[: OUTPUT_CAP + 1], completed.stderr)


class _DarwinSandbox:
    """macOS `sandbox-exec`:内核强制的沙箱策略,而且**子进程继承** —— 起子进程不是逃逸。

    策略写成「allow default + 逐项 deny」而不是 dify-sandbox 那种系统调用白名单:macOS 上
    `deny default` 的 profile 连 CPython 都起不来(实测 SIGABRT),而要让它起来就得把一份
    自己都说不清的允许清单抄进来 —— 那种清单看着更严格,实际是猜的。这里 deny 的是真正要挡的
    三样:**别人的文件、写盘、网络**,每一条都跑过(见 tests/test_sandbox.py)。
    """

    name = "darwin"

    #: `{scratch}` 由 run() 填成本次执行的临时目录。
    _PROFILE = """(version 1)
(allow default)
(deny network*)
(deny file-write*)
(allow file-write* (subpath "{scratch}") (literal "/dev/null") (literal "/dev/stdout") (literal "/dev/stderr"))
(deny file-read* (subpath "{home}"))
(allow file-read* (subpath "{scratch}"){interpreter})
"""

    def available(self) -> bool:
        import sys

        return sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").is_file()

    def run(self, payload: bytes, timeout: float) -> Attempt:
        import sys

        with tempfile.TemporaryDirectory(prefix="open-studio-sandbox-") as scratch:
            profile = Path(scratch) / "policy.sb"
            # 解释器自己往往就装在 home 底下(venv、pyenv、homebrew --user)。挡住整个 home
            # 会连它都读不到,所以**逐条放行解释器自己的目录** —— 放行的是 Python 安装,
            # 不是它上面那一层仓库。
            interpreter = "".join(
                f'\n    (subpath "{path}")'
                for path in sorted({str(Path(sys.prefix).resolve()), str(Path(sys.base_prefix).resolve())})
            )
            profile.write_text(
                self._PROFILE.format(
                    scratch=str(Path(scratch).resolve()),
                    home=str(Path.home().resolve()),
                    interpreter=interpreter,
                )
            )
            return _spawn(
                ["/usr/bin/sandbox-exec", "-f", str(profile), sys.executable, "-I", "-c", _WRAPPER],
                payload,
                timeout,
            )


class _DockerSandbox:
    """独立容器:`--network=none`、只读根、非 root、内存与进程数上限。

    这是 Linux 部署上唯一的一条路(原生 seccomp 后端还没做),也是任何平台上最强的一条。
    镜像用官方 `python:3-alpine` —— 不自己烤镜像是因为「沙箱里有什么库」应该是一个能看懂、
    能复现的事实,而不是藏在一个本仓库特有的 Dockerfile 里。
    """

    name = "docker"
    image = "python:3-alpine"

    def available(self) -> bool:
        docker = shutil.which("docker")
        if not docker:
            return False
        try:
            probe = subprocess.run([docker, "info"], capture_output=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return probe.returncode == 0

    def run(self, payload: bytes, timeout: float) -> Attempt:
        return _spawn(
            [
                "docker", "run", "--rm", "--interactive",
                "--network=none",          # 后端自己就在 127.0.0.1
                "--read-only",             # 根文件系统不可写
                "--tmpfs", "/tmp:size=64m",
                "--user", "65534:65534",   # nobody
                "--memory", f"{MEMORY_MB}m",
                "--pids-limit", "64",
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                self.image, "python", "-I", "-c", _WRAPPER,
            ],
            payload,
            timeout,
        )


#: 按优先级试。测试里会替换它来验证「没有后端就不跑」。
_BACKENDS: tuple[Backend, ...] = (_DarwinSandbox(), _DockerSandbox())


@functools.lru_cache(maxsize=1)
def active_backend() -> Backend | None:
    """这台机器上能用的隔离后端;一个都没有就是 None。

    结果缓存:`docker info` 要几百毫秒,而"装没装 docker"不会在一次进程生命周期里变。
    """
    for backend in _BACKENDS:
        if backend.available():
            return backend
    return None


def run_code(code: str, inputs: dict[str, Any], *, timeout: float = TIMEOUT_SECONDS) -> dict[str, Any]:
    """在隔离环境里跑一段用户代码,返回 `{"output": ...}`。

    没有可用的隔离后端 → `SandboxUnavailable`。**这是有意的**:没有隔离就不跑,而不是退回到
    "没有隔离但照跑"(那正是此前的状态,见模块开头)。
    """
    backend = active_backend()
    if backend is None:
        raise SandboxUnavailable(
            "这台机器上没有可用的代码隔离环境,因此不执行代码。"
            "请在部署机上安装并启动 Docker(服务端会用一个无网络、只读、非 root 的容器来跑)。"
        )
    attempt = backend.run(json.dumps({"code": code, "inputs": inputs}).encode(), timeout)
    if len(attempt.stdout) > OUTPUT_CAP:
        raise SandboxError(f"代码输出超过上限({OUTPUT_CAP // 1024} KiB)")
    if attempt.returncode != 0:
        raise SandboxError(f"代码执行出错: {attempt.stderr.decode(errors='replace')[-500:]}")
    try:
        return {"output": json.loads(attempt.stdout.decode())["output"]}
    except (ValueError, KeyError) as exc:
        raise SandboxError("代码输出无法解析(请把结果赋给 output 变量)") from exc
