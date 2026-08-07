"""会话令牌不明文落库。

令牌就是**这个人本人** —— 拿到它等于拿到他的一切,而且不需要密码。密码早就只存哈希了,令牌
却整串写在 auth_sessions.token 上:一次库泄露(或者一份被拷走的数据目录、一次误发的备份)里,
所有还没过期的令牌都可以直接拿去用,而受害者这边不会有任何痕迹。

**存哈希而不是加密**:这里根本不需要把原文取回来 —— 校验时把来客手上那串再哈希一次比对即可。
能取回原文的方案(比如 EncryptedText)在库泄露时只把问题挪到「主密钥在哪」,而哈希让库里那份
彻底没有价值。

存的形状是 `sha256:<hex>`。带前缀是为了让迁移能分辨:原始令牌本身就是 64 位十六进制
(secrets.token_hex(32)),和裸哈希长得一模一样,没有前缀就没法判断某一行迁过没有。
"""

from __future__ import annotations

import hashlib

from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import AuthSession
from tests.util import fresh_client


def _stored_tokens() -> list[str]:
    with SessionLocal() as db:
        return list(db.scalars(select(AuthSession.token)))


def _raw_token(client) -> str:
    """客户端手上那串原文 —— fresh_client 把它放在 Authorization 头里。"""
    return client.headers["Authorization"].removeprefix("Bearer ").strip()


def test_the_raw_token_is_nowhere_in_the_database() -> None:
    client = fresh_client()
    raw = _raw_token(client)
    assert raw, "登录之后应该有一份凭据"

    assert raw not in _stored_tokens()


def test_what_is_stored_is_the_hash_of_it() -> None:
    """不是随便另存了一串 —— 校验要靠它对得上。"""
    client = fresh_client()
    raw = _raw_token(client)

    assert f"sha256:{hashlib.sha256(raw.encode()).hexdigest()}" in _stored_tokens()


def test_the_credential_still_works() -> None:
    """哈希是存储形状的改变,不是登出。"""
    client = fresh_client()

    assert client.get("/api/auth/me").status_code == 200


def test_an_old_plaintext_row_is_migrated_in_place() -> None:
    """老库里那些明文行要就地哈希掉,而且人不掉线 —— 他手上那串还是原来那串。"""
    from app.core.db import _migrate_hash_session_tokens, engine
    from sqlalchemy import text

    client = fresh_client()
    raw = _raw_token(client)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE auth_sessions SET token = :raw WHERE token = :hashed"),
            {"raw": raw, "hashed": f"sha256:{hashlib.sha256(raw.encode()).hexdigest()}"},
        )
    assert raw in _stored_tokens(), "先把它改回明文,才谈得上迁移"

    _migrate_hash_session_tokens()

    assert raw not in _stored_tokens()
    assert client.get("/api/auth/me").status_code == 200, "迁移不该把人踢下线"


def test_running_the_migration_twice_does_not_double_hash() -> None:
    """迁移会被每次启动跑一遍。哈希两次的话,所有人一次性掉线。"""
    from app.core.db import _migrate_hash_session_tokens

    client = fresh_client()
    before = _stored_tokens()

    _migrate_hash_session_tokens()
    _migrate_hash_session_tokens()

    assert _stored_tokens() == before
    assert client.get("/api/auth/me").status_code == 200


def test_nobody_looks_the_token_up_by_hand() -> None:
    """查找必须走 core.security 那一个入口。

    `db.get(AuthSession, token)` 直接传原文的写法有五处;漏掉任何一处的后果不是报错,而是
    **那条路径静默地认不出人来**(或者更糟:某处又把原文写了回去)。所以这条盯的是形状。
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders = [
        f"{path.relative_to(root)}:{index}"
        for path in root.rglob("*.py")
        for index, line in enumerate(path.read_text().splitlines(), 1)
        if re.search(r"db\.get\(\s*AuthSession", line) and "core/security.py" not in str(path)
    ]

    assert not offenders, "别直接按令牌取行,用 core.security.find_session:\n  " + "\n  ".join(offenders)
