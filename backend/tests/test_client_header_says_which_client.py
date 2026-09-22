"""`X-Mosael-Client` 在两个客户端上曾经是两个意思。

前端发 `__APP_VERSION__`(`1.4.2`),浏览器扩展发字面量 `browser-extension` —— 同一栏,
一个是版本,一个是产品名。后端原样存进 `auth_sessions.client_version`,管理页照着渲染
`v{...}`:扩展用户那一行显示的是**「vbrowser-extension」**。

两边各自都"对"。错在这一栏从来没有被定义过是什么 —— 所以现在它有语法:`<界面>/<版本>`,
在后端**一处**解析,拆进两列。认不出来就是一对空串:老客户端在野外升不动,而"不知道"
本来就是这两栏的合法状态,比编一个假的诚实。
"""

from __future__ import annotations

from app.api.deps.auth import CLIENT_SURFACES, parse_client_header
from tests.util import fresh_client


def test_语法是界面加版本() -> None:
    assert parse_client_header("app/1.4.3") == ("app", "1.4.3")
    assert parse_client_header("browser-extension/0.1.0") == ("browser-extension", "0.1.0")
    assert parse_client_header("  app/1.4.3  ") == ("app", "1.4.3")


def test_认不出来的一律当没报() -> None:
    # 旧语法:裸版本号。它此前会被原样存下来。
    assert parse_client_header("1.4.2") == ("", "")
    # 旧语法:裸产品名 —— 正是渲染成「vbrowser-extension」的那一个。
    assert parse_client_header("browser-extension") == ("", "")
    assert parse_client_header("") == ("", "")
    assert parse_client_header("app/") == ("", "")


def test_界面只认我们自己发的那几个() -> None:
    """这一栏会**原样显示给管理员**,而请求头是外部输入。"""
    assert parse_client_header("evil/1.0.0") == ("", "")
    assert parse_client_header("app/<script>") == ("", "")
    # 版本那一半也有形状,不能变成一条能塞任意文本的通道。
    assert parse_client_header("app/" + "x" * 33) == ("", "")
    assert set(CLIENT_SURFACES) == {"app", "browser-extension"}


def test_自报的身份两栏都落到库里() -> None:
    """这条走**真的请求**,不直接构造会话 —— 记录发生在登录身份收口点上,
    而"某条路由忘了记"正是那个收口点存在的理由。"""
    client = fresh_client()
    client.get("/api/workspaces", headers={"X-Mosael-Client": "browser-extension/0.1.0"})

    from app.core.db import SessionLocal
    from app.db.models import AuthSession

    with SessionLocal() as db:
        session = db.query(AuthSession).order_by(AuthSession.created_at.desc()).first()
        assert session is not None
        assert (session.client_surface, session.client_version) == ("browser-extension", "0.1.0")


def test_老客户端报旧语法时两栏都留空() -> None:
    """不编一个界面出来 —— 管理页那一行显示"版本未知",而不是一个看起来像真的假值。"""
    client = fresh_client(username="oldie")
    client.get("/api/workspaces", headers={"X-Mosael-Client": "1.4.2"})

    from app.core.db import SessionLocal
    from app.db.models import AuthSession

    with SessionLocal() as db:
        session = db.query(AuthSession).order_by(AuthSession.created_at.desc()).first()
        assert session is not None
        # 先确认**记录那一步真的跑过了**(它同时盖 last_seen_at)—— 否则两栏为空这件事
        # 和"压根没走到这里"长得一模一样,断言天然成立。
        assert session.last_seen_at is not None
        assert (session.client_surface, session.client_version) == ("", "")
