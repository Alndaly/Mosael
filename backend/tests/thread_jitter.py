"""开关:每条新线程起步前随机等一会儿 —— 把「机器一忙,线程排不上」搬到本机来,专抓「靠线程先后才绿」的测试。

**默认不开。** 开法(整套或点名都行,和平时的命令一样,只多一个环境变量):

    cd backend
    MOSAEL_TEST_THREAD_JITTER=0.3 uv run --frozen python -m pytest -q
    MOSAEL_TEST_THREAD_JITTER=0.5 MOSAEL_TEST_THREAD_JITTER_SEED=7 uv run --frozen python -m pytest -q tests/test_x.py

`MOSAEL_TEST_THREAD_JITTER` 是上限(秒):每条线程在 `run()` 之前睡 0 到这么久里随机的一段。`…_SEED` 定种子
(不给就随机挑一个,打在 pytest 的表头里,红了照着它再跑)。

## 为什么不是加 CPU 压力

CI 上那几条随机红(「几项同时失败」第 3 项还没开始就被叫停、列表等探测、写盘竞态……)都是一个形状:测试默认
「我刚起的线程这会儿已经在跑了」「睡 0.3 秒它就进去了」。本机满核加压(32 个 worker + 14 核忙循环)跑全套,
二十分钟撞上两条;仿 CI 的 4 worker 加压跑二十一分钟一条没撞上 —— 线程只是慢了几毫秒。而把起步随机推后 0–0.3 秒,
全套十四分钟就红出四条,点名跑一个文件几秒钟就能 4/5 复现。

修这类测试的办法是**等事件、等条件**(替身阻塞在 `Event` / `Barrier` 上由测试放行,轮询等那个事实成立),
不是把睡眠加长 —— 见 docs/CONVENTIONS.md「测试里怎么等」。这个开关就是用来验收那样的修法的:开着它换几个种子都绿,才算修好。

只管 `threading.Thread.run` 没被子类改写的线程(`Thread(target=…)`、线程池的工作线程 —— 后端里起线程都是这么起的)。
"""

from __future__ import annotations

import os
import random
import threading
import time

ENV = "MOSAEL_TEST_THREAD_JITTER"
SEED_ENV = "MOSAEL_TEST_THREAD_JITTER_SEED"

_installed: tuple[float, int] | None = None


def install_from_env() -> None:
    """环境变量开着就装上(幂等);没开什么都不做。"""
    global _installed
    raw = os.environ.get(ENV, "").strip()
    if not raw or _installed is not None:
        return
    ceiling = float(raw)
    if ceiling <= 0:
        return
    seed = int(os.environ.get(SEED_ENV) or random.SystemRandom().randrange(1, 2**31))
    #: 写回环境变量:xdist 的 worker 是之后才起的子进程,继承它 —— 表头里打的种子就是 worker 们用的那一个。
    os.environ[SEED_ENV] = str(seed)
    #: 每个 xdist worker 用自己的一串数。同一个种子大致能重放 —— 线程谁先起本身不定,换了顺序拿到的延迟也就换了。
    worker = os.environ.get("PYTEST_XDIST_WORKER", "")
    rng = random.Random(f"{seed}:{worker}")
    lock = threading.Lock()
    original_run = threading.Thread.run

    def run_late(self: threading.Thread) -> None:
        with lock:
            delay = rng.uniform(0, ceiling)
        time.sleep(delay)
        original_run(self)

    threading.Thread.run = run_late  # type: ignore[method-assign]
    _installed = (ceiling, seed)


def header() -> str | None:
    """给 pytest 的表头:开着时说上限和种子,红了好重放。"""
    if _installed is None:
        return None
    ceiling, seed = _installed
    return f"thread jitter: 0–{ceiling:g}s before every thread starts ({ENV}), seed {seed} ({SEED_ENV}={seed} to replay)"
