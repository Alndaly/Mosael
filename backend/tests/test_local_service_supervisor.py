"""本机服务的进程管理(ADR 0041 §2),拿一个几行的假服务(tests/fake_local_service.py)把每条路走一遍:

- 起来、就绪(慢启动也等得到)、日志进缓冲也落盘(进度条按终端的样子收、中文不乱)、pid 文件;
- 没在限时内就绪 → 停掉、停在「起不来」,摆出最后几行日志;还没就绪就退出 → 不重试;
- 运行中崩了 → 1 秒起翻倍退避重启,5 分钟内最多 3 次,第 4 次停在「起不来」;
- 停:先请整组退,不听的到点强杀整组(孙进程一起走);
- pid 文件核对:pid 在、命令行一样才算同一个,接回来以后崩了照样重启;
- 同一个目录只起一份;端口被占认得出。

这里不碰数据库、不起插件 —— 那一层在 test_local_services。
"""

from __future__ import annotations

import os
import shutil
import socket
import sys
import time
from pathlib import Path

import pytest

from app.core.child_process import process_alive
from app.domain.local_services import logs as service_logs
from app.domain.local_services import pidfiles, supervisor
from app.domain.local_services.logs import ServiceLog
from app.domain.local_services.supervisor import FAILED, RESTARTING, RUNNING, STARTING, STOPPED, LaunchSpec, ServiceProcess
from tests.util import free_port

FAKE = Path(__file__).resolve().parent / "fake_local_service.py"
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="按 pid 看孙进程还在不在用的是 os.kill(pid, 0)")


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch):
    """缩短各个等待,一条测试几秒跑完;每条之后把留下的进程全停掉。"""
    monkeypatch.setattr(supervisor, "HEALTH_POLL_SECONDS", 0.05)
    monkeypatch.setattr(supervisor, "WATCH_SECONDS", 0.05)
    monkeypatch.setattr(supervisor, "RESTART_BASE_DELAY", 0.1)
    monkeypatch.setattr(supervisor, "STOP_GRACE_SECONDS", 3.0)
    shutil.rmtree(pidfiles.pid_dir(), ignore_errors=True)
    yield
    for process in supervisor.everyone():
        process.stop(grace=1.0)
    supervisor._services.clear()
    supervisor._directories.clear()


def _spec(tmp_path: Path, *flags: str, ready_timeout: float = 20.0, port: int | None = None) -> LaunchSpec:
    port = port or free_port()
    return LaunchSpec(
        argv=[sys.executable, str(FAKE), "--port", str(port), *flags],
        env={**os.environ, "FAKE_ENV": "宿主给的"}, cwd=str(tmp_path), port=port, health_path="/system_stats",
        ready_timeout=ready_timeout, directory=str(tmp_path),
    )


def _service(tmp_path: Path, name: str = "svc") -> ServiceProcess:
    return supervisor.ensure(name, ServiceLog(tmp_path / f"service-{name}.log"))


