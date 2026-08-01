from __future__ import annotations

import base64
import math
import mimetypes
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import httpx

from app.domain import ai_retry
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers.base import sanitize_provider_error
from app.db.models import Asset, ProviderProfile
from app.media.paths import resolve_key

"""
Asset analysis via OpenAI-compatible multimodal chat completions.
Images go in directly; videos are sampled into evenly-spaced frames —
this works uniformly across Kimi (moonshot), MiniMax, and any other
OpenAI-compatible vision endpoint the user configures.
"""

ANALYSIS_VENDOR_ORDER = ("moonshot", "minimax", "openai", "openai-compatible")
# 抽帧数按时长自适应:约每 SECONDS_PER_FRAME 秒 1 帧,夹在 [MIN, MAX]。帧越多画面覆盖越全,
# 但图片 token 线性上涨,所以封顶——避免长视频把上下文和费用打爆。
MIN_VIDEO_FRAMES = 4
MAX_VIDEO_FRAMES = 16
SECONDS_PER_FRAME = 6.0
FRAME_WIDTH = 512
REQUEST_TIMEOUT_SECONDS = 120
# 转写文本喂进分析时的字符上限(控 token)。
TRANSCRIPT_MAX_CHARS = 6000

# 支持"原生视频理解"(直接吃视频、不抽帧)的 vendor:
#   google  → Gemini 原生 API(视频走 inline_data)
#   alibaba → 通义千问 Qwen-VL(OpenAI 兼容,content 里 video_url)
#   moonshot→ Kimi 视觉(OpenAI 兼容,content 里 video_url)
NATIVE_VIDEO_VENDORS = ("google", "alibaba", "moonshot")
GEMINI_VIDEO_VENDORS = ("google",)
# 视频分析方式:auto=有原生能力就走原生、否则抽帧;native=强制原生;frames=强制抽帧+转写。
VIDEO_ANALYSIS_MODES = ("auto", "frames", "native")
# 原生视频直传体积上限:base64 会膨胀约 33%,过大既慢又易被网关拒。超限建议抽帧。
MAX_NATIVE_VIDEO_MB = 48


def adaptive_frame_count(duration_seconds: float) -> int:
    """按时长定帧数:约每 SECONDS_PER_FRAME 秒 1 帧,夹在 [MIN_VIDEO_FRAMES, MAX_VIDEO_FRAMES]。"""
    if not (duration_seconds > 0):
        return MIN_VIDEO_FRAMES
    target = math.ceil(duration_seconds / SECONDS_PER_FRAME)
    return max(MIN_VIDEO_FRAMES, min(MAX_VIDEO_FRAMES, target))


class AnalysisError(RuntimeError):
    pass


def pick_analysis_profile(db: Session, profile_id: str | None = None) -> ProviderProfile:
    if profile_id:
        profile = db.get(ProviderProfile, profile_id)
        if profile is None or not profile.enabled:
            raise AnalysisError("指定的供应商配置不存在或已停用")
        return profile
    profiles = db.scalars(select(ProviderProfile).where(ProviderProfile.enabled.is_(True))).all()
    by_vendor = {profile.vendor: profile for profile in reversed(profiles)}
    for vendor in ANALYSIS_VENDOR_ORDER:
        if vendor in by_vendor:
            return by_vendor[vendor]
    raise AnalysisError("没有可用的多模态供应商，请在设置中添加（如 Kimi 或 MiniMax）")


def pick_native_video_profile(db: Session, profile_id: str | None = None) -> ProviderProfile | None:
    """挑一个支持原生视频理解的启用档案。指定 id 时必须本身是 native vendor;否则按 NATIVE_VIDEO_VENDORS
    优先级挑。没有则返回 None(交给上层回落抽帧)。"""
    if profile_id:
        profile = db.get(ProviderProfile, profile_id)
        if profile is not None and profile.enabled and profile.vendor in NATIVE_VIDEO_VENDORS:
            return profile
        return None
    profiles = db.scalars(select(ProviderProfile).where(ProviderProfile.enabled.is_(True))).all()
    by_vendor = {profile.vendor: profile for profile in reversed(profiles)}
    for vendor in NATIVE_VIDEO_VENDORS:
        if vendor in by_vendor:
            return by_vendor[vendor]
    return None


