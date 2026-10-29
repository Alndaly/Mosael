"""在线购买(ADR 0088 第 3 步):下单拿二维码、渠道回调与主动查单都只发放一次、金额要对、续费顺延、验签不过不发放。

支付宝与微信都跑**真的**签名 / 验签 / 解密代码,只把网络换成 `httpx2.MockTransport`:假网关先用我们的公钥验我们发出去的签名,
再用「渠道私钥」(测试里生成)签它的回包 —— 两头的规则都被钉住。
"""

from __future__ import annotations

import base64
import json
import secrets
import time
from datetime import timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx2
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient
from sqlalchemy import select

from cloud.config import CloudConfig
from cloud.domain import credits
from cloud.models import CloudOrder, CloudPlan, CloudSubscription, CloudUser, now
from cloud.payments.alipay import AlipayChannel, sign_content
from cloud.payments.wechat import WechatPayChannel
from conftest import RecordingSender, api, signed_in

APP_ID = "2021000000000001"
MCHID = "1900000001"
WX_APPID = "wx0000000000000001"
APIV3_KEY = "0123456789abcdef0123456789abcdef"
WX_PUBKEY_ID = "PUB_KEY_ID_0001"


def rsa_pair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return key, private, public


def rsa_sign(key, text: bytes) -> str:
    return base64.b64encode(key.sign(text, padding.PKCS1v15(), hashes.SHA256())).decode()


def rsa_verify(public_pem: bytes, text: bytes, signature: str) -> None:
    serialization.load_pem_public_key(public_pem).verify(base64.b64decode(signature), text, padding.PKCS1v15(), hashes.SHA256())


# ---------------------------------------------------------------- 假支付宝


class FakeAlipay:
    def __init__(self) -> None:
        self.app_key, self.app_private, self.app_public = rsa_pair()
        self.platform_key, _, self.platform_public = rsa_pair()
        self.requests: list[dict[str, str]] = []
        #: out_trade_no → query 时回的 trade_status(没有 = 交易不存在)
        self.trades: dict[str, dict[str, str]] = {}

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        params = dict(parse_qsl(request.content.decode()))
        self.requests.append(params)
        signature = params.pop("sign")
        rsa_verify(self.app_public, sign_content(params).encode(), signature)  # 我们发出去的签名必须验得过
        biz = json.loads(params["biz_content"])
        method = params["method"]
        if method == "alipay.trade.precreate":
            node = {"code": "10000", "msg": "Success", "out_trade_no": biz["out_trade_no"],
                    "qr_code": f"https://qr.alipay.com/{biz['out_trade_no'][:8]}"}
        else:
            trade = self.trades.get(biz["out_trade_no"])
            node = ({"code": "10000", "msg": "Success", "out_trade_no": biz["out_trade_no"], **trade} if trade
                    else {"code": "40004", "msg": "Business Failed", "sub_code": "ACQ.TRADE_NOT_EXIST"})
        node_text = json.dumps(node, ensure_ascii=False, separators=(",", ":"))
        key = method.replace(".", "_") + "_response"
        raw = f'{{"{key}":{node_text},"sign":"{rsa_sign(self.platform_key, node_text.encode())}"}}'
        return httpx2.Response(200, content=raw.encode(), headers={"content-type": "application/json;charset=utf-8"})

    def channel(self, notify_url: str) -> AlipayChannel:
        return AlipayChannel(app_id=APP_ID, app_private_key=self.app_private, alipay_public_key=self.platform_public,
                             notify_url=notify_url, transport=httpx2.MockTransport(self.handler))

    def notify_body(self, order_id: str, amount: str, *, status: str = "TRADE_SUCCESS", app_id: str = APP_ID,
                    tamper: bool = False) -> bytes:
        params = {"app_id": app_id, "out_trade_no": order_id, "trade_no": "2026102922001", "trade_status": status,
                  "total_amount": amount, "gmt_payment": "2026-10-29 18:00:00", "notify_type": "trade_status_sync"}
        signature = rsa_sign(self.platform_key, sign_content(params).encode())
        if tamper:
            params["total_amount"] = "0.01"
        return urlencode({**params, "sign": signature, "sign_type": "RSA2"}).encode()


# ---------------------------------------------------------------- 假微信支付


