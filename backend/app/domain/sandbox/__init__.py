from __future__ import annotations

import functools
import json
import shutil
import subprocess
import os
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.i18n import LocalizedError, tr
from app.core.text import blame_line
from app.core.child_process import ProcessOutputLimitExceeded, run_bounded

"""Untrusted Python executes only in a container with no host mounts or network.

The former native macOS policy exposed files outside HOME and lacked enforceable memory
and process limits. Docker is now required on every platform; unavailable isolation fails closed.
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


class SandboxError(LocalizedError, RuntimeError):
    """代码本身出错、超时、或输出超限。带文案 key(`sandboxErr_*`),按读的人的语言翻。"""


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


# Only the trusted Docker CLI sees host connection configuration. None is forwarded to Python.
_MINIMAL_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
_DOCKER_ENV_KEYS = ("HOME", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_CERT_PATH",
                    "DOCKER_TLS_VERIFY", "DOCKER_API_VERSION", "XDG_RUNTIME_DIR", "SSH_AUTH_SOCK", "SystemRoot")


def _docker_env() -> dict[str, str]:
    return {**_MINIMAL_ENV, **{key: os.environ[key] for key in _DOCKER_ENV_KEYS if key in os.environ}}


def _spawn(argv: list[str], payload: bytes, timeout: float) -> Attempt:
    try:
        completed = run_bounded(argv, input=payload, timeout=timeout, max_output_bytes=OUTPUT_CAP,
                                env=_docker_env(), what="沙箱执行")
    except subprocess.TimeoutExpired as exc:
        raise SandboxError("sandboxErr_timeout", seconds=f"{timeout:g}") from exc
    except ProcessOutputLimitExceeded as exc:
        raise SandboxError("sandboxErr_outputTooLarge", kib=OUTPUT_CAP // 1024) from exc
    return Attempt(completed.returncode, completed.stdout, completed.stderr)


class _DockerSandbox:
    """独立容器:`--network=none`、只读根、非 root、内存与进程数上限。

    这是 Linux 部署上唯一的一条路(原生 seccomp 后端还没做),也是任何平台上最强的一条。
    镜像用官方 `python:3.14-alpine` —— 不自己烤镜像是因为「沙箱里有什么库」应该是一个能看懂、
    能复现的事实,而不是藏在一个本仓库特有的 Dockerfile 里。
    """

    name = "docker"
    image = "python:3.14-alpine"

    def available(self) -> bool:
        self.executable = shutil.which("docker")
        if not self.executable:
            return False
        try:
            probe = _spawn([self.executable, "info", "--format", "{{.OSType}} {{.MemoryLimit}} {{.SwapLimit}} {{.PidsLimit}}"], b"", 5)
        except (OSError, SandboxError):
            return False
        return probe.returncode == 0 and probe.stdout.strip() == b"linux true true true"

    def run(self, payload: bytes, timeout: float) -> Attempt:
        docker = getattr(self, "executable", None) or shutil.which("docker")
        if not docker:
            raise SandboxUnavailable("sandboxErr_dockerMissing")
        name = "mosael-sandbox-" + uuid.uuid4().hex
        try:
            created = _spawn([
                docker, "create", "--name", name, "--interactive", "--pull=never",
                "--network=none", "--read-only", "--log-driver", "none", "--workdir", "/tmp",
                "--tmpfs", "/tmp:size=64m,mode=1777,noexec,nosuid,nodev",
                "--user", "65534:65534", "--memory", f"{MEMORY_MB}m",
                "--memory-swap", f"{MEMORY_MB}m", "--pids-limit", "64", "--cpus", "1",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--env", "PYTHONDONTWRITEBYTECODE=1",
                # Docker implicitly injects proxies from the host CLI config, including credentials.
                *[arg for key in ("HTTP_PROXY", "HTTPS_PROXY", "FTP_PROXY", "ALL_PROXY", "NO_PROXY")
                  for spelling in (key, key.lower()) for arg in ("--env", f"{spelling}=")],
                self.image, "python", "-I", "-c", _WRAPPER,
            ], b"", 10)
            if created.returncode != 0:
                detail = blame_line(created.stderr.decode(errors="replace"), fallback="") or tr("sandboxErr_containerCreateFailed")
                raise SandboxUnavailable("sandboxErr_notReady", detail=detail, image=self.image)
            return _spawn([docker, "start", "--attach", "--interactive", name], payload, timeout)
        finally:
            # The Docker client is only transport; terminating it does not stop the workload.
            # Removing the named container kills every descendant, including detached sessions.
            try:
                cleaned = _spawn([docker, "rm", "--force", name], b"", 10)
                if cleaned.returncode and b"No such container" not in cleaned.stderr:
                    raise SandboxError("sandboxErr_cleanupFailed")
            except (OSError, SandboxError) as exc:
                raise SandboxError("sandboxErr_cleanupFailedDetail", detail=str(exc)) from exc


#: 按优先级试。测试里会替换它来验证「没有后端就不跑」。
_BACKENDS: tuple[Backend, ...] = (_DockerSandbox(),)


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
        raise SandboxUnavailable("sandboxErr_unavailable")
    attempt = backend.run(json.dumps({"code": code, "inputs": inputs}).encode(), timeout)
    if len(attempt.stdout) + len(attempt.stderr) > OUTPUT_CAP:
        raise SandboxError("sandboxErr_outputTooLarge", kib=OUTPUT_CAP // 1024)
    if attempt.returncode != 0:
        # 挑出说明原因的那一行,而不是恰好排在最后的那一行 —— 用户跑的代码里打个进度条、
        # 或者 traceback 后面还有输出,取尾巴就报了个和错误无关的东西(见 core/text.blame_line)。
        why = blame_line(attempt.stderr.decode(errors="replace"), fallback="") or tr("sandboxErr_noReason")
        raise SandboxError("sandboxErr_codeFailed", why=why)
    try:
        return {"output": json.loads(attempt.stdout.decode())["output"]}
    except (ValueError, KeyError) as exc:
        raise SandboxError("sandboxErr_outputUnparsable") from exc
