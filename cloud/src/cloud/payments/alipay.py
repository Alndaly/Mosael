"""支付宝当面付(扫码支付):`alipay.trade.precreate` 拿二维码、`alipay.trade.query` 查单、异步通知验签。

签名照支付宝开放平台的 RSA2 规则(https://opendocs.alipay.com/common/02kf5q):

- **请求**:除 `sign` 外所有非空参数按键名升序拼成 `k=v&k=v`,用**应用私钥** SHA256withRSA 签名,base64;
- **同步响应**:签的是原始 JSON 里 `<method>_response` 那个节点的**原文子串**(不是解析后再序列化的),用**支付宝公钥**验;
- **异步通知**:表单参数去掉 `sign`、`sign_type` 后同样排序拼串,用支付宝公钥验;再核对 `app_id` 是我们的。

时间一律北京时间(支付宝的 `timestamp`、`time_expire`、`gmt_payment` 都是)。
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl

import httpx2
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from cloud.payments.base import (
    ChannelUnavailable,
    NotifyAck,
    NotifyRejected,
    PaidNotice,
    QrPayment,
    cents_from_yuan,
    yuan,
)

BEIJING = timezone(timedelta(hours=8))
PROD_GATEWAY = "https://openapi.alipay.com/gateway.do"
TIMEOUT_SECONDS = 15.0
#: 「付成了」的两种交易状态:TRADE_SUCCESS(可退款)、TRADE_FINISHED(不可退款)。
PAID_STATES = frozenset({"TRADE_SUCCESS", "TRADE_FINISHED"})


def sign_content(params: Mapping[str, str]) -> str:
    return "&".join(f"{key}={params[key]}" for key in sorted(params) if params[key] not in ("", None))


def _beijing(moment: datetime) -> str:
    """朴素 UTC → 北京时间字符串 `yyyy-MM-dd HH:mm:ss`。"""
    return moment.replace(tzinfo=timezone.utc).astimezone(BEIJING).strftime("%Y-%m-%d %H:%M:%S")


def _utc(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=BEIJING).astimezone(timezone.utc).replace(tzinfo=None)


class AlipayChannel:
    name = "alipay"

    def __init__(
        self,
        *,
        app_id: str,
        app_private_key: bytes,
        alipay_public_key: bytes,
        notify_url: str,
        gateway: str = PROD_GATEWAY,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self.app_id = app_id
        private = serialization.load_pem_private_key(app_private_key, password=None)
        public = serialization.load_pem_public_key(alipay_public_key)
        if not isinstance(private, rsa.RSAPrivateKey) or not isinstance(public, rsa.RSAPublicKey):
            raise ValueError("Alipay keys must be RSA (RSA2)")
        self._private = private
        self._public = public
        self.notify_url = notify_url
        self.gateway = gateway
        self._transport = transport

    # ------------------------------------------------------------ 签名与验签

    def _sign(self, content: str) -> str:
        return base64.b64encode(self._private.sign(content.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())).decode()

    def _verify(self, content: str, signature: str) -> bool:
        try:
            self._public.verify(base64.b64decode(signature), content.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
        except (InvalidSignature, ValueError):
            return False
        return True

    # ------------------------------------------------------------ 调用

    def _call(self, method: str, biz: dict[str, object], *, with_notify: bool = False) -> dict[str, object]:
        """调一个开放接口,验过同步响应的签名,交回 `<method>_response` 那个节点。业务失败(code ≠ 10000)抛 ChannelUnavailable。"""
        params = {
            "app_id": self.app_id,
            "method": method,
            "format": "JSON",
            "charset": "utf-8",
            "sign_type": "RSA2",
            "timestamp": _beijing(datetime.now(timezone.utc).replace(tzinfo=None)),
            "version": "1.0",
            "biz_content": json.dumps(biz, ensure_ascii=False, separators=(",", ":")),
        }
        if with_notify:
            params["notify_url"] = self.notify_url
        params["sign"] = self._sign(sign_content(params))
        try:
            with httpx2.Client(transport=self._transport, timeout=TIMEOUT_SECONDS) as client:
                response = client.post(self.gateway, data=params)
        except httpx2.HTTPError as exc:
            raise ChannelUnavailable(f"alipay {method}: {type(exc).__name__}") from exc
        raw = response.text
        node_key = method.replace(".", "_") + "_response"
        node_text = _raw_node(raw, node_key)
        try:
            whole = json.loads(raw)
        except ValueError as exc:
            raise ChannelUnavailable(f"alipay {method}: not JSON") from exc
        signature = whole.get("sign") if isinstance(whole, dict) else None
        if node_text is None or not isinstance(signature, str) or not self._verify(node_text, signature):
            raise ChannelUnavailable(f"alipay {method}: response signature did not verify")
        node = json.loads(node_text)
        if node.get("code") != "10000":
            raise ChannelUnavailable(f"alipay {method}: {node.get('sub_code') or node.get('code')} {node.get('sub_msg') or node.get('msg')}")
        return node

    def create_qr(self, *, order_id: str, amount_cents: int, subject: str, expires_at: datetime) -> QrPayment:
        node = self._call(
            "alipay.trade.precreate",
            {"out_trade_no": order_id, "total_amount": yuan(amount_cents), "subject": subject,
             "time_expire": _beijing(expires_at)},
            with_notify=True,
        )
        code = node.get("qr_code")
        if not isinstance(code, str) or not code:
            raise ChannelUnavailable("alipay precreate: no qr_code")
        return QrPayment(code_url=code)

    def query(self, order_id: str) -> PaidNotice | None:
        try:
            node = self._call("alipay.trade.query", {"out_trade_no": order_id})
        except ChannelUnavailable as exc:
            # 用户还没扫码时支付宝那边没有这笔交易(ACQ.TRADE_NOT_EXIST):就是「还没付」。
            if "TRADE_NOT_EXIST" in str(exc):
                return None
            raise
        if node.get("trade_status") not in PAID_STATES:
            return None
        return PaidNotice(
            order_id=str(node.get("out_trade_no") or order_id),
            channel_trade_no=str(node.get("trade_no") or ""),
            amount_cents=cents_from_yuan(str(node.get("total_amount") or "0")),
            paid_at=_utc(str(node["send_pay_date"])) if node.get("send_pay_date") else datetime.now(timezone.utc).replace(tzinfo=None),
        )

    # ------------------------------------------------------------ 异步通知

    def parse_notify(self, *, headers: Mapping[str, str], body: bytes, at: datetime) -> PaidNotice | None:
        params = dict(parse_qsl(body.decode("utf-8"), keep_blank_values=True))
        signature = params.pop("sign", "")
        params.pop("sign_type", None)
        if not signature or not self._verify(sign_content(params), signature):
            raise NotifyRejected("alipay notify: signature did not verify")
        if params.get("app_id") != self.app_id:
            raise NotifyRejected("alipay notify: not our app_id")
        if params.get("trade_status") not in PAID_STATES:
            return None
        try:
            return PaidNotice(
                order_id=params["out_trade_no"],
                channel_trade_no=params.get("trade_no", ""),
                amount_cents=cents_from_yuan(params["total_amount"]),
                paid_at=_utc(params["gmt_payment"]) if params.get("gmt_payment") else at,
            )
        except (KeyError, ValueError) as exc:
            raise NotifyRejected(f"alipay notify: malformed ({exc})") from exc

    def ack(self, ok: bool) -> NotifyAck:
        """支付宝要的是纯文本 `success`;别的(含 `fail`)它都会按退避重发,直到 24 小时。"""
        return NotifyAck(200, b"success" if ok else b"fail", "text/plain")


def _raw_node(raw: str, key: str) -> str | None:
    """响应原文里 `"<key>":` 后面那个 JSON 值的**原文**。签名签的就是这一段字节,解析后再序列化会对不上。"""
    marker = f'"{key}"'
    at = raw.find(marker)
    if at < 0:
        return None
    colon = raw.find(":", at + len(marker))
    if colon < 0:
        return None
    start = colon + 1
    while start < len(raw) and raw[start] in " \t\r\n":
        start += 1
    try:
        _value, end = json.JSONDecoder().raw_decode(raw, start)
    except ValueError:
        return None
    return raw[start:end]
