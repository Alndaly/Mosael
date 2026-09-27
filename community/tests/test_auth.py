"""账号与令牌:短信、密码、找回、刷新轮换与重用检测、宽限期、设备授权。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import API, TERMS, FakeCaptcha, age_sms, auth, send_code, sms_login
from sqlalchemy import select, update

from community.db import utcnow
from community.models import AuthSession, DeviceAuthorization, RefreshToken, SmsCode, User

PHONE = "+8613800000001"


def refresh_cookie(client) -> str | None:
    """服务端最后一次 Set-Cookie 给的那枚(测试自己塞进去的那枚没有域名,排在后面)。"""
    found = [cookie for cookie in client.cookies.jar if cookie.name == "mosael_refresh"]
    from_server = [cookie for cookie in found if cookie.domain]
    return (from_server or found)[-1].value if found else None


def use_cookie(client, value: str) -> None:
    """换成指定的那枚刷新令牌 cookie(先清掉 cookie 罐,免得同名的两枚一起带上)。"""
    client.cookies.clear()
    client.cookies.set("mosael_refresh", value)


# ---------------- 短信 ----------------


def test_短信登录_第一次即注册_刷新令牌只在_cookie_里(client, sms, ctx) -> None:
    send_code(client, "13800000001")  # 11 位的补 +86
    assert sms.sent[-1][0] == PHONE
    response = client.post(f"{API}/auth/sms/login", json={"phone": PHONE, "code": sms.last_code(), "agree_terms_version": TERMS})
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"access_token", "expires_in", "user"}
    assert body["expires_in"] == 900
    assert body["user"]["phone"] == "+86138****0001"
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "samesite=lax" in cookie.lower()
    assert f"Path={API}/auth" in cookie
    me = client.get(f"{API}/me", headers=auth(body["access_token"]))
    assert me.status_code == 200 and me.json()["handle"] == body["user"]["handle"]
    with ctx.sessions() as db:
        assert db.scalars(select(User)).one().terms_version == TERMS
    # 第二次同号登录不再注册
    age_sms(ctx, 61)
    again = sms_login(client, sms, PHONE)
    assert again["user"]["id"] == body["user"]["id"]


def test_验证码只存哈希(client, sms, ctx) -> None:
    send_code(client, PHONE)
    code = sms.last_code()
    with ctx.sessions() as db:
        row = db.scalars(select(SmsCode)).one()
        assert code not in row.code_hash and len(row.code_hash) == 64


def test_没同意协议或版本不对(client, sms) -> None:
    send_code(client, PHONE)
    code = sms.last_code()
    missing = client.post(f"{API}/auth/sms/login", json={"phone": PHONE, "code": code})
    assert missing.status_code == 400 and missing.json()["error"]["code"] == "terms_required"
    old = client.post(f"{API}/auth/sms/login", json={"phone": PHONE, "code": code, "agree_terms_version": "old"})
    assert old.json()["error"]["code"] == "terms_outdated"


def test_60_秒内不重发(client, sms, ctx) -> None:
    send_code(client, PHONE)
    again = client.post(f"{API}/auth/sms/send", json={"phone": PHONE, "purpose": "login"})
    assert again.status_code == 429
    assert again.json()["error"]["code"] == "sms_too_frequent"
    assert int(again.headers["retry-after"]) <= 61
    age_sms(ctx, 61)
    send_code(client, PHONE)
    assert len(sms.sent) == 2


def test_同一号码每天至多_10_条(client, sms, ctx) -> None:
    for _ in range(10):
        send_code(client, PHONE)
        age_sms(ctx, 61)
    over = client.post(f"{API}/auth/sms/send", json={"phone": PHONE, "purpose": "login"})
    assert over.status_code == 429 and over.json()["error"]["code"] == "sms_daily_limit"
    age_sms(ctx, 24 * 3600)
    send_code(client, PHONE)


def test_同一_IP_每小时至多_20_条(client, sms) -> None:
    for index in range(20):
        send_code(client, f"+86139000000{index:02d}")
    over = client.post(f"{API}/auth/sms/send", json={"phone": "+8613900000099", "purpose": "login"})
    assert over.status_code == 429 and over.json()["error"]["code"] == "sms_ip_limit"


def test_一个码最多试_5_次(client, sms) -> None:
    send_code(client, PHONE)
    right = sms.last_code()
    wrong = "000000" if right != "000000" else "111111"
    codes = []
    for _ in range(5):
        response = client.post(f"{API}/auth/sms/login", json={"phone": PHONE, "code": wrong, "agree_terms_version": TERMS})
        codes.append(response.json()["error"]["code"])
    assert codes == ["code_invalid"] * 4 + ["code_attempts_exceeded"]
    after = client.post(f"{API}/auth/sms/login", json={"phone": PHONE, "code": right, "agree_terms_version": TERMS})
    assert after.json()["error"]["code"] == "code_attempts_exceeded"


def test_验证码_5_分钟过期_用过一次作废(client, sms, ctx) -> None:
    send_code(client, PHONE)
    code = sms.last_code()
    age_sms(ctx, 301)
    expired = client.post(f"{API}/auth/sms/login", json={"phone": PHONE, "code": code, "agree_terms_version": TERMS})
    assert expired.json()["error"]["code"] == "code_expired"
    send_code(client, PHONE)
    code = sms.last_code()
    ok = client.post(f"{API}/auth/sms/login", json={"phone": PHONE, "code": code, "agree_terms_version": TERMS})
    assert ok.status_code == 201
    reused = client.post(f"{API}/auth/sms/login", json={"phone": PHONE, "code": code, "agree_terms_version": TERMS})
    assert reused.json()["error"]["code"] == "code_expired"


def test_新发一条_旧码作废(client, sms, ctx) -> None:
    send_code(client, PHONE)
    first = sms.last_code()
    age_sms(ctx, 61)
    send_code(client, PHONE)
    if first != sms.last_code():
        response = client.post(f"{API}/auth/sms/login", json={"phone": PHONE, "code": first, "agree_terms_version": TERMS})
        assert response.status_code == 400


def test_发送失败不占额度(client, sms, ctx) -> None:
    sms.fail = True
    response = client.post(f"{API}/auth/sms/send", json={"phone": PHONE, "purpose": "login"})
    assert response.status_code == 502 and response.json()["error"]["code"] == "sms_send_failed"
    with ctx.sessions() as db:
        assert db.scalars(select(SmsCode)).all() == []


def test_配了人机验证就必须过(client, sms, ctx) -> None:
    ctx.captcha = FakeCaptcha()
    missing = client.post(f"{API}/auth/sms/send", json={"phone": PHONE, "purpose": "login"})
    assert missing.status_code == 400 and missing.json()["error"]["code"] == "captcha_required"
    bad = client.post(
        f"{API}/auth/sms/send", json={"phone": PHONE, "purpose": "login", "captcha": {"ticket": "bad", "randstr": "r"}}
    )
    assert bad.status_code == 403 and bad.json()["error"]["code"] == "captcha_failed"
    send_code(client, PHONE, captcha={"ticket": "good-ticket", "randstr": "r"})
    assert len(sms.sent) == 1


def test_找回密码对没注册的号码不发也不说(client, sms) -> None:
    send_code(client, PHONE, purpose="reset")
    assert sms.sent == []


def test_错误回包的形状与语言(client) -> None:
    zh = client.post(f"{API}/auth/sms/send", json={"phone": "12", "purpose": "login"})
    assert zh.status_code == 422
    assert zh.json() == {"error": {"code": "invalid_phone", "message": "手机号格式不对"}}
    en = client.post(f"{API}/auth/sms/send", json={"phone": "12", "purpose": "login"}, headers={"Accept-Language": "en-US,en;q=0.9"})
    assert en.json()["error"]["message"] == "That phone number doesn't look right."
    malformed = client.post(f"{API}/auth/sms/send", json={"purpose": "login"})
    assert malformed.status_code == 422 and malformed.json()["error"]["code"] == "invalid_request"
    assert "phone" in malformed.json()["error"]["message"]


# ---------------- 密码 ----------------


def register(client, sms, *, handle="alice", password="correct horse", phone=PHONE) -> dict:
    send_code(client, phone, purpose="bind")
    response = client.post(
        f"{API}/auth/register",
        json={"handle": handle, "password": password, "phone": phone, "code": sms.last_code(phone), "agree_terms_version": TERMS},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_注册必须绑手机_然后能用用户名或手机号登录(client, sms, ctx) -> None:
    body = register(client, sms)
    assert body["user"]["handle"] == "alice" and body["user"]["has_password"] is True
    with ctx.sessions() as db:
        stored = db.scalars(select(User)).one().password_hash
        assert stored.startswith("$argon2id$")
    for login in ("alice", "ALICE", "13800000001", PHONE):
        response = client.post(f"{API}/auth/password/login", json={"login": login, "password": "correct horse"})
        assert response.status_code == 200, (login, response.text)


def test_注册时号码和用户名被占用(client, sms, ctx) -> None:
    register(client, sms)
    taken = client.post(f"{API}/auth/sms/send", json={"phone": PHONE, "purpose": "bind"})
    assert taken.status_code == 409 and taken.json()["error"]["code"] == "phone_taken"
    send_code(client, "+8613800000002", purpose="bind")
    response = client.post(
        f"{API}/auth/register",
        json={"handle": "alice", "password": "another pw", "phone": "+8613800000002", "code": sms.last_code(), "agree_terms_version": TERMS},
    )
    assert response.status_code == 409 and response.json()["error"]["code"] == "handle_taken"
    reserved = client.post(
        f"{API}/auth/register",
        json={"handle": "official", "password": "another pw", "phone": "+8613800000002", "code": "x", "agree_terms_version": TERMS},
    )
    assert reserved.json()["error"]["code"] == "handle_reserved"


def test_密码连错按账号锁定(client, sms) -> None:
    register(client, sms)
    codes = [
        client.post(f"{API}/auth/password/login", json={"login": "alice", "password": "wrong password"}).json()["error"]["code"]
        for _ in range(6)
    ]
    assert codes[:5] == ["invalid_credentials"] * 5
    assert codes[5] == "login_locked"
    locked = client.post(f"{API}/auth/password/login", json={"login": "alice", "password": "correct horse"})
    assert locked.status_code == 429 and locked.json()["error"]["code"] == "login_locked"


def test_密码连错按_IP_锁定(client, sms, ctx) -> None:
    ctx.settings.password_ip_max_failures = 3
    for index in range(3):
        client.post(f"{API}/auth/password/login", json={"login": f"nobody{index}", "password": "whatever pw"})
    blocked = client.post(f"{API}/auth/password/login", json={"login": "someone_else", "password": "whatever pw"})
    assert blocked.json()["error"]["code"] == "login_locked"


def test_找回密码后全部会话吊销(client, sms, ctx) -> None:
    register(client, sms)
    old_cookie = refresh_cookie(client)
    age_sms(ctx, 61)
    send_code(client, PHONE, purpose="reset")
    response = client.post(f"{API}/auth/password/reset", json={"phone": PHONE, "code": sms.last_code(), "new_password": "brand new pw"})
    assert response.status_code == 204
    use_cookie(client, old_cookie)
    refreshed = client.post(f"{API}/auth/refresh", headers={"X-Requested-With": "fetch"})
    assert refreshed.status_code == 401 and refreshed.json()["error"]["code"] == "session_expired"
    assert client.post(f"{API}/auth/password/login", json={"login": "alice", "password": "brand new pw"}).status_code == 200


def test_改密码吊销别的会话_留下当前这个(client, sms, ctx) -> None:
    body = register(client, sms)
    other = client.post(f"{API}/auth/password/login", json={"login": "alice", "password": "correct horse"}).json()
    response = client.post(
        f"{API}/me/password",
        json={"current_password": "correct horse", "new_password": "next password"},
        headers=auth(body["access_token"]),
    )
    assert response.status_code == 204
    assert client.get(f"{API}/me", headers=auth(body["access_token"])).status_code == 200
    assert client.get(f"{API}/me", headers=auth(other["access_token"])).status_code == 401


# ---------------- 刷新 ----------------


def test_网页刷新要_X_Requested_With(client, sms) -> None:
    sms_login(client, sms)
    response = client.post(f"{API}/auth/refresh")
    assert response.status_code == 403 and response.json()["error"]["code"] == "csrf_header_missing"


def test_刷新即轮换_旧令牌过了宽限期再用_整个会话吊销(client, sms, ctx) -> None:
    sms_login(client, sms)
    first = refresh_cookie(client)
    rotated = client.post(f"{API}/auth/refresh", headers={"X-Requested-With": "fetch"})
    assert rotated.status_code == 200
    second = refresh_cookie(client)
    assert second and second != first
    assert "refresh_token" not in rotated.json()
    # 把旧令牌的「被换掉的时间」挪到宽限期之外,再拿它来刷新 → 视为被盗
    with ctx.sessions() as db:
        db.execute(update(RefreshToken).where(RefreshToken.rotated_at.is_not(None)).values(rotated_at=utcnow() - timedelta(seconds=30)))
        db.commit()
    use_cookie(client, first)
    reused = client.post(f"{API}/auth/refresh", headers={"X-Requested-With": "fetch"})
    assert reused.status_code == 401 and reused.json()["error"]["code"] == "refresh_reused"
    # 整个会话都下线了:连新的那枚也不能用了
    use_cookie(client, second)
    after = client.post(f"{API}/auth/refresh", headers={"X-Requested-With": "fetch"})
    assert after.status_code == 401
    with ctx.sessions() as db:
        assert db.scalars(select(AuthSession)).one().revoke_reason == "refresh_reused"


def test_宽限期内并发刷新拿到同一对令牌(client, sms, ctx) -> None:
    sms_login(client, sms)
    first = refresh_cookie(client)
    one = client.post(f"{API}/auth/refresh", headers={"X-Requested-With": "fetch"})
    new_cookie = refresh_cookie(client)
    use_cookie(client, first)
    two = client.post(f"{API}/auth/refresh", headers={"X-Requested-With": "fetch"})
    assert two.status_code == 200
    assert two.json()["access_token"] == one.json()["access_token"]
    assert refresh_cookie(client) == new_cookie
    with ctx.sessions() as db:
        assert db.scalars(select(AuthSession)).one().revoked_at is None


def test_应用用_body_刷新_回包里有新的刷新令牌(client, sms, ctx) -> None:
    body = device_login(client, sms, ctx)
    response = client.post(f"{API}/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert response.status_code == 200
    assert response.json()["refresh_token"] != body["refresh_token"]
    assert "set-cookie" not in response.headers


def test_会话到了绝对上限就不能再刷新(client, sms, ctx) -> None:
    sms_login(client, sms)
    with ctx.sessions() as db:
        db.execute(update(AuthSession).values(absolute_expires_at=utcnow() - timedelta(seconds=1)))
        db.commit()
    response = client.post(f"{API}/auth/refresh", headers={"X-Requested-With": "fetch"})
    assert response.status_code == 401 and response.json()["error"]["code"] == "session_expired"


def test_刷新推后滑动窗口但不超过绝对上限(client, sms, ctx) -> None:
    sms_login(client, sms)
    with ctx.sessions() as db:
        db.execute(update(AuthSession).values(absolute_expires_at=utcnow() + timedelta(days=2)))
        db.commit()
    client.post(f"{API}/auth/refresh", headers={"X-Requested-With": "fetch"})
    with ctx.sessions() as db:
        session = db.scalars(select(AuthSession)).one()
        assert session.expires_at <= session.absolute_expires_at


def test_退出吊销当前会话(client, sms) -> None:
    body = sms_login(client, sms)
    response = client.post(f"{API}/auth/logout", headers=auth(body["access_token"]))
    assert response.status_code == 204
    assert client.get(f"{API}/me", headers=auth(body["access_token"])).status_code == 401


def test_会话列表与吊销(client, sms) -> None:
    web = sms_login(client, sms)
    sessions = client.get(f"{API}/me/sessions", headers=auth(web["access_token"])).json()
    assert len(sessions["items"]) == 1 and sessions["items"][0]["current"] is True
    assert sessions["next_cursor"] is None
    session_id = sessions["items"][0]["id"]
    assert client.delete(f"{API}/me/sessions/{session_id}", headers=auth(web["access_token"])).status_code == 204
    assert client.get(f"{API}/me", headers=auth(web["access_token"])).status_code == 401


# ---------------- 设备授权 ----------------


def device_login(client, sms, ctx) -> dict:
    web = sms_login(client, sms)
    code = client.post(f"{API}/auth/device/code", json={"client_name": "Mosael on MacBook"}).json()
    approve = client.post(f"{API}/auth/device/approve", json={"user_code": code["user_code"]}, headers=auth(web["access_token"]))
    assert approve.status_code == 204
    with ctx.sessions() as db:
        db.execute(update(DeviceAuthorization).values(last_polled_at=None))
        db.commit()
    token = client.post(f"{API}/auth/device/token", json={"device_code": code["device_code"]})
    assert token.status_code == 200, token.text
    return token.json()


def test_设备授权的各个状态(client, sms, ctx) -> None:
    code = client.post(f"{API}/auth/device/code", json={"client_name": "Mosael on MacBook"}, headers={"Accept-Language": "zh-CN"})
    assert code.status_code == 200
    grant = code.json()
    assert set(grant) >= {"device_code", "user_code", "verification_uri", "expires_in", "interval"}
    assert grant["verification_uri"] == "https://mosael.test/zh/device"
    assert len(grant["user_code"]) == 9 and grant["user_code"][4] == "-"
    assert all(ch in "BCDFGHJKLMNPQRSTVWXZ" for ch in grant["user_code"].replace("-", ""))

    pending = client.post(f"{API}/auth/device/token", json={"device_code": grant["device_code"]})
    assert pending.status_code == 428 and pending.json()["error"]["code"] == "authorization_pending"
    too_fast = client.post(f"{API}/auth/device/token", json={"device_code": grant["device_code"]})
    assert too_fast.status_code == 429 and too_fast.json()["error"]["code"] == "slow_down"
    assert too_fast.headers["retry-after"] == "10"

    web = sms_login(client, sms)
    # 用户码小写、不带横线也认
    loose = grant["user_code"].replace("-", "").lower()
    assert client.post(f"{API}/auth/device/approve", json={"user_code": loose}, headers=auth(web["access_token"])).status_code == 204
    with ctx.sessions() as db:
        db.execute(update(DeviceAuthorization).values(last_polled_at=utcnow() - timedelta(seconds=30)))
        db.commit()
    token = client.post(f"{API}/auth/device/token", json={"device_code": grant["device_code"]})
    assert token.status_code == 200
    body = token.json()
    assert set(body) == {"access_token", "expires_in", "user", "refresh_token"}
    assert "set-cookie" not in token.headers
    with ctx.sessions() as db:
        app_session = db.scalars(select(AuthSession).where(AuthSession.kind == "app")).one()
        assert app_session.device_name == "Mosael on MacBook"
    # 设备码只能换一次
    again = client.post(f"{API}/auth/device/token", json={"device_code": grant["device_code"]})
    assert again.status_code == 400 and again.json()["error"]["code"] == "device_code_invalid"


def test_设备码过期(client, sms, ctx) -> None:
    grant = client.post(f"{API}/auth/device/code", json={"client_name": "x"}).json()
    with ctx.sessions() as db:
        db.execute(update(DeviceAuthorization).values(expires_at=utcnow() - timedelta(seconds=1)))
        db.commit()
    expired = client.post(f"{API}/auth/device/token", json={"device_code": grant["device_code"]})
    assert expired.status_code == 410 and expired.json()["error"]["code"] == "expired_token"
    web = sms_login(client, sms)
    approve = client.post(f"{API}/auth/device/approve", json={"user_code": grant["user_code"]}, headers=auth(web["access_token"]))
    assert approve.status_code == 410


def test_确认设备要先登录_码不对说找不到(client, sms) -> None:
    grant = client.post(f"{API}/auth/device/code", json={}).json()
    assert client.post(f"{API}/auth/device/approve", json={"user_code": grant["user_code"]}).status_code == 401
    web = sms_login(client, sms)
    wrong = client.post(f"{API}/auth/device/approve", json={"user_code": "BBBB-BBBB"}, headers=auth(web["access_token"]))
    assert wrong.status_code == 404 and wrong.json()["error"]["code"] == "user_code_invalid"


def test_未知设备码(client) -> None:
    response = client.post(f"{API}/auth/device/token", json={"device_code": "nope"})
    assert response.status_code == 400


# ---------------- 我 ----------------


def test_handle_只能改一次_昵称随时改(client, sms) -> None:
    body = sms_login(client, sms)
    headers = auth(body["access_token"])
    first = client.patch(f"{API}/me", json={"handle": "bob_1", "display_name": "Bob"}, headers=headers)
    assert first.status_code == 200 and first.json()["handle"] == "bob_1" and first.json()["handle_changeable"] is False
    second = client.patch(f"{API}/me", json={"handle": "bob_2"}, headers=headers)
    assert second.status_code == 409 and second.json()["error"]["code"] == "handle_change_used"
    assert client.patch(f"{API}/me", json={"display_name": "Bobby"}, headers=headers).json()["display_name"] == "Bobby"


def test_访问令牌过期或伪造(client, sms, ctx) -> None:
    from community.tokens import encode_access

    body = sms_login(client, sms)
    me = client.get(f"{API}/me", headers=auth(body["access_token"])).json()
    with ctx.sessions() as db:
        session_id = db.scalars(select(AuthSession)).one().id
    stale = encode_access(ctx.keys, user_id=me["id"], session_id=session_id, role="user", iat=1_000_000, ttl=900)
    expired = client.get(f"{API}/me", headers=auth(stale))
    assert expired.status_code == 401 and expired.json()["error"]["code"] == "token_expired"
    forged = client.get(f"{API}/me", headers=auth(body["access_token"][:-4] + "AAAA"))
    assert forged.status_code == 401


@pytest.mark.parametrize("login", ["", "a"])
def test_密码登录参数不全(client, login) -> None:
    response = client.post(f"{API}/auth/password/login", json={"login": login, "password": "whatever pw"})
    assert response.status_code == 401
