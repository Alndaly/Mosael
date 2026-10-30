"""腾讯云短信:把 6 位登录验证码发到手机。

用官方 Python SDK 的 `sms.v20210111` 客户端,签名/重试/协议细节交给腾讯云维护。没有配置时
明确抛 `sms_not_configured`,与邮件同一原则:不假装发出。测试注入假的 PhoneCodeSender,
不访问外网。
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from cloud.config import CloudConfig
from cloud.errors import CloudError
from cloud.phone import mask_phone

logger = logging.getLogger(__name__)


class PhoneCodeSender(Protocol):
    def ensure_ready(self) -> None: ...
    def send_code(self, *, phone: str, purpose: str, code: str) -> None: ...


class TencentSmsSender:
    def __init__(self, config: CloudConfig, *, client: Any | None = None) -> None:
        self.config = config
        self._client = client

    def ensure_ready(self) -> None:
        if not self.config.sms_configured:
            raise CloudError(503, "sms_not_configured")

    def _client_or_build(self):
        if self._client is not None:
            return self._client
        from tencentcloud.common import credential
        from tencentcloud.common.profile.client_profile import ClientProfile
        from tencentcloud.common.profile.http_profile import HttpProfile
        from tencentcloud.sms.v20210111 import sms_client

        profile = ClientProfile()
        http = HttpProfile()
        http.endpoint = "sms.tencentcloudapi.com"
        profile.httpProfile = http
        self._client = sms_client.SmsClient(
            credential.Credential(
                self.config.tencent_sms_secret_id,
                self.config.tencent_sms_secret_key,
            ),
            self.config.tencent_sms_region,
            profile,
        )
        return self._client

    def send_code(self, *, phone: str, purpose: str, code: str) -> None:
        self.ensure_ready()
        from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
        from tencentcloud.sms.v20210111 import models

        request = models.SendSmsRequest()
        request.SmsSdkAppId = self.config.tencent_sms_sdk_app_id
        request.SignName = self.config.tencent_sms_sign_name
        request.TemplateId = self.config.tencent_sms_template_id
        request.PhoneNumberSet = [phone]
        #: 模板正文由部署方在腾讯云控制台配;参数个数必须与模板完全一致。
        #: 当前模板只有 {1}=验证码,多发一个分钟数会被腾讯判成内容不匹配。
        request.TemplateParamSet = [code]
        try:
            response = self._client_or_build().SendSms(request)
        except TencentCloudSDKException as exc:
            logger.warning("Tencent SMS send failed for %s: %s", mask_phone(phone), exc)
            raise CloudError(502, "sms_send_failed") from exc
        statuses = getattr(response, "SendStatusSet", None) or []
        if not statuses or getattr(statuses[0], "Code", "") != "Ok":
            reason = getattr(statuses[0], "Message", "empty SendStatusSet") if statuses else "empty SendStatusSet"
            provider_code = getattr(statuses[0], "Code", "") if statuses else ""
            logger.warning(
                "Tencent SMS rejected %s (%s): %s", mask_phone(phone), provider_code, reason
            )
            lowered = reason.lower()
            if "DailyLimit" in provider_code or "every day" in lowered or "每日" in reason:
                raise CloudError(429, "sms_daily_limit")
            if "LimitExceeded" in provider_code:
                raise CloudError(429, "sms_rate_limited")
            raise CloudError(502, "sms_send_failed")
        logger.info("sent %s sms code to %s", purpose, mask_phone(phone))
