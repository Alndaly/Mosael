from __future__ import annotations

import base64
import math
import mimetypes
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Literal

import httpx


from app.domain.providers import models as provider_models
from app.core import http_retry  # Gemini 的 generateContent 不是 /chat/completions,仍走裸重试
from app.domain.ai_chat import AiChatError, chat, target_for
from app.domain.billing.usage import BillableCall, billable, once
from sqlalchemy.orm import Session

from app.ai.providers.contracts.generation import sanitize_adapter_error
from app.core.i18n import LocalizedError
from app.db.models import Asset, ProviderProfile
from app.domain.providers import credentials as provider_credentials
from app.domain.providers.credentials import ResolvedConnection
from app.domain.providers.selection import find_enabled_connection, list_enabled_connections
from app.media.image_preview import browser_compatible_image
from app.media.paths import resolve_key
from app.core.child_process import run_logged
from app.core.config import settings
from app.media.probe import probe_media

"""Existing-asset visual analysis.

Standalone HTTP callers select an independently configured direct profile. Agent-tool callers
arrive with a service token bound to an AgentSession and pass its resolved current model here;
API-key targets use the direct Adapter and OAuth targets use the tool-free Gateway. Images are
normalized first. Video can use a native API-backed Adapter or evenly sampled frames plus any
existing transcript; the Gateway has no native video block and therefore uses frames.
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
# 视频分析方式:auto=API Adapter 有原生能力就走原生,OAuth Gateway/其余走抽帧;
# native=强制原生(OAuth 明确拒绝);frames=强制抽帧+转写。
VIDEO_ANALYSIS_MODES = ("auto", "frames", "native")
# 原生视频直传体积上限:base64 会膨胀约 33%,过大既慢又易被网关拒。超限建议抽帧。
MAX_NATIVE_VIDEO_MB = 48


def adaptive_frame_count(duration_seconds: float) -> int:
    """按时长定帧数:约每 SECONDS_PER_FRAME 秒 1 帧,夹在 [MIN_VIDEO_FRAMES, MAX_VIDEO_FRAMES]。"""
    if not (duration_seconds > 0):
        return MIN_VIDEO_FRAMES
    target = math.ceil(duration_seconds / SECONDS_PER_FRAME)
    return max(MIN_VIDEO_FRAMES, min(MAX_VIDEO_FRAMES, target))


class AnalysisError(LocalizedError, RuntimeError):
    """素材分析的领域错误。带文案 key(`analysisErr_*`),按读的人的语言翻(见 core/i18n)。"""


def select_analysis_connection(db: Session, profile_id: str | None, user_id: str | None) -> ResolvedConnection:
    """挑一条能做多模态的连接,并绑上**这个人**的钥匙。

    钥匙解析不出来就报出来,而不是换一条能用的 —— 「我以为用的是自己的额度,其实花的是别人的钱」
    是这里最坏的失败方式(见 domain/providers/credentials)。
    """
    if profile_id:
        profile = find_enabled_connection(db, "", profile_id, owner_user_id=user_id)
        if profile is None:
            raise AnalysisError("analysisErr_profileNotFound")
        return _resolve_connection_credentials(db, profile, user_id)
    profiles = list_enabled_connections(db, owner_user_id=user_id, auth_type="api_key")
    by_vendor = {profile.vendor: profile for profile in reversed(profiles)}
    for vendor in ANALYSIS_VENDOR_ORDER:
        if vendor in by_vendor:
            return _resolve_connection_credentials(db, by_vendor[vendor], user_id)
    raise AnalysisError("analysisErr_noVisionProvider")


def _resolve_connection_credentials(db: Session, profile: ProviderProfile, user_id: str | None) -> ResolvedConnection:
    resolved = provider_credentials.resolve_connection(db, profile, user_id)
    if resolved is None:
        raise AnalysisError("analysisErr_noCredential", name=profile.name)
    return resolved


def select_native_video_connection(
    db: Session,
    profile_id: str | None,
    user_id: str | None,
) -> ResolvedConnection | None:
    """挑一个支持原生视频理解的启用档案。指定 id 时必须本身是 native vendor;否则按 NATIVE_VIDEO_VENDORS
    优先级挑。没有则返回 None(交给上层回落抽帧)。"""
    if profile_id:
        profile = find_enabled_connection(db, "", profile_id, owner_user_id=user_id)
        if profile is not None and profile.vendor in NATIVE_VIDEO_VENDORS:
            return provider_credentials.resolve_connection(db, profile, user_id)
        return None
    profiles = list_enabled_connections(db, owner_user_id=user_id, auth_type="api_key")
    by_vendor = {profile.vendor: profile for profile in reversed(profiles)}
    for vendor in NATIVE_VIDEO_VENDORS:
        if vendor in by_vendor:
            # 原生视频是回落链的一环:钥匙没配就当这条路不存在,回落抽帧,而不是整个失败。
            return provider_credentials.resolve_connection(db, by_vendor[vendor], user_id)
    return None


def extract_video_frames(path: Path, count: int | None = None) -> list[bytes]:
    """Evenly sampled JPEG frames via a single ffmpeg pass. count=None → 按时长自适应帧数。"""
    with tempfile.TemporaryDirectory(prefix="mosael-frames-") as tmp:
        pattern = Path(tmp) / "frame-%02d.jpg"
        try:
            # 时长走共用的探测:头里没写时长的录像,这里曾把 "N/A" 交给 float() 直接抛出去。
            duration = max(float(probe_media(path).get("duration") or 1.0), 0.2)
            frame_count = count if count is not None else adaptive_frame_count(duration)
            run_logged(
                [
                    settings.ffmpeg, "-y", "-v", "error", "-i", str(path),
                    "-vf", f"fps={frame_count / duration}:round=up,scale={FRAME_WIDTH}:-2",
                    "-frames:v", str(frame_count), "-q:v", "5", str(pattern),
                ],
                check=True, capture_output=True, timeout=120, what="视频抽帧")
        except subprocess.SubprocessError as exc:
            raise AnalysisError("analysisErr_frameExtractFailed") from exc
        frames = sorted(Path(tmp).glob("frame-*.jpg"))
        if not frames:
            raise AnalysisError("analysisErr_noFrames")
        return [frame.read_bytes() for frame in frames]


def _breakdown_shots_for(db: Session, asset: Asset, path: Path) -> tuple[list[dict[str, Any]], Any | None]:
    """这条素材的镜头(ADR 0061 §3):库里有镜头表就用(刀口已经量好);没有就现场只量刀口
    (不取帧、不判画面,短片一两秒)。量不出来回 ([], None) —— 调用方回落均匀抽帧。"""
    from app.domain.shots import breakdowns as shots_breakdowns
    from app.domain.shots import detect as shots_detect

    row = shots_breakdowns.breakdown_for(db, asset.id)
    if row is not None and row.shots:
        return list(row.shots), row
    try:
        probed = shots_detect.probe(path)
        measured = shots_detect.measure(path, motion=False)
        return shots_detect.build_shots(probed.duration, measured.cuts, measured.motion), None
    except Exception:
        return [], None


def extract_shot_frames(
    path: Path, shots: list[dict[str, Any]], frame_count: int
) -> tuple[list[bytes], list[str] | None]:
    """按镜头取中点帧(每镜至少一帧,镜多均匀挑),每张图带 `S03 · 0:12.4–0:15.0` 标注,
    返回 `(帧字节, 标注)`;没有镜头 / 一帧都取不到时回落均匀抽帧(标注为 None)。
    分析不能因为镜头表缺席或取帧失败而失败。"""
    from app.domain.shots import frames as shots_frames

    if shots:
        try:
            labeled = shots_frames.grab_midframes(path, shots, frame_count)
        except Exception:
            labeled = []
        if labeled:
            return [image for _label, image in labeled], [label for label, _image in labeled]
    #: 均匀抽帧保持 `extract_video_frames(path)` 的单参形状 —— 既有测试替身按这个签名挂。
    return extract_video_frames(path), None


def shot_table_context(db: Session, asset: Asset) -> str:
    """已有镜头表的那一段(量好的刀口时长、判过的景别运镜);没有表回空串。两条路都带上(ADR 0061 §3)。"""
    from app.domain.shots import breakdowns as shots_breakdowns

    row = shots_breakdowns.breakdown_for(db, asset.id)
    if row is None or not row.shots:
        return ""
    return shots_breakdowns.prompt_context(row, asset)


def image_part(data: bytes, mime: str = "image/jpeg") -> dict[str, Any]:
    """一张图在对话消息里的样子(data URI)。**导出给别处用** —— 画板上「图片连到便签让
    模型看着写」用的是同一份,自己再拼一遍 base64 的话,格式改了只会改好其中一处。"""
    return _image_part(data, mime)


def _image_part(data: bytes, mime: str = "image/jpeg") -> dict[str, Any]:
    encoded = base64.b64encode(data).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}


def build_messages(
    asset: Asset,
    question: str,
    images: list[bytes],
    transcript: str | None = None,
    *,
    image_mime: str = "image/jpeg",
    frame_labels: list[str] | None = None,
    shot_context: str = "",
) -> list[dict[str, Any]]:
    meta = asset.media_info or {}
    context = f"素材名称: {asset.name}；类型: {asset.kind}"
    if meta.get("duration"):
        context += f"；时长: {meta['duration']}秒"
    if asset.kind == "video":
        if frame_labels is not None:
            context += (f"。以下是按镜头抽取的 {len(images)} 帧画面（每帧前面的标注写着它在哪一镜、"
                        "这一镜的起止时间，照标注说哪一帧在哪一镜）。镜头边界和时长是代码量出来的，准确。")
        else:
            context += f"。以下是按时间均匀抽取的 {len(images)} 帧画面（从前到后）。"
    # 画面只能"看",接上语音转写才能"听懂"台词/旁白——视频理解质量的关键补充。
    if transcript:
        context += f"\n\n【语音转写(自动识别,可能有误差,仅供参考)】\n{transcript}"
    # 已有镜头表就带上(ADR 0061 §3):量好的刀口时长、判过的景别运镜,模型不必再猜一遍。
    if shot_context:
        context += f"\n\n{shot_context}"
    content: list[dict[str, Any]] = [{"type": "text", "text": f"{context}\n\n{question}"}]
    if frame_labels is not None:
        for label, image in zip(frame_labels, images):
            content.append({"type": "text", "text": f"【{label}】"})
            content.append(_image_part(image, image_mime))
    else:
        content.extend(_image_part(image, image_mime) for image in images)
    return [{"role": "user", "content": content}]


def asset_transcript_text(db: Session, asset_id: str) -> str | None:
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


def call_vision_model(
    db: Session,
    profile: ResolvedConnection,
    messages: list[dict[str, Any]],
    call: BillableCall | None = None,
    *,
    model: str = "",
    surface: Literal["direct", "automation"] = "direct",
) -> str:
    # 参数是解析过的连接(连接 + 这个人的钥匙),不再是 ORM 对象 —— 此前靠 object_session 把
    # 会话从对象上摸出来,而 ResolvedConnection 没有挂在任何会话上,db 只能显式传。
    # 模型名不做兜底:取不到就让 target_for 当场报「这条连接下没有可用的对话模型」。
    # 此前回落成 "gpt-4o-mini" —— 用户选的是 Kimi,实际却在别家端点上花 OpenAI 模型的钱,
    # 静默换模型换厂商是这里最坏的失败方式(select_analysis_connection 的凭据原则同理)。
    try:
        return chat(
            target_for(db, profile, model=model, surface=surface),
            messages,
            temperature=0.2,
            timeout=REQUEST_TIMEOUT_SECONDS,
            call=call,
            label="分析请求",
        ).strip()
    except AiChatError as exc:
        raise AnalysisError(str(exc)) from exc


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
        raise AnalysisError("analysisErr_videoTooLarge", mb=MAX_NATIVE_VIDEO_MB)
    mime = mimetypes.guess_type(path.name)[0] or "video/mp4"
    return data, mime


def _call_gemini_video(
    db: Session,
    profile: ResolvedConnection,
    prompt: str,
    video: bytes,
    mime: str,
    call: BillableCall | None = None,
    *,
    model: str = "",
) -> str:
    """Gemini 原生:视频字节走 inline_data,generateContent 端点(非 OpenAI 兼容)。"""
    base_url = (profile.base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    model = (model or provider_models.model_id_for(db, profile, "chat")).strip()
    if not model:
        # 与 OpenAI-compatible 分支的 target_for 保持同一条不变量：连接下没有显式可用的
        # chat 模型就当场失败，不能因为这个 Adapter 绕开 target_for 而暗换成某个固定 Gemini。
        raise AnalysisError("analysisErr_noChatModel", name=profile.name)
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
        response = http_retry.post(
            f"{base_url}/models/{model}:generateContent",
            params={"key": profile.api_key},
            json=body,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        if call is not None:
            call.describe(provider=profile.vendor or "", model=model, provider_profile_id=profile.id)
            # Gemini 的计量字段叫 usageMetadata,键名也和 OpenAI 不同 —— 计量本来就该因供应商
            # 而异,billable 只要求最后落到 input_tokens / output_tokens 上。
            meta = payload.get("usageMetadata") or {}
            call.meter(
                input_tokens=int(meta.get("promptTokenCount") or 0),
                output_tokens=int(meta.get("candidatesTokenCount") or 0),
                raw=meta if isinstance(meta, dict) else {},
            )
        return str(payload["candidates"][0]["content"]["parts"][0]["text"]).strip()
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        raise AnalysisError("analysisErr_geminiFailed", detail=sanitize_adapter_error(str(exc), profile.api_key)) from exc


def _analyze_video_native(
    db: Session,
    profile: ResolvedConnection,
    asset: Asset,
    path: Path,
    question: str,
    transcript: str | None,
    call: BillableCall | None = None,
    *,
    model: str = "",
    surface: Literal["direct", "automation"] = "direct",
) -> str:
    """原生视频理解:Gemini 走 inline_data;Qwen-VL / Kimi 等 OpenAI 兼容端走 content 里的 video_url。"""
    video, mime = _read_native_video(path)
    prompt = _prompt_text(asset, question, transcript)
    if profile.vendor in GEMINI_VIDEO_VENDORS:
        return _call_gemini_video(db, profile, prompt, video, mime, call, model=model)
    data_uri = f"data:{mime};base64,{base64.b64encode(video).decode()}"
    content = [{"type": "text", "text": prompt}, {"type": "video_url", "video_url": {"url": data_uri}}]
    return call_vision_model(
        db,
        profile,
        [{"role": "user", "content": content}],
        call,
        model=model,
        surface=surface,
    )


def analyze_asset(
    db: Session,
    asset: Asset,
    question: str,
    *,
    user_id: str | None,
    profile_id: str | None = None,
    mode: str = "auto",
    resolved_connection: ResolvedConnection | None = None,
    model: str = "",
    surface: Literal["direct", "automation"] = "direct",
) -> dict[str, Any]:
    if asset.kind not in ("image", "video"):
        raise AnalysisError("analysisErr_unsupportedKind")
    if not asset.file_key:
        raise AnalysisError("analysisErr_noLocalFile")
    if mode not in VIDEO_ANALYSIS_MODES:
        raise AnalysisError("analysisErr_unknownMode", mode=mode)
    path = resolve_key(asset.file_key)
    if not path.is_file():
        raise AnalysisError("analysisErr_fileMissing")

    prompt = question.strip() or "请描述这个素材的内容。"

    # 图片:始终抽一帧走视觉模型(原生视频那套对图片没意义)。
    if asset.kind == "image":
        compatible = browser_compatible_image(path, path.parent)
        if compatible is None:
            raise AnalysisError("analysisErr_imageUnconvertible")
        image_path, image_mime = compatible
        profile = resolved_connection or select_analysis_connection(db, profile_id, user_id)
        with billable(
            db, user_id=user_id, capability="chat", operation="analyze_asset", workspace_id=asset.workspace_id,
            idempotency_key=once("analyze_asset"),
            source_type="asset", source_id=asset.id,
        ) as call:
            messages = build_messages(asset, prompt, [image_path.read_bytes()], image_mime=image_mime)
            if resolved_connection is not None:
                answer = call_vision_model(db, profile, messages, call, model=model, surface=surface)
            else:
                # 保留普通 HTTP/MCP 旧入口的调用形状，让测试替身和第三方调用者不必学习新参数。
                answer = call_vision_model(db, profile, messages, call)
        actual_model = model or provider_models.model_id_for(db, profile, "chat")
        return {"answer": answer, "provider": profile.vendor, "model": actual_model, "mode": "image", "frames": 1}

    transcript_text = asset_transcript_text(db, asset.id)  # 转写两条路都喂
    #: 有镜头表就带上(两条路都带,ADR 0061 §3):量好的刀口时长、判过的景别运镜,模型不必再猜。
    table_context = shot_table_context(db, asset)
    oauth_gateway = resolved_connection is not None and surface == "automation" and resolved_connection.auth_type == "oauth"
    if mode == "native" and oauth_gateway:
        raise AnalysisError("analysisErr_oauthNoNativeVideo")
    if mode == "frames" or oauth_gateway:
        native_profile = None
    elif resolved_connection is not None:
        native_profile = resolved_connection if resolved_connection.vendor in NATIVE_VIDEO_VENDORS else None
    else:
        native_profile = select_native_video_connection(db, profile_id, user_id)

    # 原生视频理解:显式 native 必须有原生档案;auto 有就走、没有回落抽帧。
    if mode == "native" and native_profile is None:
        raise AnalysisError("analysisErr_noNativeVideoProvider")
    if native_profile is not None and mode in ("native", "auto"):
        # 原生视频理解是这套里最贵的调用之一,以前完全不在账上。
        native_prompt = f"{prompt}\n\n{table_context}" if table_context else prompt
        with billable(
            db, user_id=user_id, capability="chat", operation="analyze_asset", workspace_id=asset.workspace_id,
            idempotency_key=once("analyze_asset"),
            source_type="asset", source_id=asset.id,
        ) as call:
            answer = _analyze_video_native(
                db,
                native_profile,
                asset,
                path,
                native_prompt,
                transcript_text,
                call,
                model=model,
                surface=surface,
            )
        actual_model = model or provider_models.model_id_for(db, native_profile, "chat")
        return {
            "answer": answer,
            "provider": native_profile.vendor,
            "model": actual_model,
            "mode": "native",
            "used_transcript": bool(transcript_text),
        }

    # 抽帧 + 转写(frames,或 auto 无原生档案时的回落)。
    # 按镜头抽(ADR 0061 §3):先量刀口,每镜至少一帧取中点,每张图标着 S03 · 0:12.4–0:15.0;
    # 没镜头表 / 取不到时回落老喂法(均匀抽帧)。
    profile = resolved_connection or select_analysis_connection(db, profile_id, user_id)
    shots, _row = _breakdown_shots_for(db, asset, path)
    frame_count = adaptive_frame_count(float((asset.media_info or {}).get("duration") or 0))
    images, frame_labels = extract_shot_frames(path, shots, frame_count)
    with billable(
        db, user_id=user_id, capability="chat", operation="analyze_asset", workspace_id=asset.workspace_id,
        idempotency_key=once("analyze_asset"),
        source_type="asset", source_id=asset.id,
    ) as call:
        messages = build_messages(asset, prompt, images, transcript=transcript_text,
                                  frame_labels=frame_labels, shot_context=table_context)
        if resolved_connection is not None:
            answer = call_vision_model(db, profile, messages, call, model=model, surface=surface)
        else:
            answer = call_vision_model(db, profile, messages, call)
    actual_model = model or provider_models.model_id_for(db, profile, "chat")
    return {
        "answer": answer,
        "provider": profile.vendor,
        "model": actual_model,
        "mode": "frames",
        "frames": len(images),
        "used_transcript": bool(transcript_text),
    }
