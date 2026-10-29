"""微信支付 Native(扫码支付),APIv3:下单拿 `code_url`、按商户订单号查单、支付通知验签与解密。

规则照微信支付 APIv3 文档(https://pay.weixin.qq.com/doc/v3/merchant/4012365334):

- **请求签名**:`HTTP方法\\nURL(路径+查询)\\n时间戳\\n随机串\\n请求体\\n` 用**商户私钥** SHA256withRSA 签,放进
  `Authorization: WECHATPAY2-SHA256-RSA2048 mchid=…,nonce_str=…,signature=…,timestamp=…,serial_no=<商户证书序列号>`;
- **应答与通知验签**:`时间戳\\n随机串\\n应答 / 通知原文\\n` 用**微信支付公钥**验 `Wechatpay-Signature`;`Wechatpay-Serial`
  必须是我们配的那把公钥的 id。时间戳离现在超过 5 分钟的通知拒收(防重放);
- **通知解密**:`resource` 用 APIv3 密钥 AEAD_AES_256_GCM 解出交易,再核对 `mchid` / `appid` 是我们的。

查单的应答也验签 —— 主动查单是「发放」的依据之一,和回调一样不能信一个没验过的回包。
"""

from __future__ import annotations

import base64
import json
import secrets
import time
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

import httpx2
from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from cloud.payments.base import ChannelUnavailable, NotifyAck, NotifyRejected, PaidNotice, QrPayment

PROD_BASE = "https://api.mch.weixin.qq.com"
TIMEOUT_SECONDS = 15.0
#: 通知里的时间戳和现在差多少以内才收。
NOTIFY_FRESHNESS = timedelta(minutes=5)
BEIJING = timezone(timedelta(hours=8))


def _rfc3339(moment: datetime) -> str:
    """朴素 UTC → 微信要的 `2026-10-29T18:00:00+08:00`。"""
    return moment.replace(tzinfo=timezone.utc).astimezone(BEIJING).isoformat(timespec="seconds")


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(timezone.utc).replace(tzinfo=None)


