"""异步任务轮询:提交拿 id → 轮询到终态。几乎所有外部生成 API 都是这个形状。"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import Any, TypeVar

from app.ai.providers.contracts.generation import (
    POLL_TIMEOUT_SECONDS,
    GenerationAdapterError,
    RemoteTaskSettled,
    provider_payload_settled,
    remember_remote_task,
    remote_task_cancelled,
    remote_task_interrupted,
    result_wanted,
)
from app.ai.providers.adapters.shared.errors import PollAnswerUnreadable, transient_poll_failure

#: 异步任务的默认节奏。各家可以覆盖,但没有理由的话就用这一份 —— 此前七个文件各定义了一次
#: 自己的 POLL_INTERVAL,而它们的值本来就一样。
POLL_INTERVAL_SECONDS = 2.0

#: 一次没问到(见 `transient_poll_failure`)之后隔多久再问:从轮询间隔起每次翻倍,封顶一分钟。合盖十几秒、换一次
#: Wi-Fi、查询接口限一阵流都等得过去;仍受六小时的上限和取消约束(ADR 0019 修订)。
TRANSIENT_BACKOFF_CAP_SECONDS = 60.0

_Ready = TypeVar("_Ready")


def _ask(client: Any, poll_path: str) -> dict[str, Any]:
    response = client.get(poll_path)
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise PollAnswerUnreadable("poll response is not JSON") from exc
    if not isinstance(payload, dict):
        raise PollAnswerUnreadable("poll response is not a JSON object")
    return payload


def _pause(seconds: float) -> None:
    """退避时一秒一秒地等,每一秒都看一眼取消 —— 断网时退避到一分钟,用户点了停止不该再干等一分钟。"""
    for _ in range(max(1, math.ceil(seconds))):
        if remote_task_cancelled():
            return
        time.sleep(min(1.0, seconds))


def poll_until_ready(
    client: Any,
    poll_path: str,
    extract: "Callable[[dict[str, Any]], _Ready | None]",
    *,
    interval: float = POLL_INTERVAL_SECONDS,
    timeout: float = POLL_TIMEOUT_SECONDS,
    vendor: str = "",
) -> tuple[_Ready, dict[str, Any]]:
    """轮询一个异步任务到终态,返回 (产物地址, 终态回包)。

    几乎所有外部生成 API 都是同一个形状:提交拿 id → 轮询到终态 → 下载。此前**六家各写了一遍
    这个循环**,各自定义间隔、各自抛超时 —— 代价不是行数,是每家都可能漏掉一件事,而没有任何
    机制能发现谁漏了。

    `extract` 负责读懂那一家的终态:拿到产物就回产物,还没结束回 None,失败**自己抛**
    (它才知道那家把失败原因放在哪个字段)。回的是一个地址还是**一串**地址由那一家决定 ——
    图像接口的 `n` 一次会给回多张,收成单数的话多出来的那几张就在这儿被丢掉了。

    计时用 `time.monotonic()` 而不是 `time.time()`:墙钟会跳(NTP 校时、夏令时),跳一下
    要么把还在跑的任务判成超时,要么让它多等一个小时。六家原本都用的是墙钟。

    **一次没问到不是结束。** 远端任务提交了就在花钱,网络抖一下、查询接口回一次 502、代理回一页 HTML,远端照样在做。
    此前这里任何一步抛异常都直接跳出循环,任务判失败、账记「未扣费」,远端做完的成片再没人去取 —— 用户照提示重来就是
    再付一次。现在这些(见 `transient_poll_failure`)退避再问,每次都报给运行器(界面上写「连接中断,正在重新连接」),
    接上了也报一声;只有确定性的失败(401 / 404、服务商判了失败)和六小时上限才结束等待(ADR 0019 修订)。
    """
    #: **开始等之前先报回执。** 这是远端任务号唯一一次离开适配器的局部变量。
    remember_remote_task(poll_path)
    deadline = time.monotonic() + timeout
    payload: dict[str, Any] = {}
    failures = 0
    while time.monotonic() < deadline:
        if remote_task_cancelled():
            raise GenerationAdapterError("providerErr_cancelled")
        try:
            payload = _ask(client, poll_path)
        except Exception as exc:
            if not transient_poll_failure(exc):
                raise
            failures += 1
            remote_task_interrupted(failures)
            _pause(min(interval * 2**failures, TRANSIENT_BACKOFF_CAP_SECONDS))
            continue
        if failures:
            failures = 0
            remote_task_interrupted(0)
        try:
            ready = extract(payload)
        except Exception:
            # 服务商判了失败(或者说完成了却没给结果):这也是终态。有的平台失败也扣,扣了多少写在这一份里。
            provider_payload_settled(payload)
            raise
        if ready:
            # **先交回包,再回产物。**调用方接下来要下载 —— 下载失败的话,这份写着用量和扣费的回包不能跟着丢。
            provider_payload_settled(payload)
            if not result_wanted():
                # 停下之后替记账跟到这里的:回包就是要的全部,成片不下(见 RemoteTaskWatch.collect)。
                raise RemoteTaskSettled()
            return ready, payload
        time.sleep(interval)
    # 是哪一家超时了由调用方给(`vendor`):那句话会一路显示到用户眼前,收成一份不带名字的
    # 通用句子等于把"是哪一家超时了"这个信息删掉。
    # 远端任务号一起说出来:走到这里它多半仍在花钱,那是唯一能让人去供应商后台找回它的线索。
    hours = f"{timeout / 3600:g}"
    if vendor:
        raise GenerationAdapterError("providerErr_vendorPollTimeout", vendor=vendor, task=poll_path, hours=hours)
    raise GenerationAdapterError("providerErr_pollTimeout", task=poll_path, hours=hours)
