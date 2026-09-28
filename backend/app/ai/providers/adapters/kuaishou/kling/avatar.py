"""可灵数字人与对口型(ADR 0028 阶段 4)。

官方文档(2026-09-28 读,英文站 kling.ai/document-api):

- **数字人**(`/api/video/avatar`):`POST /v1/videos/avatar/image2video`,`image`(人像)+ `sound_file`(配音)
  + 可选 `prompt`(≤2500 字,动作、情绪、运镜)+ `mode`(std / pro)。图片、音频都收**不带前缀的 Base64** 或
  可访问的链接;图片 jpg/png ≤10MB、边长 ≥300px、宽高比 1:2.5–2.5:1;音频 mp3/wav/m4a/aac ≤5MB、2–300 秒。
  查询 `GET /v1/videos/avatar/image2video/{task_id}`。
- **对口型**(`/api/video/lip-sync` 与 `/lip-sync/face-detection`):两步。
  1. `POST /v1/videos/identify-face`,`video_url`(**只收链接**:mp4/mov ≤100MB、2–60 秒、720p 或 1080p、边长
     512–2160px)→ `session_id` + `face_data[]`(每张脸的 `face_id` 和出现的起止毫秒);
  2. `POST /v1/videos/advanced-lip-sync`,`session_id` + `face_choose`(目前只支持一个人):`face_id`、`sound_file`
     (Base64 或链接,2–60 秒)、`sound_start_time` / `sound_end_time`(从配音里截哪段,毫秒,截出来 ≥2 秒)、
     `sound_insert_time`(插到原片第几毫秒;和那张脸出现的时段至少重叠 2 秒,不能超出原片)、`sound_volume` /
     `original_audio_volume`(0–2)。查询 `GET /v1/videos/advanced-lip-sync/{task_id}`。

两者回的都是旧接口那种形状(`task_status`: submitted / processing / succeed / failed,结果在
`task_result.videos[].url`),和 video.extract_video_url 同一份解析。
"""

from __future__ import annotations

import base64
import logging
import tempfile
from pathlib import Path
from typing import Any

from app.ai.providers.contracts.generation import (
    DRIVING_AUDIO,
    FIRST_FRAME,
    SOURCE_VIDEO,
    GenerationAdapterError,
    GenerationRequest,
    source_url_values,
)

logger = logging.getLogger(__name__)

AVATAR_MODEL = "kling-avatar"
LIPSYNC_MODEL = "kling-lipsync"
AVATAR_PATH = "/v1/videos/avatar/image2video"
IDENTIFY_FACE_PATH = "/v1/videos/identify-face"
LIPSYNC_PATH = "/v1/videos/advanced-lip-sync"
#: 音频直传的上限(两个接口都是 5MB)。超了先转成单声道 mp3 —— 300 秒的 64kbps mp3 约 2.4MB。
MAX_AUDIO_BYTES = 5 * 1024 * 1024
MIN_OVERLAP_MS = 2000


def is_avatar(model: str) -> bool:
    return str(model or "").strip().lower() == AVATAR_MODEL


def is_lipsync(model: str) -> bool:
    return str(model or "").strip().lower() == LIPSYNC_MODEL


def _url_or_path(request: GenerationRequest, role: str) -> tuple[str | None, Path | None]:
    urls = source_url_values(request.parameters, role, request.kind)
    if urls:
        return str(urls[0]), None
    for item in request.sources:
        if item.role == role:
            return item.public_url, item.path
    return None, None


def _raw_base64(data: bytes) -> str:
    """可灵要**不带** `data:…;base64,` 前缀的 Base64(文档明写带了就错)。"""
    return base64.b64encode(data).decode("ascii")


def image_field(request: GenerationRequest) -> str:
    url, path = _url_or_path(request, FIRST_FRAME)
    if url:
        return url
    if path is None or not path.is_file():
        raise GenerationAdapterError("providerErr_sourceMissing", vendor="Kling", role=FIRST_FRAME)
    return _raw_base64(path.read_bytes())


