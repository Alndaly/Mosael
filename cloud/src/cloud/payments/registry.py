"""按部署配置组装可用的支付渠道:配齐了商户凭据的才开,一个都没配就是「这个部署还没开在线购买」。"""

from __future__ import annotations

from cloud.config import API_PREFIX, CloudConfig
from cloud.payments.alipay import AlipayChannel
from cloud.payments.base import PaymentChannel, pem
from cloud.payments.wechat import WechatPayChannel


def notify_url(config: CloudConfig, channel: str) -> str:
    """渠道回调打到哪:`<public_url>/api/cloud/v1/payments/<渠道>/notify`。必须是公网可达的 https(由部署保证)。"""
    return f"{config.public_url}{API_PREFIX}/payments/{channel}/notify"


def channels_from_config(config: CloudConfig) -> dict[str, PaymentChannel]:
    channels: dict[str, PaymentChannel] = {}
    if config.alipay_app_id and config.alipay_private_key and config.alipay_public_key:
        channels["alipay"] = AlipayChannel(
            app_id=config.alipay_app_id,
            app_private_key=pem(config.alipay_private_key),
            alipay_public_key=pem(config.alipay_public_key),
            notify_url=notify_url(config, "alipay"),
            gateway=config.alipay_gateway,
        )
    if all((config.wechatpay_mchid, config.wechatpay_appid, config.wechatpay_serial_no, config.wechatpay_private_key,
            config.wechatpay_apiv3_key, config.wechatpay_public_key, config.wechatpay_public_key_id)):
        channels["wechat"] = WechatPayChannel(
            mchid=config.wechatpay_mchid,
            appid=config.wechatpay_appid,
            merchant_serial_no=config.wechatpay_serial_no,
            merchant_private_key=pem(config.wechatpay_private_key),
            apiv3_key=config.wechatpay_apiv3_key,
            platform_public_key=pem(config.wechatpay_public_key),
            platform_public_key_id=config.wechatpay_public_key_id,
            notify_url=notify_url(config, "wechat"),
        )
    return channels
