"""阿里云百炼的数字人(ADR 0028):`wan2.2-s2v`(说话照片)和 `videoretalk`(改口型)。

和万相视频是**同一套异步任务协议**(提交拿 task_id → 轮询 `/api/v1/tasks/{id}` → 下载预签名地址),所以轮询、
取地址、下载都走 `video.py` 那一份;这里只多三件它俩自己的事:

· **提交路径不同**:两个都走 `image2video/video-synthesis`,不是万相的 `video-generation/video-synthesis`。
· **素材是链接字段**(`image_url` / `audio_url` / `video_url`),不收内联的 base64。本地素材先传到**百炼自己的临时存储**
  (`dashscope/uploads`,和声音复刻共用),提交时带上 `X-DashScope-OssResourceResolve: enable`。配音生成的音频都是
  本地文件,要求先配好对象存储才能让人物说话,门槛就太高了。有公网直链的素材(从链接导入的)直接用直链。
· **说话照片先预检**:`wan2.2-s2v-detect` 同步判一张图能不能用(清晰、单人、正面),不过就不提交,说「没找到清晰的正脸」。
  预检只要请求成功就计费(文档原话),所以只在真要提交之前调一次。

接口形状照 2026-09-26 读到的官方文档写,**还没拿真实密钥跑到终态**(ADR 0028 §3):第一次真跑时以接口自己的报错校准。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.ai.providers.adapters.alibaba.dashscope.uploads import OSS_RESOLVE_HEADER, TemporaryUploadError, upload_temporary
from app.ai.providers.contracts.generation import (
    DRIVING_AUDIO,
    FIRST_FRAME,
    REFERENCE_IMAGE,
    SOURCE_VIDEO,
    GenerationAdapterError,
    GenerationRequest,
    report_side_call,
    source_url_values,
)
from app.core.http_retry import RetryingClient

SUBMIT_PATH = "/api/v1/services/aigc/image2video/video-synthesis"
DETECT_PATH = "/api/v1/services/aigc/image2video/face-detect"

S2V_MODEL_PREFIX = "wan2.2-s2v"
S2V_DETECT_MODEL = "wan2.2-s2v-detect"
RETALK_MODEL = "videoretalk"
#: 改口型的原视频每边要在这个范围里(百炼回「The height or width of video must be 640 ~ 2048」)。
RETALK_VIDEO_SIDES = (640, 2048)


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


def _upload(client: RetryingClient, model: str, path: Path) -> str:
    """传到百炼的临时存储(凭证只绑这个生成模型)。取不到凭证说成生成那一类的错。"""
    try:
        return upload_temporary(client, model, path)
    except TemporaryUploadError as exc:
        raise GenerationAdapterError.relay(exc) from exc


def _input_url(client: RetryingClient, request: GenerationRequest, role: str, *, required: bool = True) -> str:
    url, local = _local_or_url(request, role)
    if url:
        return url
    if local is not None:
        if role == SOURCE_VIDEO and str(request.model).lower() == RETALK_MODEL:
            return _upload_fitted_video(client, request.model, local)
        return _upload(client, request.model, local)
    if required:
        raise GenerationAdapterError("providerErr_sourceMissing", vendor="DashScope", role=role)
    return ""


def _upload_fitted_video(client: RetryingClient, model: str, path: Path) -> str:
    """改口型的原视频先等比缩放进每边 640–2048 像素再传(说话照片交回的 512×512 直接交过去被拒,真跑撞上过)。
    已经在范围里的原样传;缩放用的临时文件传完就删。"""
    import tempfile

    from app.media.vendor_formats import VendorFormatError, video_sides_within

    low, high = RETALK_VIDEO_SIDES
    with tempfile.TemporaryDirectory(prefix="mosael-retalk-") as scratch:
        try:
            fitted = video_sides_within(path, Path(scratch) / f"{path.stem}-fit.mp4", min_side=low, max_side=high)
        except VendorFormatError as exc:
            raise GenerationAdapterError(exc.key, **exc.params) from exc
        return _upload(client, model, fitted)


def check_portrait(client: RetryingClient, image_url: str) -> None:
    """说话照片之前的预检:图里要有一张清晰、正面的人脸。不过就说人话,不提交。

    预检是**同步**接口:交进来的是提交任务那个客户端(带着 `X-DashScope-Async: enable`),这一次要把异步头摘掉 ——
    带着它百炼回 403「current user api does not support asynchronous calls」(真跑撞上过,一次都没走到提交)。
    """
    request = client.build_request(
        "POST", DETECT_PATH, json={"model": S2V_DETECT_MODEL, "input": {"image_url": image_url}}, headers=OSS_RESOLVE_HEADER,
    )
    request.headers.pop("X-DashScope-Async", None)
    response = client.send(request)
    response.raise_for_status()
    body = response.json() or {}
    #: 请求成功就计费,不管过没过 —— 先记这一笔,再看结果(见 contracts.generation.report_side_call)。
    report_side_call(S2V_DETECT_MODEL, {"requests": 1, "images": 1}, body)
    output = body.get("output") or {}
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


__all__ = ["build_talking_payload", "check_portrait", "is_talking_model", "submit_talking"]