class WechatPayChannel:
    name = "wechat"

    def __init__(
        self,
        *,
        mchid: str,
        appid: str,
        merchant_serial_no: str,
        merchant_private_key: bytes,
        apiv3_key: str,
        platform_public_key: bytes,
        platform_public_key_id: str,
        notify_url: str,
        base_url: str = PROD_BASE,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        private = serialization.load_pem_private_key(merchant_private_key, password=None)
        public = serialization.load_pem_public_key(platform_public_key)
        if not isinstance(private, rsa.RSAPrivateKey) or not isinstance(public, rsa.RSAPublicKey):
            raise ValueError("WeChat Pay keys must be RSA")
        if len(apiv3_key.encode("utf-8")) != 32:
            raise ValueError("WeChat Pay APIv3 key must be 32 bytes")
        self.mchid = mchid
        self.appid = appid
        self.serial_no = merchant_serial_no
        self._private = private
        self._public = public
        self._aes = AESGCM(apiv3_key.encode("utf-8"))
        self.public_key_id = platform_public_key_id
        self.notify_url = notify_url
        self.base_url = base_url.rstrip("/")
        self._transport = transport

    # ------------------------------------------------------------ 签名与验签

    def _authorization(self, method: str, url: str, body: str) -> str:
        split = urlsplit(url)
        path = split.path + (f"?{split.query}" if split.query else "")
        timestamp, nonce = str(int(time.time())), secrets.token_hex(16)
        message = f"{method}\n{path}\n{timestamp}\n{nonce}\n{body}\n"
        signature = base64.b64encode(self._private.sign(message.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())).decode()
        return (
            f'WECHATPAY2-SHA256-RSA2048 mchid="{self.mchid}",nonce_str="{nonce}",signature="{signature}",'
            f'timestamp="{timestamp}",serial_no="{self.serial_no}"'
        )

    def _verified(self, headers: Mapping[str, str], body: bytes) -> bool:
        lower = {key.lower(): value for key, value in headers.items()}
        timestamp, nonce = lower.get("wechatpay-timestamp", ""), lower.get("wechatpay-nonce", "")
        signature, serial = lower.get("wechatpay-signature", ""), lower.get("wechatpay-serial", "")
        if not (timestamp and nonce and signature) or serial != self.public_key_id:
            return False
        message = f"{timestamp}\n{nonce}\n".encode() + body + b"\n"
        try:
            self._public.verify(base64.b64decode(signature), message, padding.PKCS1v15(), hashes.SHA256())
        except (InvalidSignature, ValueError):
            return False
        return True

    # ------------------------------------------------------------ 调用

    def _request(self, method: str, path: str, payload: dict[str, object] | None = None) -> tuple[int, dict[str, object]]:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) if payload is not None else ""
        headers = {
            "Authorization": self._authorization(method, url, body),
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Wechatpay-Serial": self.public_key_id,
        }
        try:
            with httpx2.Client(transport=self._transport, timeout=TIMEOUT_SECONDS) as client:
                response = client.request(method, url, content=body.encode("utf-8") if body else None, headers=headers)
        except httpx2.HTTPError as exc:
            raise ChannelUnavailable(f"wechat {path}: {type(exc).__name__}") from exc
        if not self._verified(response.headers, response.content):
            raise ChannelUnavailable(f"wechat {path}: response signature did not verify")
        try:
            data = response.json() if response.content else {}
        except ValueError as exc:
            raise ChannelUnavailable(f"wechat {path}: not JSON") from exc
        return response.status_code, data if isinstance(data, dict) else {}

    def create_qr(self, *, order_id: str, amount_cents: int, subject: str, expires_at: datetime) -> QrPayment:
        status, data = self._request("POST", "/v3/pay/transactions/native", {
            "appid": self.appid,
            "mchid": self.mchid,
            "description": subject,
            "out_trade_no": order_id,
            "time_expire": _rfc3339(expires_at),
            "notify_url": self.notify_url,
            "amount": {"total": amount_cents, "currency": "CNY"},
        })
        code = data.get("code_url")
        if status != 200 or not isinstance(code, str) or not code:
            raise ChannelUnavailable(f"wechat native: {status} {data.get('code')} {data.get('message')}")
        return QrPayment(code_url=code)

    def query(self, order_id: str) -> PaidNotice | None:
        status, data = self._request(
            "GET", f"/v3/pay/transactions/out-trade-no/{quote(order_id, safe='')}?mchid={quote(self.mchid, safe='')}"
        )
        if status == 404:
            return None
        if status != 200:
            raise ChannelUnavailable(f"wechat query: {status} {data.get('code')}")
        return self._paid(data, order_id)

    # ------------------------------------------------------------ 支付通知

    def parse_notify(self, *, headers: Mapping[str, str], body: bytes, at: datetime) -> PaidNotice | None:
        if not self._verified(headers, body):
            raise NotifyRejected("wechat notify: signature did not verify")
        lower = {key.lower(): value for key, value in headers.items()}
        try:
            sent = datetime.fromtimestamp(int(lower["wechatpay-timestamp"]), tz=timezone.utc).replace(tzinfo=None)
        except (KeyError, ValueError) as exc:
            raise NotifyRejected("wechat notify: bad timestamp") from exc
        if abs(at - sent) > NOTIFY_FRESHNESS:
            raise NotifyRejected("wechat notify: stale timestamp")
        try:
            resource = json.loads(body)["resource"]
            plain = self._aes.decrypt(
                #: 微信的 nonce 就是一串明文(12 个字符),原样当字节用;密文与附加数据各自按文档处理。
                resource["nonce"].encode("utf-8"),
                base64.b64decode(resource["ciphertext"]),
                (resource.get("associated_data") or "").encode("utf-8"),
            )
            transaction = json.loads(plain)
        except (KeyError, ValueError, TypeError, InvalidTag) as exc:
            raise NotifyRejected(f"wechat notify: cannot decrypt ({type(exc).__name__})") from exc
        if transaction.get("mchid") != self.mchid or transaction.get("appid") != self.appid:
            raise NotifyRejected("wechat notify: not our merchant")
        return self._paid(transaction, None)

    def _paid(self, transaction: Mapping[str, object], order_id: str | None) -> PaidNotice | None:
        if transaction.get("trade_state") != "SUCCESS":
            return None
        amount = transaction.get("amount")
        total = amount.get("total") if isinstance(amount, dict) else None
        if not isinstance(total, int):
            raise NotifyRejected("wechat: transaction without amount.total")
        success = transaction.get("success_time")
        return PaidNotice(
            order_id=str(transaction.get("out_trade_no") or order_id or ""),
            channel_trade_no=str(transaction.get("transaction_id") or ""),
            amount_cents=total,
            paid_at=_utc(success) if isinstance(success, str) and success else datetime.now(timezone.utc).replace(tzinfo=None),
        )

    def ack(self, ok: bool) -> NotifyAck:
        """收到了回 204、不带报文;没收下回 4xx + `{"code":"FAIL"}`,微信会按退避重发。"""
        if ok:
            return NotifyAck(204, b"", "application/json")
        return NotifyAck(400, b'{"code":"FAIL","message":"rejected"}', "application/json")