def extract_video_frames(path: Path, count: int | None = None) -> list[bytes]:
    """Evenly sampled JPEG frames via a single ffmpeg pass. count=None → 按时长自适应帧数。"""
    with tempfile.TemporaryDirectory(prefix="open-studio-frames-") as tmp:
        pattern = Path(tmp) / "frame-%02d.jpg"
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                check=True, capture_output=True, text=True, timeout=20,
            )
            duration = max(float(probe.stdout.strip() or 1.0), 0.2)
            frame_count = count if count is not None else adaptive_frame_count(duration)
            subprocess.run(
                [
                    "ffmpeg", "-y", "-v", "error", "-i", str(path),
                    "-vf", f"fps={frame_count / duration}:round=up,scale={FRAME_WIDTH}:-2",
                    "-frames:v", str(frame_count), "-q:v", "5", str(pattern),
                ],
                check=True, capture_output=True, timeout=120,
            )
        except subprocess.SubprocessError as exc:
            raise AnalysisError("视频抽帧失败") from exc
        frames = sorted(Path(tmp).glob("frame-*.jpg"))
        if not frames:
            raise AnalysisError("视频中没有可用画面")
        return [frame.read_bytes() for frame in frames]


def _image_part(data: bytes, mime: str = "image/jpeg") -> dict[str, Any]:
    encoded = base64.b64encode(data).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}


def build_messages(
    asset: Asset, question: str, images: list[bytes], transcript: str | None = None
) -> list[dict[str, Any]]:
    meta = asset.media_info or {}
    context = f"素材名称: {asset.name}；类型: {asset.kind}"
    if meta.get("duration"):
        context += f"；时长: {meta['duration']}秒"
    if asset.kind == "video":
        context += f"。以下是按时间均匀抽取的 {len(images)} 帧画面（从前到后）。"
    # 画面只能"看",接上语音转写才能"听懂"台词/旁白——视频理解质量的关键补充。
    if transcript:
        context += f"\n\n【语音转写(自动识别,可能有误差,仅供参考)】\n{transcript}"
    content: list[dict[str, Any]] = [{"type": "text", "text": f"{context}\n\n{question}"}]
    content.extend(_image_part(image) for image in images)
    return [{"role": "user", "content": content}]


def _asset_transcript_text(db: Session, asset_id: str) -> str | None:
    """把该素材已有转写拼成一段纯文本(按时间顺序);没有则 None。"""
    from app.domain.transcripts.operations import get_transcript_for_asset

    transcript = get_transcript_for_asset(db, asset_id)
    if transcript is None:
        return None
    parts = [segment.text.strip() for segment in transcript.segments if segment.text and segment.text.strip()]
    text = " ".join(parts).strip()
    if not text:
        return None
    return text[:TRANSCRIPT_MAX_CHARS]


def call_vision_model(profile: ProviderProfile, messages: list[dict[str, Any]]) -> str:
    base_url = profile.base_url.rstrip("/")
    model = profile.default_model or "gpt-4o-mini"
    try:
        response = ai_retry.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {profile.api_key}"},
            json={"model": model, "messages": messages, "temperature": 0.2},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        return str(payload["choices"][0]["message"]["content"]).strip()
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        raise AnalysisError(sanitize_provider_error(f"分析请求失败: {exc}", profile.api_key)) from exc


def _prompt_text(asset: Asset, question: str, transcript: str | None) -> str:
    """原生视频用的纯文本提示(不含帧,画面交给模型直读);带上转写作为"听"的补充。"""
    meta = asset.media_info or {}
    context = f"素材名称: {asset.name}；类型: {asset.kind}"
    if meta.get("duration"):
        context += f"；时长: {meta['duration']}秒"
    if transcript:
        context += f"\n\n【语音转写(自动识别,可能有误差,仅供参考)】\n{transcript}"
    return f"{context}\n\n{question}"


