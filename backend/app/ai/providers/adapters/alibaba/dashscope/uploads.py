"""百炼自己的临时存储:把一个本地文件交给只收地址的接口。

取上传凭证 → 表单直传 OSS → 得到 `oss://…`(凭证 5 分钟有效、文件 48 小时有效、**只绑取凭证时点名的那个模型**),
提交时带上 `X-DashScope-OssResourceResolve: enable`。不借用户的对象存储 —— 要求先配好对象存储才能让人物说话、才能
复刻一把嗓子,门槛就太高了。

两处在用:数字人(`digital_human`,按生成模型取凭证)和声音复刻(`voice_enrollment`,按 `voice-enrollment` 取凭证,
2026-10-05 真机验过)。
"""

from __future__ import annotations

from pathlib import Path

from app.core.http_retry import RetryingClient
from app.core.i18n import LocalizedError

UPLOAD_POLICY_PATH = "/api/v1/uploads"
#: 用 `oss://` 临时地址提交时必须带的头(文档原话:「必须在 HTTP 请求头中显式添加」)。
OSS_RESOLVE_HEADER = {"X-DashScope-OssResourceResolve": "enable"}


class TemporaryUploadError(LocalizedError, RuntimeError):
    """取不到上传凭证(回包里没有上传地址或目录)。调用方转述成自己那一类错误(`relay`)。"""


def upload_temporary(client: RetryingClient, model: str, path: Path) -> str:
    """把一个本地文件传到百炼的临时存储,交回 `oss://…`。

    `client` 是带着 Authorization 的那个(取凭证要它);直传 OSS **不带** Authorization —— 签名在 policy 里,
    带上反而走另一条校验分支。
    """
    policy_response = client.get(UPLOAD_POLICY_PATH, params={"action": "getPolicy", "model": model})
    policy_response.raise_for_status()
    policy = (policy_response.json() or {}).get("data") or {}
    host = str(policy.get("upload_host") or "")
    upload_dir = str(policy.get("upload_dir") or "").rstrip("/")
    if not host or not upload_dir:
        raise TemporaryUploadError("providerErr_uploadPolicyMissing", vendor="DashScope")
    key = f"{upload_dir}/{path.name}"
    #: 表单字段照文档的顺序,`file` 必须在最后。
    form = {
        "OSSAccessKeyId": str(policy.get("oss_access_key_id") or ""),
        "Signature": str(policy.get("signature") or ""),
        "policy": str(policy.get("policy") or ""),
        "x-oss-object-acl": str(policy.get("x_oss_object_acl") or "private"),
        "x-oss-forbid-overwrite": str(policy.get("x_oss_forbid_overwrite") or "true"),
        "key": key,
        "success_action_status": "200",
    }
    #: 直传地址是百炼回给我们的(和成片下载同一类);一次就好 —— 文件句柄传过一遍就读完了,重发不了。
    with path.open("rb") as handle, RetryingClient(timeout=300, max_retries=0) as uploader:
        uploaded = uploader.post(host, data=form, files={"file": (path.name, handle)})
    uploaded.raise_for_status()
    return f"oss://{key}"


__all__ = ["OSS_RESOLVE_HEADER", "UPLOAD_POLICY_PATH", "TemporaryUploadError", "upload_temporary"]
