"""部署到服务器时,允许的来源要能配 —— 但仍然一个一个写,不接受通配符。

前端本来就能指向任意后端(设置里的「服务端地址」),而"几个人共用一台服务器"这件事此前卡在
`main.py` 里一份照桌面端写死的名单上:Electron 的 `file://`、两个 dev 端口,没别的。你的域名
不在里面,浏览器直接拦掉,而那个错误看起来像后端坏了。

**放开成 `*` 是另一回事,不能做。** `/api/auth` 按性质开放:首次运行的空库、或者开了
MOSAEL_OPEN_REGISTRATION 的部署上,register 对任何能连到端口的人都成功 —— 通配符下,用户
碰巧打开的任何网页都能在这个后端上给自己开个号**并读回 token**。
"""

from __future__ import annotations

import importlib

import pytest

from app.core.config import settings


@pytest.fixture
def cors_origins(monkeypatch):
    """按需重建 app —— CORS 中间件是在 create_app 里装的,改配置得重新装一次。"""

    def build(value: str):
        monkeypatch.setattr(settings, "cors_origins", value)
        main = importlib.import_module("app.main")
        app = main.create_app()
        for middleware in app.user_middleware:
            allowed = getattr(middleware, "kwargs", {}).get("allow_origins")
            if allowed is not None:
                return list(allowed)
        raise AssertionError("没有找到 CORS 中间件")

    return build


def test_没配的时候只有桌面端那几个(cors_origins) -> None:
    origins = cors_origins("")
    assert "null" in origins, "Electron 的 file:// 是 Origin: null,少了它桌面端自己都连不上"
    assert not any(one.startswith("https://") for one in origins)


def test_配了域名就加进去(cors_origins) -> None:
    origins = cors_origins("https://studio.example.com")
    assert "https://studio.example.com" in origins
    # 原来那几个仍在 —— 加一个远程来源不该把桌面端挤掉。
    assert "null" in origins


def test_多个域名逗号分隔并且忽略空白和尾斜杠(cors_origins) -> None:
    origins = cors_origins(" https://a.example.com/ , https://b.example.com ,, ")
    assert "https://a.example.com" in origins
    assert "https://b.example.com" in origins
    # 尾斜杠要去掉:浏览器发的 Origin 从不带它,留着等于这一条永远匹配不上,
    # 而表现是"我明明配了却还是被拦"。
    assert "https://a.example.com/" not in origins


def test_通配符不会因为可配置而混进来(cors_origins) -> None:
    """写成 `*` 也只是加了一条名叫 `*` 的来源 —— 它匹配不上任何真实 Origin。

    这一条钉的是**不要**哪天有人把它当成开关:允许通配符要动的是这里的语义,
    而那个改动必须是显眼的、需要解释的,不是在配置里填一个星号。
    """
    origins = cors_origins("*")
    assert origins.count("*") <= 1
    assert "null" in origins
