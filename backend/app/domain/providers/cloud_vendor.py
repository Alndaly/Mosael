"""MosaelCloud 官方中转作为一条连接时,vendor 怎么写、端点在哪(ADR 0088)。

和 `plugin_vendor` 同一个理由住在这里:供应商的凭据解析(要认出它、给它端点)、连接列表、云端登录三处都要用,
放在供应商包最底下,谁都能引而不成环。它**不在预设表里** —— 不能在「添加供应商」里自己建,只由云端登录建出来。
"""

from __future__ import annotations

from app.core.config import settings

VENDOR = "mosael-cloud"
#: 连接的名字。只有一条,不让改。
CONNECTION_NAME = "Mosael Cloud"
#: 这条连接的鉴权方式:钥匙是云端登录换来的设备令牌,不由用户填。
AUTH_TYPE = "mosael_cloud"
#: 网关报的价是积分。用量账本按币种各算各的,积分是单独的一种,不和人民币、美元相加。
CREDITS = "CREDITS"


def is_cloud(vendor: str) -> bool:
    return vendor == VENDOR


def gateway_base_url() -> str:
    """网关的 OpenAI 兼容端点:`<cloud_url>/gateway/v1`。跟着部署配置走,不存进连接 —— 换了 Cloud 地址不用改连接。"""
    base = settings.cloud_url.strip().rstrip("/")
    return f"{base}/gateway/v1" if base else ""
