"""上游通道 API Key 的落库加密:Fernet(`cryptography` 的成熟实现),钥匙是部署配置里的 `CLOUD_CHANNEL_KEY`。

Key 只在两处出现原文:加通道的那条命令(从环境变量或终端读,不进命令行参数),和网关向上游发请求的那一刻。
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from cloud.config import CloudConfig
from cloud.errors import CloudError


def new_channel_key() -> str:
    """生成一把新的 `CLOUD_CHANNEL_KEY`。换钥匙等于所有通道要重新加一遍 Key —— 不做轮换,第一版用不上。"""
    return Fernet.generate_key().decode("ascii")


def _fernet(config: CloudConfig) -> Fernet:
    if not config.channel_key:
        raise CloudError(503, "gateway_not_configured")
    return Fernet(config.channel_key.encode("ascii"))


def seal(config: CloudConfig, api_key: str) -> str:
    return _fernet(config).encrypt(api_key.encode("utf-8")).decode("ascii")


def unseal(config: CloudConfig, sealed: str) -> str:
    """解不开(钥匙换过、库被改过)当作网关没配好:说「没配置」,不把一个坏 Key 发给上游。"""
    try:
        return _fernet(config).decrypt(sealed.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise CloudError(503, "gateway_not_configured") from exc
