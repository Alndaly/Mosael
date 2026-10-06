"""本机服务测试用的假服务(ADR 0041 §6「测试」):几行 Python 的 HTTP 服务,能按指令慢启动、崩、不响应、起孙进程。

    python fake_local_service.py --port 8189 [--slow 2] [--hang] [--exit-at-start 3] [--crash-after 0.5]
                                 [--crash-first 2] [--count FILE] [--child FILE] [--ignore-term] [--mute-after 0.5]

- `GET /system_stats` 回 200 和一小段 JSON(像 ComfyUI 那样),别的路径 404;
- `--slow`:先睡这么久再开始听(第一次启动要解包前端的那种);
- `--hang`:一直不听(就绪超时);
- `--exit-at-start`:还没听就以这个退出码退出(参数不对、缺依赖);
- `--crash-after`:听起来以后过这么久崩掉(退出码 1);
- `--crash-first N`:配 `--count`,前 N 次启动都在就绪之后崩掉,之后稳住(崩溃重启之后能恢复);
- `--count`:每次启动往这个文件追加一行(数它起了几次);
- `--child`:起一个孙进程(一直睡),把它的 pid 写进这个文件(验「停整组」);
- `--ignore-term`:不理 SIGTERM(验「10 秒后强杀」);
- `--mute-after`:就绪之后过这么久不再应答(关掉监听),进程照样活着(「进程在、却没有应答」)。

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
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
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
            time.sleep(crash_after)
            print("出错了,崩掉", flush=True)
            os._exit(1)

        threading.Thread(target=crash, daemon=True).start()
    if args.mute_after is not None:
        def mute() -> None:
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
