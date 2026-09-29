"""异步任务轮询:提交拿 id → 轮询到终态。几乎所有外部生成 API 都是这个形状。"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, TypeVar

from app.ai.providers.contracts.generation import (
    POLL_TIMEOUT_SECONDS,
    GenerationAdapterError,
    remember_remote_task,
    remote_task_cancelled,
)

#: 异步任务的默认节奏。各家可以覆盖,但没有理由的话就用这一份 —— 此前七个文件各定义了一次
#: 自己的 POLL_INTERVAL,而它们的值本来就一样。
POLL_INTERVAL_SECONDS = 2.0

_Ready = TypeVar("_Ready")


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
    """
    #: **开始等之前先报回执。** 这是远端任务号唯一一次离开适配器的局部变量。
    remember_remote_task(poll_path)
    deadline = time.monotonic() + timeout
    payload: dict[str, Any] = {}
    while time.monotonic() < deadline:
        if remote_task_cancelled():
            raise GenerationAdapterError("providerErr_cancelled")
        response = client.get(poll_path)
        response.raise_for_status()
        payload = response.json()
        ready = extract(payload)
        if ready:
            return ready, payload
        time.sleep(interval)
    # 是哪一家超时了由调用方给(`vendor`):那句话会一路显示到用户眼前,收成一份不带名字的
    # 通用句子等于把"是哪一家超时了"这个信息删掉。
    # 远端任务号一起说出来:走到这里它多半仍在花钱,那是唯一能让人去供应商后台找回它的线索。
    hours = f"{timeout / 3600:g}"
    if vendor:
        raise GenerationAdapterError("providerErr_vendorPollTimeout", vendor=vendor, task=poll_path, hours=hours)
    raise GenerationAdapterError("providerErr_pollTimeout", task=poll_path, hours=hours)