class FakeWechat:
    def __init__(self) -> None:
        self.merchant_key, self.merchant_private, self.merchant_public = rsa_pair()
        self.platform_key, _, self.platform_public = rsa_pair()
        self.requests: list[httpx2.Request] = []
        self.transactions: dict[str, dict[str, object]] = {}

    def signed_headers(self, body: bytes, *, timestamp: int | None = None) -> dict[str, str]:
        stamp, nonce = str(timestamp or int(time.time())), secrets.token_hex(8)
        signature = rsa_sign(self.platform_key, f"{stamp}\n{nonce}\n".encode() + body + b"\n")
        return {"Wechatpay-Timestamp": stamp, "Wechatpay-Nonce": nonce, "Wechatpay-Signature": signature,
                "Wechatpay-Serial": WX_PUBKEY_ID, "Content-Type": "application/json"}

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        auth = request.headers["authorization"]
        assert auth.startswith("WECHATPAY2-SHA256-RSA2048 ")
        fields = dict(part.split("=", 1) for part in auth.split(" ", 1)[1].split(","))
        fields = {key: value.strip('"') for key, value in fields.items()}
        assert fields["mchid"] == MCHID and fields["serial_no"] == "MERCHANT_SERIAL"
        split = urlsplit(str(request.url))
        path = split.path + (f"?{split.query}" if split.query else "")
        message = f"{request.method}\n{path}\n{fields['timestamp']}\n{fields['nonce_str']}\n{request.content.decode()}\n"
        rsa_verify(self.merchant_public, message.encode(), fields["signature"])  # 我们的请求签名必须验得过
        if request.method == "POST":
            body = json.dumps({"code_url": "weixin://wxpay/bizpayurl?pr=abc"}).encode()
            return httpx2.Response(200, content=body, headers=self.signed_headers(body))
        order_id = split.path.rsplit("/", 1)[1]
        transaction = self.transactions.get(order_id)
        if transaction is None:
            body = json.dumps({"code": "ORDER_NOT_EXIST", "message": "订单不存在"}).encode()
            return httpx2.Response(404, content=body, headers=self.signed_headers(body))
        body = json.dumps(transaction).encode()
        return httpx2.Response(200, content=body, headers=self.signed_headers(body))

    def channel(self, notify_url: str) -> WechatPayChannel:
        return WechatPayChannel(
            mchid=MCHID, appid=WX_APPID, merchant_serial_no="MERCHANT_SERIAL", merchant_private_key=self.merchant_private,
            apiv3_key=APIV3_KEY, platform_public_key=self.platform_public, platform_public_key_id=WX_PUBKEY_ID,
            notify_url=notify_url, transport=httpx2.MockTransport(self.handler),
        )

    def transaction(self, order_id: str, total: int, *, mchid: str = MCHID) -> dict[str, object]:
        return {"mchid": mchid, "appid": WX_APPID, "out_trade_no": order_id, "transaction_id": "4200000001",
                "trade_state": "SUCCESS", "success_time": "2026-10-29T18:00:00+08:00", "amount": {"total": total}}

    def notify(self, transaction: dict[str, object], *, timestamp: int | None = None) -> tuple[bytes, dict[str, str]]:
        nonce = secrets.token_hex(6)
        ciphertext = AESGCM(APIV3_KEY.encode()).encrypt(nonce.encode(), json.dumps(transaction).encode(), b"transaction")
        body = json.dumps({
            "id": "EV-1", "event_type": "TRANSACTION.SUCCESS", "resource_type": "encrypt-resource",
            "resource": {"algorithm": "AEAD_AES_256_GCM", "ciphertext": base64.b64encode(ciphertext).decode(),
                         "associated_data": "transaction", "nonce": nonce},
        }).encode()
        return body, self.signed_headers(body, timestamp=timestamp)


# ---------------------------------------------------------------- 夹具


@pytest.fixture
def alipay() -> FakeAlipay:
    return FakeAlipay()


@pytest.fixture
def wechat() -> FakeWechat:
    return FakeWechat()


