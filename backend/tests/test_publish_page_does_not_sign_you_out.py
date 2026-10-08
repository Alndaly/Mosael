"""打开发布页不会把人登出:界面读「发布器在不在线」凭登录会话,不凭执行器密钥。

这条接口此前挂在执行器通道上(整组路由要 X-Mosael-Worker-Key)。界面拿不到那把密钥,每次打开发布页都收到 401;
而界面把任何 401 都当成「登录过期」—— 一打开发布页就回到登录屏(批二真界面验证时撞上的)。
"""

from __future__ import annotations

from app.core.worker_key import WORKER_KEY_HEADER
from tests.util import fresh_client


def test_登录了的界面不带执行器密钥也读得到发布器在不在线() -> None:
    client = fresh_client()
    assert WORKER_KEY_HEADER not in client.headers

    response = client.get("/api/publish/worker/status")

    assert response.status_code == 200, "401 会让界面当成登录过期,把人登出"
    assert response.json() == {"online": False}


def test_没登录的读不到() -> None:
    client = fresh_client()
    client.headers.pop("Authorization")
    assert client.get("/api/publish/worker/status").status_code == 401
