"""插件 OAuth:替用户做那段机械的、也最容易抄错的部分。

注册应用拿 AppKey/SecretKey 替代不了 —— 那是他和开放平台之间的事。能替代的是后面那一段:
拼授权链接、拿 code 换令牌、把令牌写回哪几个键。全是机械动作,而每一步抄错换回来的都是
一句英文报错(`invalid_client` / `redirect_uri_mismatch`),看不出错在哪一格。

所以这里验的都是那段纯逻辑,以及两条"错了不报错"的规矩:

· **对方没给的字段不写** —— 刷新时常常只回 access_token,把缺失当空串写回去会**抹掉已有的
  refresh_token**,而那一份丢了就得重新授权一遍;
· **声明不全就当没声明** —— 半个 oauth 块会让界面长出一个点了必然失败的按钮。
"""

from __future__ import annotations

import pytest

from app.domain.plugins.manifest import OAuthSpec
from app.domain.plugins.oauth import (
    PluginOAuthError,
    authorize_url,
    credentials_from_token,
    token_request,
)

BAIDU = OAuthSpec(
    authorize_url="https://openapi.baidu.com/oauth/2.0/authorize",
    token_url="https://openapi.baidu.com/oauth/2.0/token",
    client_id_field="APP_KEY",
    client_secret_field="SECRET_KEY",
    scope="basic,netdisk",
    redirect_uri="oob",
    stores={"refresh_token": "REFRESH_TOKEN", "access_token": "ACCESS_TOKEN"},
)


def test_授权链接按声明拼出来() -> None:
    url = authorize_url(BAIDU, {"APP_KEY": "abc123"})
    assert url.startswith("https://openapi.baidu.com/oauth/2.0/authorize?")
    for part in ("response_type=code", "client_id=abc123", "redirect_uri=oob", "scope=basic%2Cnetdisk"):
        assert part in url, part


def test_端点本来就带问号时接的是与号() -> None:
    spec = OAuthSpec(**{**BAIDU.__dict__, "authorize_url": "https://x.test/auth?tenant=1"})
    assert "?tenant=1&response_type=code" in authorize_url(spec, {"APP_KEY": "k"})


def test_没填_appkey_时说清楚缺哪一格() -> None:
    """不说的话,用户会点进一个 invalid_client 的页面,而那句报错不会告诉他缺的是这一格。"""
    with pytest.raises(PluginOAuthError) as error:
        authorize_url(BAIDU, {})
    assert "APP_KEY" in str(error.value)


def test_换令牌的参数带上密钥和同一个重定向地址() -> None:
    # redirect_uri 在换令牌时也要带,而且必须和授权时一模一样 —— 不一致换来的是
    # redirect_uri_mismatch,一个看不出哪儿不一致的报错。
    payload = token_request(BAIDU, {"APP_KEY": "abc", "SECRET_KEY": "sec"}, " the-code ")
    assert payload == {
        "grant_type": "authorization_code",
        "code": "the-code",
        "client_id": "abc",
        "redirect_uri": "oob",
        "client_secret": "sec",
    }


def test_令牌响应按声明映射回凭据键() -> None:
    got = credentials_from_token(BAIDU, {"refresh_token": "r1", "access_token": "a1", "expires_in": 2592000})
    assert got == {"REFRESH_TOKEN": "r1", "ACCESS_TOKEN": "a1"}


def test_对方没给的字段不写回去() -> None:
    """刷新时常常只回 access_token。把缺失当空串写回,已有的 refresh_token 就没了 ——
    而那一份丢了要重新走一遍授权。"""
    got = credentials_from_token(BAIDU, {"access_token": "a2"})
    assert got == {"ACCESS_TOKEN": "a2"}
    assert "REFRESH_TOKEN" not in got


def test_对方的报错原样转出去() -> None:
    """`invalid_client` 比"授权失败"有用得多 —— 它至少说明是 AppKey 那一格的事。"""
    with pytest.raises(PluginOAuthError) as error:
        credentials_from_token(BAIDU, {"error": "invalid_client", "error_description": "unknown client id"})
    assert "unknown client id" in str(error.value)


def test_一个声明过的字段都没回就说出来() -> None:
    with pytest.raises(PluginOAuthError) as error:
        credentials_from_token(BAIDU, {"something_else": "x"})
    assert "stores" in str(error.value)


def test_声明不全就当没声明() -> None:
    """半个 oauth 块会让界面长出一个点了必然失败的按钮。"""
    from app.domain.plugins.manifest import _oauth

    assert _oauth({"authorize_url": "https://x.test/a"}) is None  # 缺 token_url / client_id_field / stores
    assert _oauth(None) is None
    assert _oauth({
        "authorize_url": "https://x.test/a",
        "token_url": "https://x.test/t",
        "client_id_field": "K",
        "stores": {"refresh_token": "R"},
    }) is not None


def test_oauth_块读的是_instance_那一层() -> None:
    """位置钉死在这里,因为放错了**不会报错**,只会让授权按钮静默不出现。

    界面上那个按钮的显示条件是 `manifest.oauth is not None`。块写在顶层(它引用的
    client_id_field / stores 都在 instance.credentials 里,写在旁边是很自然的选择)时,
    解析器读不到,于是 oauth 为 None,按钮不出现,而**没有任何一处报错** —— 用户看到的
    只是"没有授权入口",作者看到的是"我明明声明了"。写解析器的人自己就踩进去过一次。
    """
    from app.domain.plugins.manifest import parse

    block = {
        "authorize_url": "https://x.test/auth",
        "token_url": "https://x.test/token",
        "client_id_field": "KEY",
        "stores": {"refresh_token": "R"},
    }
    base = {"id": "x.y", "manifest_version": 1, "name": "X", "version": "1", "_path": "/tmp/x"}

    assert parse({**base, "instance": {"oauth": block}}, "x").oauth is not None
    # 顶层写法读不到 —— 这一条不是"支持两种",是钉住只有一种。
    assert parse({**base, "oauth": block, "instance": {}}, "x").oauth is None


def test_百度网盘自己声明了_oauth() -> None:
    """机制做完了却没在任何插件上声明,等于对用户不存在 —— 这正是它上线时的样子:
    oauth.py 有、路由有、按钮有,唯独 manifest 里没声明,于是那条路一次也没被走到。"""
    import json
    import pathlib

    from app.domain.plugins.manifest import parse

    root = pathlib.Path(__file__).resolve().parents[2]
    raw = json.loads((root / "plugins/examples/baidu-pan/mosael.plugin.json").read_text(encoding="utf-8"))
    raw["_path"] = str(root)
    manifest = parse(raw, "baidu-pan")

    assert manifest.oauth is not None, "百度网盘要能自己走授权,否则用户只能手抄 refresh_token"
    # stores 指向的必须是真实存在的凭据键,否则换回来的令牌无处可存。
    keys = {field.key for field in manifest.credentials}
    assert set(manifest.oauth.stores.values()) <= keys
    assert manifest.oauth.client_id_field in keys
    assert manifest.oauth.client_secret_field in keys
