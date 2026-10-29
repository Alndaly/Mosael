"""支付渠道的公共形状。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class QrPayment:
    """渠道给的二维码内容(支付宝 `qr_code` / 微信 `code_url`),界面把它画成码让人扫。"""

    code_url: str


@dataclass(frozen=True)
class PaidNotice:
    """渠道说「这一笔付了」(回调或查单),**已经验过签**。金额是渠道说的数,和订单对不对得上由订单那一层判。"""

    order_id: str
    channel_trade_no: str
    amount_cents: int
    paid_at: datetime


class NotifyRejected(Exception):
    """回调认不出是渠道发的(验签不过、时间戳太旧、商户号不对)。回给渠道一个失败,它会重发;**不发放**。"""


class ChannelUnavailable(Exception):
    """和渠道说话没成(连不上、超时、它回了业务错误)。下单时说「这个支付方式暂时用不了」,查单时就当还没付。"""


@dataclass(frozen=True)
class NotifyAck:
    """回给渠道的那句「收到了」/「没收到」。各家要的形状不同(支付宝是纯文本 success,微信是 HTTP 状态码)。"""

    status_code: int
    body: bytes
    media_type: str


class PaymentChannel(Protocol):
    #: `alipay` / `wechat`,和 `cloud_orders.channel` 一致。
    name: str

    def create_qr(self, *, order_id: str, amount_cents: int, subject: str, expires_at: datetime) -> QrPayment: ...

    def parse_notify(self, *, headers: Mapping[str, str], body: bytes, at: datetime) -> PaidNotice | None:
        """验签并读出这一条回调。是渠道发的、但不是「付成了」(等待付款、关闭)回 None;认不出抛 `NotifyRejected`。"""
        ...

    def query(self, order_id: str) -> PaidNotice | None:
        """主动问渠道这一笔付了没有(兜住丢了的回调)。没付回 None;问不到抛 `ChannelUnavailable`。"""
        ...

    def ack(self, ok: bool) -> NotifyAck: ...


def pem(value: str) -> bytes:
    """配置里的密钥:直接是 PEM 内容,或者一个 PEM 文件的路径(部署时常把证书挂成文件)。"""
    text = value.strip()
    if text.startswith("-----BEGIN"):
        return text.encode("ascii")
    return Path(text).expanduser().read_bytes()


def cents_from_yuan(text: str) -> int:
    """`"12.30"` → 1230。渠道报的金额是字符串,不过浮点。"""
    whole, _, frac = text.strip().partition(".")
    if not whole.isdigit() or (frac and not frac.isdigit()) or len(frac) > 2:
        raise ValueError(f"not a CNY amount: {text!r}")
    return int(whole) * 100 + int((frac + "00")[:2])


def yuan(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"
