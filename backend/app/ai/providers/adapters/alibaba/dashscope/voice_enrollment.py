"""百炼 CosyVoice 的声音复刻(ADR 0037):`voice-enrollment` 这个「模型」下的建 / 查 / 列 / 删。

真机验证(2026-10-05,素材是 Edge 合成的朗读,音色建完即删):

· 接口只收**地址**。参考音频先传到百炼自己的临时存储(`dashscope/uploads`,凭证按 `model=voice-enrollment` 取),
  交 `oss://…`,提交时带 `X-DashScope-OssResourceResolve: enable`。
· 建:`POST /api/v1/services/audio/tts/customization`,`input.action = create_voice`,回 `output.voice_id`,
  形如 `cosyvoice-v3-flash-<prefix>-<32 位 hex>`。
· **不是同步的**:`query_voice` 先是 DEPLOYING,约 10 秒后 OK。等的那一段在领域层(它要写任务进度)。
· 前缀超过 10 个字符直接 400;文档另说只收字母和数字。
· 音色**绑死在建它的那个模型上**:v3-flash 上建的发给 v2 是 400。
· `list_voice` 可按前缀过滤;`delete_voice` 之后列表为空。

错误照百炼原话(`code: message`)放进 `detail`,不翻、不猜。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.ai.providers.adapters.alibaba.dashscope.connection import failure_detail, native_base
from app.ai.providers.adapters.alibaba.dashscope.speech import CosyVoiceSpeechAdapter
from app.ai.providers.adapters.alibaba.dashscope.uploads import OSS_RESOLVE_HEADER, TemporaryUploadError, upload_temporary
from app.ai.providers.contracts.voice_enrollment import (
    DEPLOYING,
    READY,
    REJECTED,
    RemoteVoice,
    VoiceEnrollmentError,
)
from app.core.http_retry import RetryingClient

CUSTOMIZATION_PATH = "/api/v1/services/audio/tts/customization"
#: 复刻这件事在百炼那边是一个「模型」:取上传凭证、调接口都报这个名字。
ENROLLMENT_MODEL = "voice-enrollment"
#: 前缀的上限(超了百炼回 400「prefix should not be longer than 10 characters」)。
PREFIX_LIMIT = 10
#: 一把嗓子在一个账号里的副本按模型各一份,一页足够;给大一点,别让翻页漏掉一份。
_LIST_PAGE_SIZE = 100
_TIMEOUT_SECONDS = 60
#: 百炼的原词 → 归一的状态。认不出的按「没通过」算(`UNDEPLOYED` 就是审核没过)。
_STATUS = {"OK": READY, "DEPLOYING": DEPLOYING}


def remote_status(raw: str) -> str:
    return _STATUS.get(str(raw or "").strip().upper(), REJECTED)


def enrollment_payload(action: str, **fields: Any) -> dict[str, Any]:
    """四个动作同一个信封:`{"model": "voice-enrollment", "input": {"action": …, …}}`。"""
    return {"model": ENROLLMENT_MODEL, "input": {"action": action, **fields}}


class CosyVoiceEnrollmentAdapter:
    """CosyVoice 的声音复刻。和 `CosyVoiceSpeechAdapter` 同一把 DashScope Key、同一个根地址 —— 复刻出来的音色
    就交给那个合成适配器去念,它一行不改。"""

    engine_id = CosyVoiceSpeechAdapter.engine_id

    def __init__(self, api_key: str, base_url: str = "") -> None:
        if not api_key:
            raise VoiceEnrollmentError("providerErr_bailianTtsKeyMissing")
        self._key = api_key
        self._base = native_base(base_url)

    def _client(self, *, max_retries: int | None = None) -> RetryingClient:
        return RetryingClient(
            base_url=self._base,
            timeout=_TIMEOUT_SECONDS,
            headers={"Authorization": f"Bearer {self._key}"},
            max_retries=max_retries,
        )

    def _call(self, client: RetryingClient, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        response = client.post(CUSTOMIZATION_PATH, json=payload, headers=headers)
        if response.status_code >= 400:
            raise VoiceEnrollmentError("providerErr_voiceEnrollFailed", detail=failure_detail(response))
        return (response.json() or {}).get("output") or {}

    def create(self, *, target_model: str, prefix: str, reference: Path) -> str:
        if not prefix or len(prefix) > PREFIX_LIMIT or not prefix.isalnum():
            # 我们自己的编程错误(前缀由 domain/voices/remote.prefix_for 定),不该打到百炼那里去换一个 400。
            raise ValueError(f"prefix must be 1–{PREFIX_LIMIT} letters or digits: {prefix!r}")
        with self._client() as client:
            try:
                url = upload_temporary(client, ENROLLMENT_MODEL, reference)
            except TemporaryUploadError as exc:
                raise VoiceEnrollmentError.relay(exc) from exc
            except httpx.HTTPStatusError as exc:
                raise VoiceEnrollmentError("providerErr_voiceEnrollUploadFailed", detail=failure_detail(exc.response)) from exc
            except httpx.HTTPError as exc:
                raise VoiceEnrollmentError("providerErr_voiceEnrollUploadFailed", detail=str(exc)) from exc
        # **建这一下不重试**:超时之后再发一遍,账号里就多一个没人认领的音色(前缀认得出、删得掉,但不该造出来)。
        with self._client(max_retries=0) as client:
            try:
                output = self._call(
                    client,
                    enrollment_payload("create_voice", target_model=target_model, prefix=prefix, url=url),
                    headers=OSS_RESOLVE_HEADER,
                )
            except httpx.HTTPError as exc:
                raise VoiceEnrollmentError("providerErr_voiceEnrollFailed", detail=str(exc)) from exc
        voice_id = str(output.get("voice_id") or "").strip()
        if not voice_id:
            raise VoiceEnrollmentError("providerErr_voiceEnrollNoVoiceId")
        return voice_id

    def query(self, voice_id: str) -> RemoteVoice:
        output = self._safe_call(enrollment_payload("query_voice", voice_id=voice_id))
        raw = str(output.get("status") or "")
        return RemoteVoice(
            voice_id=voice_id, status=remote_status(raw), raw_status=raw, target_model=str(output.get("target_model") or "")
        )

    def list(self, *, prefix: str) -> list[RemoteVoice]:
        output = self._safe_call(enrollment_payload("list_voice", prefix=prefix, page_index=0, page_size=_LIST_PAGE_SIZE))
        found: list[RemoteVoice] = []
        for item in output.get("voice_list") or []:
            if not isinstance(item, dict) or not item.get("voice_id"):
                continue
            raw = str(item.get("status") or "")
            found.append(RemoteVoice(
                voice_id=str(item["voice_id"]), status=remote_status(raw), raw_status=raw,
                target_model=str(item.get("target_model") or ""),
            ))
        return found

    def delete(self, voice_id: str) -> None:
        self._safe_call(enrollment_payload("delete_voice", voice_id=voice_id))

    def _safe_call(self, payload: dict[str, Any]) -> dict[str, Any]:
        """查、列、删:重放无害,照常重试;网络错误也说成复刻那一类的错。"""
        with self._client() as client:
            try:
                return self._call(client, payload)
            except httpx.HTTPError as exc:
                raise VoiceEnrollmentError("providerErr_voiceEnrollFailed", detail=str(exc)) from exc


__all__ = [
    "CUSTOMIZATION_PATH",
    "ENROLLMENT_MODEL",
    "PREFIX_LIMIT",
    "CosyVoiceEnrollmentAdapter",
    "enrollment_payload",
    "remote_status",
]
