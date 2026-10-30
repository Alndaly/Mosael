"""腾讯云短信发送器:配置门槛、请求字段、腾讯拒绝时不假装成功。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cloud.config import CloudConfig
from cloud.errors import CloudError
from cloud.sms import TencentSmsSender


def configured(tmp_path):
    return CloudConfig(
        data_dir=tmp_path,
        public_url="https://mosael.test",
        cookie_secure=False,
        tencent_sms_secret_id="id",
        tencent_sms_secret_key="key",
        tencent_sms_sdk_app_id="1400000000",
        tencent_sms_sign_name="Mosael",
        tencent_sms_template_id="123456",
    )


class FakeClient:
    def __init__(self, status="Ok"):
        self.requests = []
        self.status = status

    def SendSms(self, request):
        self.requests.append(request)
        return SimpleNamespace(SendStatusSet=[SimpleNamespace(Code=self.status, Message="x")])


def test_unconfigured_sms_is_an_explicit_503(tmp_path):
    sender = TencentSmsSender(CloudConfig(data_dir=tmp_path))
    with pytest.raises(CloudError) as raised:
        sender.ensure_ready()
    assert raised.value.code == "sms_not_configured"


def test_sends_only_the_code_because_the_template_has_one_parameter(tmp_path):
    client = FakeClient()
    sender = TencentSmsSender(configured(tmp_path), client=client)
    sender.send_code(phone="+8613800138000", purpose="login", code="123456")
    request = client.requests[0]
    assert request.PhoneNumberSet == ["+8613800138000"]
    assert request.TemplateParamSet == ["123456"]
    assert request.SmsSdkAppId == "1400000000"
    assert request.SignName == "Mosael"
    assert request.TemplateId == "123456"


def test_tencent_rejection_is_a_send_failure(tmp_path):
    sender = TencentSmsSender(configured(tmp_path), client=FakeClient(status="LimitExceeded.PhoneNumberDailyLimit"))
    with pytest.raises(CloudError) as raised:
        sender.send_code(phone="+8613800138000", purpose="login", code="123456")
    assert raised.value.code == "sms_send_failed"
