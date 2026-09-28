"""出站网络配置那一行单例,几条线程同时第一次读也只建一行、谁都不报错。

几个插件调用同时起跑时各自读到「还没有」、各自去建,后到的撞唯一约束 —— CI 上
test_同时在跑的插件调用不超过名额 反复红在 `UNIQUE constraint failed: network_config.id`。
"""

from __future__ import annotations

import threading

from sqlalchemy import delete, func, select

from app.core.db import SessionLocal
from app.db.models import NetworkConfig
from app.domain import network
from tests.util import fresh_client


def test_同时第一次读_只建一行_谁都拿得到() -> None:
    fresh_client()
    with SessionLocal() as db:
        db.execute(delete(NetworkConfig))
        db.commit()

    start = threading.Barrier(6)
    errors: list[BaseException] = []
    seen: list[str] = []

    def read() -> None:
        try:
            start.wait()
            with SessionLocal() as db:
                seen.append(network.get_config(db).id)
        except BaseException as exc:  # noqa: BLE001 — 收起来在主线程断言
            errors.append(exc)

    threads = [threading.Thread(target=read) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, errors
    assert seen == ["default"] * 6
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(NetworkConfig)) == 1
        assert network.get_config(db).no_proxy, "默认绕过列表照样填上"
