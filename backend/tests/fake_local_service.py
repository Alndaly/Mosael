"""本机服务测试用的假服务(ADR 0041 §6「测试」):几行 Python 的 HTTP 服务,能按指令慢启动、崩、不响应、起孙进程。

    python fake_local_service.py --port 8189 [--slow 2] [--hang] [--exit-at-start 3] [--crash-after 0.5]
                                 [--crash-first 2] [--count FILE] [--child FILE] [--ignore-term] [--mute-after 0.5]

- `GET /system_stats` 回 200 和一小段 JSON(像 ComfyUI 那样),别的路径 404;
- `--slow`:先睡这么久再开始听(第一次启动要解包前端的那种);
- `--hang`:一直不听(就绪超时);
- `--exit-at-start`:还没听就以这个退出码退出(参数不对、缺依赖);
- `--crash-after`:**头一回答了健康检查之后**过这么久崩掉(退出码 1);
- `--crash-first N`:配 `--count`,前 N 次启动都在就绪之后崩掉,之后稳住(崩溃重启之后能恢复);
- `--count`:每次启动往这个文件追加一行(数它起了几次);
- `--child`:起一个孙进程(一直睡),把它的 pid 写进这个文件(验「停整组」);
- `--ignore-term`:不理 SIGTERM(验「10 秒后强杀」);
- `--mute-after`:就绪之后(头一回答了健康检查之后)过这么久不再应答(关掉监听),进程照样活着(「进程在、却没有应答」)。

**它和它起的孙进程都跟着起它的那个测试进程走**:测试进程没了(被 kill -9、超时掐掉),它们自己退出(见 `_follow_owner`)。
看护起服务时给的是一个新的会话、日志写进文件,测试进程死了它们收不到信号、也读不到管道断开;此前测试进程一被强杀,
它们就以 1 号进程为父一直挂着(实测撞到过两天前留下的八个)。

「崩」「不再应答」都从**头一回答了健康检查**算,不从开始听算:看护那边要先看到它就绪,这两件事才是「运行中崩了 / 没了应答」。
此前从开始听算,看护线程起得晚 0.2 秒,进程就在被看到就绪之前崩了 —— 测的成了「还没就绪就退出」。

启动时往 stdout 打几行日志:一行中文、一段用回车刷新的进度条 —— 日志缓冲按终端的样子收。
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


#: 头一回答了健康检查(有人看到它就绪了)。
_seen_ready = threading.Event()

#: 起这个假服务的测试进程。孙进程从环境变量里拿到同一个,跟着的是测试进程,不是这个假服务 ——
#: 「停整组,孙进程也走」那条要看的是看护把整组停掉了,孙进程不能因为假服务没了就自己先走。
OWNER_ENV = "FAKE_SERVICE_OWNER"
#: 孙进程:一直在,直到起它的测试进程没了。
FOLLOWER = (
    "import os, time\n"
    f"owner = int(os.environ[{OWNER_ENV!r}])\n"
    "while True:\n"
    "    time.sleep(0.2)\n"
    "    try:\n"
    "        os.kill(owner, 0)\n"
    "    except OSError:\n"
    "        break\n"
)


def _follow_owner() -> None:
    """测试进程一没,这个假服务就退出(os._exit:不等别的线程、不跑清理)。"""
    owner = int(os.environ[OWNER_ENV])

    def watch() -> None:
        while True:
            time.sleep(0.2)
            try:
                os.kill(owner, 0)
            except OSError:  # 没了(ProcessLookupError),或者号已经被别人的进程用上(PermissionError)
                os._exit(0)

    threading.Thread(target=watch, daemon=True).start()


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 — http.server 的约定
        if self.path != "/system_stats":
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps({"system": {"comfyui_version": "0.0.0-fake", "pid": os.getpid()}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()
        _seen_ready.set()

    def log_message(self, *_args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--listen", default="127.0.0.1")
    parser.add_argument("--slow", type=float, default=0.0)
    parser.add_argument("--hang", action="store_true")
    parser.add_argument("--exit-at-start", type=int, default=None)
    parser.add_argument("--crash-after", type=float, default=None)
    parser.add_argument("--crash-first", type=int, default=0)
    parser.add_argument("--count", default="")
    parser.add_argument("--child", default="")
    parser.add_argument("--ignore-term", action="store_true")
    parser.add_argument("--mute-after", type=float, default=None)
    args = parser.parse_args()
    os.environ.setdefault(OWNER_ENV, str(os.getppid()))
    _follow_owner()

    starts = 1
    if args.count:
        with open(args.count, "a", encoding="utf-8") as handle:
            handle.write(f"{os.getpid()}\n")
        with open(args.count, encoding="utf-8") as handle:
            starts = len(handle.read().splitlines())
    if args.ignore_term:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    print(f"假服务第 {starts} 次启动,pid {os.getpid()},环境 FAKE_ENV={os.environ.get('FAKE_ENV', '')}", flush=True)
    for percent in (10, 50, 100):
        sys.stdout.write(f"\r加载 {percent}%")
        sys.stdout.flush()
    sys.stdout.write("\n")
    sys.stdout.flush()
    if args.child:
        child = subprocess.Popen([sys.executable, "-c", FOLLOWER])
        with open(args.child, "w", encoding="utf-8") as handle:
            handle.write(str(child.pid))
    if args.exit_at_start is not None:
        print("缺了一个依赖,起不来", flush=True)
        sys.exit(args.exit_at_start)
    if args.hang:
        while True:
            time.sleep(1)
    time.sleep(args.slow)
    server = ThreadingHTTPServer((args.listen, args.port), _Handler)
    print(f"听在 {args.listen}:{args.port}", flush=True)
    crash_after = args.crash_after
    if args.crash_first and starts <= args.crash_first:
        crash_after = crash_after if crash_after is not None else 0.3
    elif args.crash_first:
        crash_after = None
    if crash_after is not None:
        def crash() -> None:
            _seen_ready.wait()
            time.sleep(crash_after)
            print("出错了,崩掉", flush=True)
            os._exit(1)

        threading.Thread(target=crash, daemon=True).start()
    if args.mute_after is not None:
        def mute() -> None:
            _seen_ready.wait()
            time.sleep(args.mute_after)
            print("不再应答(进程还在)", flush=True)
            server.shutdown()
            server.server_close()

        threading.Thread(target=mute, daemon=True).start()
        server.serve_forever()
        while True:
            time.sleep(1)
    server.serve_forever()


if __name__ == "__main__":
    main()