def _read_native_video(path: Path) -> tuple[bytes, str]:
    data = path.read_bytes()
    if len(data) > MAX_NATIVE_VIDEO_MB * 1024 * 1024:
        raise AnalysisError(f"视频超过 {MAX_NATIVE_VIDEO_MB}MB,原生直传过大,请改用抽帧模式")
    mime = mimetypes.guess_type(path.name)[0] or "video/mp4"
    return data, mime


def _call_gemini_video(profile: ProviderProfile, prompt: str, video: bytes, mime: str) -> str:
    """Gemini 原生:视频字节走 inline_data,generateContent 端点(非 OpenAI 兼容)。"""
    base_url = (profile.base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    model = profile.default_model or "gemini-2.0-flash"
    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime, "data": base64.b64encode(video).decode()}},
                ],
            }
        ]
    }
    try:
        response = ai_retry.post(
            f"{base_url}/models/{model}:generateContent",
            params={"key": profile.api_key},
            json=body,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        return str(payload["candidates"][0]["content"]["parts"][0]["text"]).strip()
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        raise AnalysisError(sanitize_provider_error(f"Gemini 视频分析失败: {exc}", profile.api_key)) from exc


def _analyze_video_native(profile: ProviderProfile, asset: Asset, path: Path, question: str, transcript: str | None) -> str:
    """原生视频理解:Gemini 走 inline_data;Qwen-VL / Kimi 等 OpenAI 兼容端走 content 里的 video_url。"""
    video, mime = _read_native_video(path)
    prompt = _prompt_text(asset, question, transcript)
    if profile.vendor in GEMINI_VIDEO_VENDORS:
        return _call_gemini_video(profile, prompt, video, mime)
    data_uri = f"data:{mime};base64,{base64.b64encode(video).decode()}"
    content = [{"type": "text", "text": prompt}, {"type": "video_url", "video_url": {"url": data_uri}}]
    return call_vision_model(profile, [{"role": "user", "content": content}])


def analyze_asset(
    db: Session, asset: Asset, question: str, profile_id: str | None = None, mode: str = "auto"
) -> dict[str, Any]:
    if asset.kind not in ("image", "video"):
        raise AnalysisError("只支持分析图片或视频素材")
    if not asset.file_key:
        raise AnalysisError("素材没有本地文件")
    if mode not in VIDEO_ANALYSIS_MODES:
        raise AnalysisError(f"未知分析方式: {mode}")
    path = resolve_key(asset.file_key)
    if not path.is_file():
        raise AnalysisError("素材文件缺失")

    prompt = question.strip() or "请描述这个素材的内容。"

    # 图片:始终抽一帧走视觉模型(原生视频那套对图片没意义)。
    if asset.kind == "image":
        profile = pick_analysis_profile(db, profile_id)
        answer = call_vision_model(profile, build_messages(asset, prompt, [path.read_bytes()]))
        return {"answer": answer, "provider": profile.vendor, "model": profile.default_model, "mode": "image", "frames": 1}

    transcript_text = _asset_transcript_text(db, asset.id)  # 转写两条路都喂
    native_profile = None if mode == "frames" else pick_native_video_profile(db, profile_id)

    # 原生视频理解:显式 native 必须有原生档案;auto 有就走、没有回落抽帧。
    if mode == "native" and native_profile is None:
        raise AnalysisError("没有支持原生视频理解的供应商(需 Gemini / 通义千问 Qwen-VL / Kimi),或改用抽帧模式")
    if native_profile is not None and mode in ("native", "auto"):
        answer = _analyze_video_native(native_profile, asset, path, prompt, transcript_text)
        return {
            "answer": answer,
            "provider": native_profile.vendor,
            "model": native_profile.default_model,
            "mode": "native",
            "used_transcript": bool(transcript_text),
        }

    # 抽帧 + 转写(frames,或 auto 无原生档案时的回落)。
    profile = pick_analysis_profile(db, profile_id)
    images = extract_video_frames(path)  # 帧数按时长自适应
    answer = call_vision_model(profile, build_messages(asset, prompt, images, transcript=transcript_text))
    return {
        "answer": answer,
        "provider": profile.vendor,
        "model": profile.default_model,
        "mode": "frames",
        "frames": len(images),
        "used_transcript": bool(transcript_text),
    }