def _audio_bytes(path: Path) -> bytes:
    """配音文件的字节;不是 mp3/wav/m4a/aac、或超了 5MB 的先转成单声道 mp3(可灵收这四种,≤5MB)。"""
    raw = path.read_bytes()
    if path.suffix.lower() in (".mp3", ".wav", ".m4a", ".aac") and len(raw) <= MAX_AUDIO_BYTES:
        return raw
    from app.media.vendor_formats import speech_mp3

    with tempfile.TemporaryDirectory(prefix="mosael-kling-audio-") as folder:
        converted = speech_mp3(path, Path(folder) / "voice.mp3").read_bytes()
    if len(converted) > MAX_AUDIO_BYTES:
        raise GenerationAdapterError("providerErr_klingAudioTooLarge")
    return converted


def audio_field(request: GenerationRequest) -> str:
    url, path = _url_or_path(request, DRIVING_AUDIO)
    if url:
        return url
    if path is None or not path.is_file():
        raise GenerationAdapterError("providerErr_sourceMissing", vendor="Kling", role=DRIVING_AUDIO)
    return _raw_base64(_audio_bytes(path))


def build_avatar_payload(request: GenerationRequest) -> dict[str, Any]:
    """数字人的请求体。清晰度照旧接口那条规矩映射:1080p 走 pro(高质量),其余 std(文档:「std 性价比,pro 画质更好」)。"""
    payload: dict[str, Any] = {
        "image": image_field(request),
        "sound_file": audio_field(request),
        "mode": "pro" if str(request.parameters.get("resolution") or "").lower() == "1080p" else "std",
    }
    if request.prompt.strip():
        payload["prompt"] = request.prompt.strip()[:2500]
    if request.parameters.get("external_task_id"):
        payload["external_task_id"] = str(request.parameters["external_task_id"])
    return payload


def audio_duration_ms(request: GenerationRequest) -> int:
    """配音多长(毫秒)。本地文件照素材库那套探测量;只有链接时量不了,交回 0,由调用方按人脸时段截。"""
    _url, path = _url_or_path(request, DRIVING_AUDIO)
    if path is None or not path.is_file():
        return 0
    from app.media.probe import probe_media

    seconds = probe_media(path).get("duration")
    if not seconds:
        logger.warning("量不出配音 %s 的时长", path.name)
        return 0
    return int(float(seconds) * 1000)


def video_url(request: GenerationRequest) -> str:
    """识别人脸只收链接(生成漏斗按描述符的 url_only_roles 先把本地原片换成直链)。"""
    url, _path = _url_or_path(request, SOURCE_VIDEO)
    if not url:
        raise GenerationAdapterError("providerErr_sourceMissing", vendor="Kling", role=SOURCE_VIDEO)
    return url


def pick_face(faces: list[dict[str, Any]]) -> dict[str, Any]:
    """原片里出现最久的那张脸(接口一次只对一个人)。一张都没有就说清楚。"""
    usable = [one for one in faces if isinstance(one, dict) and one.get("face_id") is not None]
    if not usable:
        raise GenerationAdapterError("providerErr_klingNoFace")
    return max(usable, key=lambda one: int(one.get("end_time") or 0) - int(one.get("start_time") or 0))


def build_lipsync_payload(session_id: str, face: dict[str, Any], sound_file: str, audio_ms: int) -> dict[str, Any]:
    """从那张脸出现的那一刻插进配音,截到「配音多长」和「脸还在多久」里短的那个;不足 2 秒接口不收,提前说。

    原片的声音压到 0:对口型是让人说**新的**这段话,原来的人声留着就是两段话叠在一起(译配那条路另有背景轨)。
    """
    start = int(face.get("start_time") or 0)
    window = int(face.get("end_time") or 0) - start
    length = min(audio_ms, window) if audio_ms else window
    if length < MIN_OVERLAP_MS:
        raise GenerationAdapterError("providerErr_klingFaceTooShort")
    return {
        "session_id": session_id,
        "face_choose": [{
            "face_id": str(face["face_id"]),
            "sound_file": sound_file,
            "sound_start_time": 0,
            "sound_end_time": length,
            "sound_insert_time": start,
            "sound_volume": 1,
            "original_audio_volume": 0,
        }],
    }