@pytest.fixture
def shop(tmp_path, alipay, wechat):
    from cloud.app import create_app

    config = CloudConfig(data_dir=tmp_path, public_url="https://mosael.test", cookie_secure=False)
    channels = {"alipay": alipay.channel("https://mosael.test/api/cloud/v1/payments/alipay/notify"),
                "wechat": wechat.channel("https://mosael.test/api/cloud/v1/payments/wechat/notify")}
    app = create_app(config, code_sender=RecordingSender(), payment_channels=channels)
    with app.state.db.session() as db:
        db.add(CloudPlan(slug="pro", name="Pro", period="month", monthly_credits=1000, credit_ttl_days=60, price_cents=2900))
        db.add(CloudPlan(slug="max", name="Max", period="year", monthly_credits=5000, credit_ttl_days=60, price_cents=99900))
        db.add(CloudPlan(slug="beta", name="内测", period="month", monthly_credits=100, credit_ttl_days=30))
        db.commit()
    return app


def buyer(app) -> TestClient:
    client = TestClient(app)
    signed_in(client)
    return client


def order_of(client: TestClient, plan: str = "pro", channel: str = "alipay") -> dict:
    response = client.post(api("/orders"), json={"plan": plan, "channel": channel})
    assert response.status_code == 201, response.text
    return response.json()["order"]


def notify_alipay(client: TestClient, body: bytes):
    return client.post(api("/payments/alipay/notify"), content=body,
                       headers={"content-type": "application/x-www-form-urlencoded"})


def credits_of(app) -> int:
    with app.state.db.session() as db:
        return credits.balance(db, db.scalar(select(CloudUser)).id, at=now()).total


def stored(app, order_id: str) -> CloudOrder:
    with app.state.db.session() as db:
        return db.get(CloudOrder, order_id)


# ---------------------------------------------------------------- 套餐与下单


def test_plans_lists_priced_plans_and_the_open_channels(shop):
    body = TestClient(shop).get(api("/plans")).json()
    assert [one["slug"] for one in body["plans"]] == ["pro", "max"]  # 没标价的内测套餐不在线卖
    assert body["plans"][0]["price_cents"] == 2900 and body["plans"][0]["currency"] == "CNY"
    assert body["channels"] == ["alipay", "wechat"]


def test_ordering_needs_a_priced_plan_and_an_open_channel(tmp_path, alipay):
    from cloud.app import create_app

    app = create_app(CloudConfig(data_dir=tmp_path, public_url="https://mosael.test", cookie_secure=False),
                     code_sender=RecordingSender(), payment_channels={})
    with app.state.db.session() as db:
        db.add(CloudPlan(slug="pro", name="Pro", period="month", monthly_credits=1, credit_ttl_days=1, price_cents=100))
        db.add(CloudPlan(slug="beta", name="B", period="month", monthly_credits=1, credit_ttl_days=1))
        db.commit()
    client = buyer(app)
    assert client.post(api("/orders"), json={"plan": "beta", "channel": "alipay"}).json()["error"] == "plan_not_for_sale"
    refused = client.post(api("/orders"), json={"plan": "pro", "channel": "alipay"})
    assert refused.status_code == 400 and refused.json()["error"] == "payment_channel_unavailable"
    with app.state.db.session() as db:
        assert db.scalar(select(CloudOrder)) is None


def test_an_alipay_order_carries_a_signed_precreate_and_a_qr_code(shop, alipay):
    client = buyer(shop)
    order = order_of(client)
    assert order["status"] == "pending" and order["amount_cents"] == 2900
    assert order["code_url"].startswith("https://qr.alipay.com/")
    sent = alipay.requests[-1]
    assert sent["method"] == "alipay.trade.precreate" and sent["app_id"] == APP_ID
    assert sent["notify_url"] == "https://mosael.test/api/cloud/v1/payments/alipay/notify"
    biz = json.loads(sent["biz_content"])
    assert biz == {"out_trade_no": order["id"], "total_amount": "29.00", "subject": "Mosael Pro",
                   "time_expire": biz["time_expire"]}


# ---------------------------------------------------------------- 到账与发放


