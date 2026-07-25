from __future__ import annotations

import base64
import math
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import httpx
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


def extract_video_frames(path: Path, count: int | None = None) -> list[bytes]:
    """Evenly sampled JPEG frames via a single ffmpeg pass. count=None → 按时长自适应帧数。"""
    with tempfile.TemporaryDirectory(prefix="mibu-frames-") as tmp:
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
        response = httpx.post(
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


def analyze_asset(db: Session, asset: Asset, question: str, profile_id: str | None = None) -> dict[str, Any]:
    if asset.kind not in ("image", "video"):
        raise AnalysisError("只支持分析图片或视频素材")
    if not asset.file_key:
        raise AnalysisError("素材没有本地文件")
    path = resolve_key(asset.file_key)
    if not path.is_file():
        raise AnalysisError("素材文件缺失")

    profile = pick_analysis_profile(db, profile_id)
    transcript_text: str | None = None
    if asset.kind == "image":
        images = [path.read_bytes()]
    else:
        images = extract_video_frames(path)  # 帧数按时长自适应
        transcript_text = _asset_transcript_text(db, asset.id)  # 有转写就一起喂进去
    messages = build_messages(asset, question.strip() or "请描述这个素材的内容。", images, transcript=transcript_text)
    answer = call_vision_model(profile, messages)
    return {
        "answer": answer,
        "provider": profile.vendor,
        "model": profile.default_model,
        "frames": len(images),
        "used_transcript": bool(transcript_text),
    }