def _wait_for(predicate, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _starts(count: Path) -> list[str]:
    return count.read_text(encoding="utf-8").splitlines() if count.exists() else []


def _supervision_over(service: ServiceProcess) -> None:
    """等看护线程结束:重起只能由它发起,它结束了就不会再有。数「起了几次」之前先等这个 ——
    此前是睡 0.5 秒再数,机器一忙,该有的那次重起还没来得及发生,「不重起」照样成立。"""
    thread = service._thread
    if thread is not None:
        thread.join(timeout=30)
        assert not thread.is_alive(), "看护线程 30 秒还没结束"


# ---- 起、就绪、日志、停 ----------------------------------------------------------


def test_起来以后健康检查通过才算运行中_日志进缓冲也落盘(tmp_path: Path) -> None:
    service = _service(tmp_path)
    spec = _spec(tmp_path, "--slow", "0.6")
    service.launch(spec, respawn=lambda: spec)
    assert service.state == STARTING, "健康检查过之前是「启动中」"
    assert service.wait_settled(20) == RUNNING
    assert supervisor.healthy(spec.health_url)
    assert service.ready_seconds is not None and service.ready_seconds >= 0.6, "慢启动也等得到,用了多久记下来"

    record = pidfiles.read_all()[0]
    assert (record.instance_id, record.pid, record.port) == ("svc", service.pid, spec.port)
    assert record.argv == spec.argv, "pid 文件记着命令行,下次启动据此核对"

    lines = service.log.tail(50)
    assert any("第 1 次启动" in line and "FAKE_ENV=宿主给的" in line for line in lines), lines
    assert "加载 100%" in lines and not any("加载 10%" in line for line in lines), "回车刷新的进度条只留最后那一下"
    assert "第 1 次启动" in (tmp_path / "service-svc.log").read_text(encoding="utf-8"), "也落盘"

    pid = service.pid
    service.stop()
    assert service.state == STOPPED and service.pid is None
    assert not process_alive(pid)
    assert pidfiles.read_all() == [], "停了就删 pid 文件"


def test_没在限时内就绪_停掉并停在起不来_摆出最后几行日志(tmp_path: Path) -> None:
    service = _service(tmp_path)
    spec = _spec(tmp_path, "--hang", ready_timeout=1.0)
    service.launch(spec, respawn=lambda: spec)
    pid = service.pid
    assert service.wait_settled(15) == FAILED
    assert service.error is not None and service.error.key == "localServiceErr_readyTimeout"
    assert any("第 1 次启动" in line for line in service.failure_lines), service.failure_lines
    assert _wait_for(lambda: not process_alive(pid), 5), "超时的那个进程被停掉了,不留着占端口"
    assert pidfiles.read_all() == []


def test_还没就绪就退出_不重试(tmp_path: Path) -> None:
    count = tmp_path / "count"
    service = _service(tmp_path)
    spec = _spec(tmp_path, "--exit-at-start", "3", "--count", str(count))
    service.launch(spec, respawn=lambda: spec)
    assert service.wait_settled(15) == FAILED
    assert service.error is not None and service.error.key == "localServiceErr_exitedDuringStart"
    assert service.error.params["code"] == "3"
    assert any("缺了一个依赖" in line for line in service.failure_lines)
    _supervision_over(service)
    assert len(_starts(count)) == 1, "第一次就没起来的(参数不对、缺依赖)每次都一样,不重试"


# ---- 崩溃退避 ------------------------------------------------------------------


def test_运行中崩了_退避之后重起_起来又是运行中(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(supervisor, "RESTART_BASE_DELAY", 0.8)
    count = tmp_path / "count"
    service = _service(tmp_path)
    spec = _spec(tmp_path, "--crash-first", "1", "--count", str(count))
    asked = []

    def respawn() -> LaunchSpec:
        asked.append(1)
        return spec

    service.launch(spec, respawn=respawn)
    assert service.wait_settled(15) == RUNNING
    assert _wait_for(lambda: service.state == RESTARTING), "崩了以后、重起好之前是「重启中」,不是「起不来」也不是「已停止」"
    assert _wait_for(lambda: len(_starts(count)) == 2 and service.state == RUNNING), service.state
    assert service.restarts() == 1
    assert asked == [1], "重起之前问调用方要一份新的起法(配置可能改过)"
    assert service.error is None


def test_崩得太勤_五分钟内第四次停在起不来_退避一次比一次长(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    count = tmp_path / "count"
    service = _service(tmp_path)
    spec = _spec(tmp_path, "--crash-after", "0.2", "--count", str(count))
    #: 记下看护线程**真拿去等的**那几段退避,不量两次重起之间隔了多久:那段时间里还有起进程、跑到崩,机器一忙
    #: 某一次起得慢,「后一段比前一段长」就不成立了(几套测试同时跑时实测 0.63 / 1.81 / 2.65)。
    delays: list[float | None] = []
    next_delay = supervisor.RestartPolicy.next_delay

    def recording(self, now: float) -> float | None:
        delays.append(next_delay(self, now))
        return delays[-1]

    monkeypatch.setattr(supervisor.RestartPolicy, "next_delay", recording)

    service.launch(spec, respawn=lambda: spec)
    assert _wait_for(lambda: service.state == FAILED, 60), service.state
    assert service.error is not None and service.error.key == "localServiceErr_crashedTooOften"
    assert len(_starts(count)) == 1 + supervisor.MAX_RESTARTS, "第一次 + 三次重启,第四次崩了就不再起"
    assert delays == [0.1, 0.2, 0.4, None], f"1 秒起翻倍(这里缩成 0.1 秒起),第四次不再起:{delays}"
    assert any("崩掉" in line for line in service.failure_lines)


def test_重启策略_一秒起翻倍_窗口里最多三次_窗口过了重新数(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(supervisor, "RESTART_BASE_DELAY", 1.0)
    policy = supervisor.RestartPolicy()
    assert [policy.next_delay(0.0), policy.next_delay(10.0), policy.next_delay(20.0)] == [1.0, 2.0, 4.0]
    assert policy.next_delay(30.0) is None, "5 分钟内第 4 次不再起"
    assert policy.recent(30.0) == 3
    assert policy.next_delay(400.0) == 1.0, "窗口过了从头数"


def test_重起的那一次没就绪就退出_也算一次崩溃(tmp_path: Path) -> None:
    """崩溃之后重起,新的那一个还没就绪就退出了:不是「第一次就没起来」,照样退避、计数,够了停在起不来。"""
    count = tmp_path / "count"
    service = _service(tmp_path)
    good = _spec(tmp_path, "--crash-after", "0.2", "--count", str(count))
    broken = LaunchSpec(**{**good.__dict__, "argv": [*good.argv[:2], "--port", str(good.port), "--exit-at-start", "2",
                                                       "--count", str(count)]})
    service.launch(good, respawn=lambda: broken)
    assert _wait_for(lambda: service.state == FAILED, 20), service.state
    assert service.error is not None and service.error.key == "localServiceErr_crashedTooOften"
    assert len(_starts(count)) == 1 + supervisor.MAX_RESTARTS


# ---- 停 ----------------------------------------------------------------------


@posix_only
def test_停的是整组_孙进程一起走(tmp_path: Path) -> None:
    child = tmp_path / "child.pid"
    service = _service(tmp_path)
    spec = _spec(tmp_path, "--child", str(child))
    service.launch(spec, respawn=lambda: spec)
    assert service.wait_settled(15) == RUNNING
    grandchild = int(child.read_text(encoding="utf-8"))
    assert process_alive(grandchild)
    service.stop()
    assert _wait_for(lambda: not process_alive(grandchild), 5), "它起的孙进程也停了(不留着占显存)"


@posix_only
def test_不理_SIGTERM_的到点强杀整组(tmp_path: Path) -> None:
    service = _service(tmp_path)
    spec = _spec(tmp_path, "--ignore-term")
    service.launch(spec, respawn=lambda: spec)
    assert service.wait_settled(15) == RUNNING
    pid = service.pid
    started = time.monotonic()
    service.stop(grace=0.5)
    assert service.state == STOPPED
    assert not process_alive(pid)
    assert time.monotonic() - started >= 0.5, "先等它自己退,到点才强杀"


def test_停下的时候不算崩溃_不重起(tmp_path: Path) -> None:
    count = tmp_path / "count"
    service = _service(tmp_path)
    spec = _spec(tmp_path, "--count", str(count))
    service.launch(spec, respawn=lambda: spec)
    assert service.wait_settled(15) == RUNNING
    service.stop()
    _supervision_over(service)
    assert service.state == STOPPED and len(_starts(count)) == 1


# ---- 接回 ------------------------------------------------------------------


@posix_only
def test_pid_在_命令行一样才算同一个_接回来以后崩了照样重起(tmp_path: Path) -> None:
    count = tmp_path / "count"
    first = _service(tmp_path, "adopt")
    spec = _spec(tmp_path, "--count", str(count))
    first.launch(spec, respawn=lambda: spec)
    assert first.wait_settled(15) == RUNNING
    pid = first.pid
    # 后端被强杀:进程内的看护没了,子进程自成一组还活着
    first._stop.set()
    supervisor._services.clear()
    supervisor._directories.clear()

    record = pidfiles.read_all()[0]
    assert pidfiles.same_process(record)
    assert not pidfiles.same_process(pidfiles.PidRecord(**{**record.__dict__, "argv": [*record.argv, "--别的"]})), \
        "命令行对不上(pid 被别的程序复用了)就不是它"
    assert not pidfiles.same_process(pidfiles.PidRecord(**{**record.__dict__, "pid": 2 ** 22 + 7})), "pid 不在就不是它"

    again = _service(tmp_path, "adopt")
    again.adopt(record, respawn=lambda: spec)
    assert again.state == RUNNING and again.adopted and again.pid == pid
    assert any("第 1 次启动" in line for line in again.log.tail(50)), "接回来以后从同一个日志文件接着读"

    os.kill(pid, 9)
    assert _wait_for(lambda: len(_starts(count)) == 2 and again.state == RUNNING), again.state
    assert not again.adopted, "重起的那个是这次后端起的"
    again.stop()


# ---- 目录锁、端口 ----------------------------------------------------------------


def test_同一个目录只起一份(tmp_path: Path) -> None:
    first = _service(tmp_path, "a")
    spec = _spec(tmp_path)
    assert supervisor.claim("a", "/same") is None
    first.launch(spec, respawn=lambda: spec)
    assert first.wait_settled(15) == RUNNING
    assert supervisor.claim("b", "/same") == "a", "第二个连接直接被告知是谁占着"
    assert supervisor.claim("a", "/same") is None, "自己再占一次没关系"
    first.stop()
    assert supervisor.claim("b", "/same") is None, "停了就放开"


def test_端口被占认得出() -> None:
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen()
        port = holder.getsockname()[1]
        assert supervisor.port_in_use(port)
    assert not supervisor.port_in_use(free_port())


# ---- 日志缓冲 ------------------------------------------------------------------


def test_日志缓冲_回车盖掉这一行_被切开的汉字不乱_最多两千行(tmp_path: Path) -> None:
    log = ServiceLog(tmp_path / "x.log", ring_lines=3)
    handle = log.open_for_child(fresh=True)
    handle.write("第一行\n进度 1%\r进度 50%".encode())
    handle.flush()
    assert log.tail() == ["第一行", "进度 50%"]
    word = "完成".encode()
    handle.write(b"\r" + word[:2])
    handle.flush()
    log.pump()
    handle.write(word[2:] + b"\n\n")
    handle.close()
    assert log.tail() == ["第一行", "完成", ""], "回车之后的字盖掉这一行;切在两次读之间的汉字照样读得出"
    with open(tmp_path / "x.log", "ab") as more:
        more.write(b"a\nb\nc\n")
    assert log.tail() == ["a", "b", "c"], "只留最近 ring_lines 行"
    assert service_logs.RING_LINES == 2000


def test_日志从头起时滚一次_一直开着太大了抄一份再截断(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "service-x.log"
    log = ServiceLog(path)
    with log.open_for_child(fresh=True) as handle:
        handle.write(b"first run\n")
    with log.open_for_child(fresh=True) as handle:
        handle.write(b"second run\n")
    assert path.with_name("service-x.log.1").read_text() == "first run\n", "从头起之前滚一次"
    assert log.tail() == ["second run"], "缓冲也从头来"
    with log.open_for_child(fresh=False) as handle:
        handle.write(b"after a crash\n")
    assert log.tail() == ["second run", "after a crash"], "崩溃后的重起接着写同一个文件"

    monkeypatch.setattr(service_logs, "MAX_BYTES", 20)
    with open(path, "ab") as handle:
        handle.write(b"x" * 30 + b"\n")
    log.pump()
    assert path.stat().st_size == 0 and "x" * 30 in path.with_name("service-x.log.1").read_text(), "太大了:抄进 .1、截断"
    with open(path, "ab") as handle:
        handle.write(b"keeps going\n")
    assert log.tail()[-1] == "keeps going", "截断以后接着从头读"
