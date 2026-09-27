"""阿里云百炼的数字人(ADR 0028):`wan2.2-s2v`(说话照片)和 `videoretalk`(改口型)。

和万相视频是**同一套异步任务协议**(提交拿 task_id → 轮询 `/api/v1/tasks/{id}` → 下载预签名地址),所以轮询、
取地址、下载都走 `video.py` 那一份;这里只多三件它俩自己的事:

· **提交路径不同**:两个都走 `image2video/video-synthesis`,不是万相的 `video-generation/video-synthesis`。
· **素材是链接字段**(`image_url` / `audio_url` / `video_url`),不收内联的 base64。本地素材先传到**百炼自己的临时存储**
  (取上传凭证 → 表单直传 OSS → 得到 `oss://…`,48 小时有效,只对这一个模型有效),提交时带上
  `X-DashScope-OssResourceResolve: enable`。不借用户的对象存储 —— 配音生成的音频都是本地文件,要求先配好对象存储
  才能让人物说话,门槛就太高了。有公网直链的素材(从链接导入的)直接用直链。
· **说话照片先预检**:`wan2.2-s2v-detect` 同步判一张图能不能用(清晰、单人、正面),不过就不提交,说「没找到清晰的正脸」。
  预检只要请求成功就计费(文档原话),所以只在真要提交之前调一次。

接口形状照 2026-09-26 读到的官方文档写,**还没拿真实密钥跑到终态**(ADR 0028 §3):第一次真跑时以接口自己的报错校准。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.ai.providers.contracts.generation import (
    DRIVING_AUDIO,
    FIRST_FRAME,
    REFERENCE_IMAGE,
    SOURCE_VIDEO,
    GenerationAdapterError,
    GenerationRequest,
    source_url_values,
)
from app.core.http_retry import RetryingClient

SUBMIT_PATH = "/api/v1/services/aigc/image2video/video-synthesis"
DETECT_PATH = "/api/v1/services/aigc/image2video/face-detect"
UPLOAD_POLICY_PATH = "/api/v1/uploads"
#: 用 `oss://` 临时地址提交时必须带的头(文档原话:「必须在 HTTP 请求头中显式添加」)。
OSS_RESOLVE_HEADER = {"X-DashScope-OssResourceResolve": "enable"}

S2V_MODEL_PREFIX = "wan2.2-s2v"
S2V_DETECT_MODEL = "wan2.2-s2v-detect"
RETALK_MODEL = "videoretalk"


def is_talking_model(model: str) -> bool:
    """这个模型是不是走这条路(说话照片 / 改口型)。"""
    name = str(model or "").strip().lower()
    return (name.startswith(S2V_MODEL_PREFIX) and name != S2V_DETECT_MODEL) or name == RETALK_MODEL


def _local_or_url(request: GenerationRequest, role: str) -> tuple[str, Path | None]:
    """这个角色的第一份素材:(公网直链, 本地文件)。有直链就用直链;都没有返回 ("", None)。"""
    urls = source_url_values(request.parameters, role, request.kind)
    if urls:
        return str(urls[0]), None
    for item in request.sources:
        if item.role == role:
            return (item.public_url or "", None if item.public_url else item.path)
    return "", None


def upload_temporary(client: RetryingClient, model: str, path: Path) -> str:
    """把一个本地文件传到百炼的临时存储,交回 `oss://…`。凭证 5 分钟有效、文件 48 小时有效、只绑这个模型。"""
    policy_response = client.get(UPLOAD_POLICY_PATH, params={"action": "getPolicy", "model": model})
    policy_response.raise_for_status()
    policy = (policy_response.json() or {}).get("data") or {}
    host = str(policy.get("upload_host") or "")
    upload_dir = str(policy.get("upload_dir") or "").rstrip("/")
    if not host or not upload_dir:
        raise GenerationAdapterError("providerErr_uploadPolicyMissing", vendor="DashScope")
    key = f"{upload_dir}/{path.name}"
    #: 表单字段照文档的顺序,`file` 必须在最后。直传 OSS **不带** Authorization —— 签名在 policy 里。
    form = {
        "OSSAccessKeyId": str(policy.get("oss_access_key_id") or ""),
        "Signature": str(policy.get("signature") or ""),
        "policy": str(policy.get("policy") or ""),
        "x-oss-object-acl": str(policy.get("x_oss_object_acl") or "private"),
        "x-oss-forbid-overwrite": str(policy.get("x_oss_forbid_overwrite") or "true"),
        "key": key,
        "success_action_status": "200",
    }
    with path.open("rb") as handle:
        uploaded = httpx.post(host, data=form, files={"file": (path.name, handle)}, timeout=300)
    uploaded.raise_for_status()
    return f"oss://{key}"


def _input_url(client: RetryingClient, request: GenerationRequest, role: str, *, required: bool = True) -> str:
    url, local = _local_or_url(request, role)
    if url:
        return url
    if local is not None:
        return upload_temporary(client, request.model, local)
    if required:
        raise GenerationAdapterError("providerErr_sourceMissing", vendor="DashScope", role=role)
    return ""


def check_portrait(client: RetryingClient, image_url: str) -> None:
    """说话照片之前的预检:图里要有一张清晰、正面的人脸。不过就说人话,不提交。"""
    response = client.post(
        DETECT_PATH,
        json={"model": S2V_DETECT_MODEL, "input": {"image_url": image_url}},
        headers=OSS_RESOLVE_HEADER,
    )
    response.raise_for_status()
    output = (response.json() or {}).get("output") or {}
    if not output.get("check_pass"):
        detail = str(output.get("message") or output.get("code") or "").strip()
        raise GenerationAdapterError("providerErr_noUsableFace", vendor="DashScope", detail=detail)


def build_talking_payload(client: RetryingClient, request: GenerationRequest) -> dict[str, Any]:
    """说话照片:人像(首帧)+ 驱动音频;改口型:源视频 + 驱动音频(+ 可选的一张参考人像,指定改哪张脸)。"""
    audio = _input_url(client, request, DRIVING_AUDIO)
    provider_options: dict[str, Any] = {}
    if str(request.model).lower() == RETALK_MODEL:
        payload_input: dict[str, Any] = {"video_url": _input_url(client, request, SOURCE_VIDEO), "audio_url": audio}
        face = _input_url(client, request, REFERENCE_IMAGE, required=False)
        if face:
            payload_input["ref_image_url"] = face
        #: 音频比视频长时,用正放、倒放交替把视频补到音频那么长 —— 不开的话后半段话没有画面。总是开:
        #: 没有哪种情况是「想让后半段话没有画面」,不值得多一个让人选的参数。
        provider_options["video_extension"] = True
    else:
        image = _input_url(client, request, FIRST_FRAME)
        check_portrait(client, image)
        payload_input = {"image_url": image, "audio_url": audio}
        resolution = str(request.parameters.get("resolution") or "").strip()
        if resolution:
            provider_options["resolution"] = resolution.upper()
    payload: dict[str, Any] = {"model": request.model, "input": payload_input}
    if provider_options:
        payload["parameters"] = provider_options
    return payload


def submit_talking(client: RetryingClient, request: GenerationRequest) -> str:
    """提交,交回任务号。"""
    response = client.post(SUBMIT_PATH, json=build_talking_payload(client, request), headers=OSS_RESOLVE_HEADER)
    response.raise_for_status()
    task_id = ((response.json() or {}).get("output") or {}).get("task_id") or ""
    if not task_id:
        raise GenerationAdapterError("providerErr_noTaskId", vendor="DashScope")
    return str(task_id)


__all__ = ["build_talking_payload", "check_portrait", "is_talking_model", "submit_talking", "upload_temporary"]