def test_an_alipay_notify_grants_the_plan_once(shop, alipay):
    client = buyer(shop)
    order = order_of(client)
    response = notify_alipay(TestClient(shop), alipay.notify_body(order["id"], "29.00"))
    assert response.status_code == 200 and response.text == "success"
    assert stored(shop, order["id"]).status == "paid"
    assert credits_of(shop) == 1000
    #: 回调重发:还是只发一次。
    assert notify_alipay(TestClient(shop), alipay.notify_body(order["id"], "29.00")).text == "success"
    assert credits_of(shop) == 1000
    view = client.get(api(f"/orders/{order['id']}")).json()["order"]
    assert view["status"] == "paid" and view["code_url"] is None


def test_a_forged_or_tampered_alipay_notify_grants_nothing(shop, alipay):
    client = buyer(shop)
    order = order_of(client)
    assert notify_alipay(TestClient(shop), alipay.notify_body(order["id"], "29.00", tamper=True)).text == "fail"
    assert notify_alipay(TestClient(shop), alipay.notify_body(order["id"], "29.00", app_id="2021999")).text == "fail"
    assert stored(shop, order["id"]).status == "pending"
    assert credits_of(shop) == 0


def test_a_wrong_amount_is_acknowledged_but_not_granted(shop, alipay):
    client = buyer(shop)
    order = order_of(client)
    assert notify_alipay(TestClient(shop), alipay.notify_body(order["id"], "0.01")).text == "success"
    found = stored(shop, order["id"])
    assert found.status == "pending" and "amount mismatch" in found.note
    assert credits_of(shop) == 0


def test_a_lost_callback_is_caught_by_polling_the_order(shop, alipay):
    client = buyer(shop)
    order = order_of(client)
    assert client.get(api(f"/orders/{order['id']}")).json()["order"]["status"] == "pending"
    alipay.trades[order["id"]] = {"trade_status": "TRADE_SUCCESS", "trade_no": "T1", "total_amount": "29.00",
                                  "send_pay_date": "2026-10-29 18:00:00"}
    assert client.get(api(f"/orders/{order['id']}")).json()["order"]["status"] == "paid"
    assert credits_of(shop) == 1000


def test_an_unpaid_order_closes_after_it_expires_and_a_late_payment_still_counts(shop, alipay):
    client = buyer(shop)
    order = order_of(client)
    with shop.state.db.session() as db:
        row = db.get(CloudOrder, order["id"])
        row.expires_at = now() - timedelta(minutes=1)
        db.commit()
    assert client.get(api(f"/orders/{order['id']}")).json()["order"]["status"] == "closed"
    assert notify_alipay(TestClient(shop), alipay.notify_body(order["id"], "29.00")).text == "success"
    assert stored(shop, order["id"]).status == "paid"
    assert credits_of(shop) == 1000


def test_buying_the_same_plan_again_extends_it_and_another_plan_runs_alongside(shop, alipay):
    client = buyer(shop)
    first = order_of(client)
    notify_alipay(TestClient(shop), alipay.notify_body(first["id"], "29.00"))
    with shop.state.db.session() as db:
        subscription = db.scalar(select(CloudSubscription))
        first_end = subscription.ends_at
    second = order_of(client)
    notify_alipay(TestClient(shop), alipay.notify_body(second["id"], "29.00"))
    with shop.state.db.session() as db:
        subscriptions = db.scalars(select(CloudSubscription)).all()
        assert len(subscriptions) == 1
        assert subscriptions[0].ends_at == credits.add_months(first_end, 1)
        assert stored(shop, second["id"]).subscription_id == subscriptions[0].id
    view = client.get(api(f"/orders/{second['id']}")).json()["order"]
    assert view["subscription_ends_at"] == credits.add_months(first_end, 1).isoformat()

    upgrade = order_of(client, plan="max")
    notify_alipay(TestClient(shop), alipay.notify_body(upgrade["id"], "999.00"))
    with shop.state.db.session() as db:
        #: 买了另一个套餐:和现有的同时生效,预付的那段不作废。
        subscriptions = db.scalars(select(CloudSubscription)).all()
        assert sorted(one.status for one in subscriptions) == ["active", "active"]
        pro = next(one for one in subscriptions if one.ends_at == credits.add_months(first_end, 1))
        assert pro.status == "active"
    assert credits_of(shop) == 1000 + 5000


def test_someone_elses_order_is_not_found(shop, alipay):
    client = buyer(shop)
    order = order_of(client)
    other = TestClient(shop)
    signed_in(other, email="bob@example.com")
    assert other.get(api(f"/orders/{order['id']}")).status_code == 404


def test_the_desktop_can_order_with_its_device_token(shop, alipay):
    client = buyer(shop)
    secret = client.post(api("/device-tokens"), json={"name": "Mac"}).json()["secret"]
    client.cookies.clear()
    client.headers["Authorization"] = f"Bearer {secret}"
    assert order_of(client)["status"] == "pending"


# ---------------------------------------------------------------- 微信支付


def notify_wechat(app, body: bytes, headers: dict[str, str]):
    return TestClient(app).post(api("/payments/wechat/notify"), content=body, headers=headers)


def test_a_wechat_order_is_signed_and_its_encrypted_notify_grants_once(shop, wechat):
    client = buyer(shop)
    order = order_of(client, channel="wechat")
    assert order["code_url"] == "weixin://wxpay/bizpayurl?pr=abc"
    sent = json.loads(wechat.requests[-1].content)
    assert sent["amount"] == {"total": 2900, "currency": "CNY"}
    assert sent["notify_url"] == "https://mosael.test/api/cloud/v1/payments/wechat/notify"
    assert sent["out_trade_no"] == order["id"] and sent["mchid"] == MCHID and sent["appid"] == WX_APPID

    body, headers = wechat.notify(wechat.transaction(order["id"], 2900))
    assert notify_wechat(shop, body, headers).status_code == 204
    assert notify_wechat(shop, body, headers).status_code == 204
    assert stored(shop, order["id"]).status == "paid"
    assert credits_of(shop) == 1000


def test_wechat_notifies_that_do_not_verify_are_refused(shop, wechat):
    client = buyer(shop)
    order = order_of(client, channel="wechat")
    body, headers = wechat.notify(wechat.transaction(order["id"], 2900))
    tampered = body.replace(b'"EV-1"', b'"EV-2"')
    assert notify_wechat(shop, tampered, headers).status_code == 400
    stale_body, stale_headers = wechat.notify(wechat.transaction(order["id"], 2900), timestamp=int(time.time()) - 3600)
    assert notify_wechat(shop, stale_body, stale_headers).status_code == 400
    foreign_body, foreign_headers = wechat.notify(wechat.transaction(order["id"], 2900, mchid="1999"))
    assert notify_wechat(shop, foreign_body, foreign_headers).status_code == 400
    assert stored(shop, order["id"]).status == "pending"
    assert credits_of(shop) == 0


def test_a_lost_wechat_callback_is_caught_by_a_signed_query(shop, wechat):
    client = buyer(shop)
    order = order_of(client, channel="wechat")
    assert client.get(api(f"/orders/{order['id']}")).json()["order"]["status"] == "pending"
    wechat.transactions[order["id"]] = wechat.transaction(order["id"], 2900)
    assert client.get(api(f"/orders/{order['id']}")).json()["order"]["status"] == "paid"
    assert credits_of(shop) == 1000


# ---------------------------------------------------------------- 配置里的密钥写法


def test_keys_are_read_as_pem_a_pem_file_or_a_bare_base64_string(tmp_path):
    """支付宝控制台给的是不带头尾的一整串 base64:粘过来就能用;PKCS#8 和 PKCS#1 的私钥都认。"""
    from cryptography.hazmat.primitives.asymmetric import rsa as rsa_keys

    from cloud.payments.base import pem

    key = rsa_keys.generate_private_key(public_exponent=65537, key_size=2048)
    pkcs8 = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    pkcs1 = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                              serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)

    def bare(pem_bytes: bytes) -> str:
        return "".join(line for line in pem_bytes.decode().splitlines() if not line.startswith("-----"))

    for private in (pkcs8, pkcs1):
        for written in (private.decode(), bare(private)):
            loaded = serialization.load_pem_private_key(pem(written, kind="private"), password=None)
            assert loaded.private_numbers() == key.private_numbers()
    assert serialization.load_pem_public_key(pem(bare(public), kind="public")).public_numbers() == key.public_key().public_numbers()
    on_disk = tmp_path / "app.pem"
    on_disk.write_bytes(pkcs8)
    assert pem(str(on_disk), kind="private") == pkcs8
    with pytest.raises(ValueError):
        pem("not a key!", kind="private")
