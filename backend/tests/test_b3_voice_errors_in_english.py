"""配音、转写、降噪、分离、分析的报错按读的人的语言说 —— 英文界面不再弹中文。

这些领域的错误此前是写死的中文句子,经路由 `detail=str(exc)` 原样转出,或在后台任务里写进
`job.error`。改成「文案 key + 参数」之后:请求里按 Accept-Language 翻,任务失败原因存 key
(见 jobs.blame),读的时候按读的人的语言翻。上游原文(ffmpeg、worker 的异常行)不翻,作为参数
放进翻好的句子里。
"""

from __future__ import annotations

import io
import wave
from types import SimpleNamespace

import pytest

from app.core.i18n import LocalizedError, t
from app.domain.jobs import blame


def _en(exc: LocalizedError) -> str:
    return t(exc.key, "en", **exc.params)


def test_short_reference_audio_is_refused_in_english_with_the_numbers() -> None:
    from app.domain.voices import voices

    with pytest.raises(voices.VoiceError) as caught:
        voices.check_reference_duration(2.6)

    assert _en(caught.value) == (
        "The reference audio is too short (only 2.6 s). Zero-shot cloning needs enough speech to learn the voice "
        "— give it 5–15 seconds of continuous, clear speech, or the result will be unintelligible."
    )
    # 缺省语言(后台线程、没有请求头)仍是原来那句中文。
    assert "参考音频太短(只有 2.6 秒)" in str(caught.value)


def test_worker_failure_keeps_the_upstream_line_inside_an_english_sentence() -> None:
    from app.domain.voices import voices

    error = voices.worker_failure("Traceback...\nModuleNotFoundError: No module named 'natsort'\n")

    assert isinstance(error, voices.VoiceError)
    assert _en(error) == (
        "Speech synthesis failed: ModuleNotFoundError: No module named 'natsort' — the engine's runtime is "
        "incomplete. Go to Settings → Voice cloning and click Download to add the missing dependencies."
    )


def test_language_guard_names_the_language_in_english() -> None:
    from app.domain.voices.voices import VoiceError, _refuse_if_unspeakable

    with pytest.raises(VoiceError) as caught:
        _refuse_if_unspeakable("三日前のだったらちょっとお腹壊しちゃうかな", "edge", "zh-CN-XiaoxiaoNeural", "")

    assert _en(caught.value) == "This text is Japanese, but the selected Edge voice is zh. Pick a voice that starts with ja-."
    assert "日文" not in _en(caught.value)


def test_dub_error_carries_the_original_audio_key_instead_of_frozen_text() -> None:
    from app.domain.voices.subtitle_dub import DubError, start_subtitle_dub

    with pytest.raises(DubError) as caught:
        start_subtitle_dub(
            None,  # 模式不合法时在碰库之前就拒绝
            sequence_id="s",
            clip_ids=[],
            match_duration=False,
            created_by=None,
            synthesis={},
            original_audio="bogus",
        )

    assert caught.value.key == "dubErr_originalAudioMode"
    assert _en(caught.value) == "The original-audio mode must be one of duck / mute / keep / separate."


def test_asr_errors_are_localized_and_dictation_stays_a_subclass() -> None:
    from app.domain.voices.transcription import ASRError, DictationTooLong, resolve_transcription_runtime

    with pytest.raises(ASRError) as caught:
        resolve_transcription_runtime(engine="nonsense")

    assert _en(caught.value) == "Unsupported ASR engine: nonsense"
    # 路由据此把听写超长变成 4xx;以前 `except RuntimeError` 的地方照样接得住。
    assert issubclass(DictationTooLong, ASRError) and issubclass(ASRError, RuntimeError)
    assert _en(DictationTooLong("asrErr_dictationTooLong", seconds="300", limit="120")) == (
        "This recording is 300 s, over the 120 s dictation limit. For longer content, import it as an asset and transcribe that."
    )


def test_denoise_and_separation_errors_stay_catchable_as_the_contract_errors() -> None:
    from app.ai.providers.contracts.denoise import DenoiseError
    from app.ai.providers.contracts.separation import SeparationError
    from app.domain.denoise import ready_adapter
    from app.domain.separation import start_separation_job

    with pytest.raises(DenoiseError) as denoised:
        ready_adapter("no-such-engine")
    assert _en(denoised.value) == "There's no noise-reduction engine called no-such-engine."

    with pytest.raises(SeparationError) as separated:
        start_separation_job(None, asset=SimpleNamespace(kind="image", file_key="x"), created_by=None)
    assert _en(separated.value) == "Only audio or video assets can be separated."


def test_analysis_error_renders_in_english() -> None:
    from app.domain.analysis.service import AnalysisError, analyze_asset

    with pytest.raises(AnalysisError) as caught:
        analyze_asset(None, SimpleNamespace(kind="text", file_key="x"), "?", user_id=None)

    assert _en(caught.value) == "Only image or video assets can be analysed."


def test_a_failed_job_records_the_key_so_the_reader_gets_their_language() -> None:
    from app.domain.voices.transcription import ASRError

    recorded = blame(ASRError("asrErr_noAudioTrack", name="clip.mp4"))

    assert recorded["error_key"] == "asrErr_noAudioTrack"
    assert recorded["error_params"] == {"name": "clip.mp4"}
    assert t(recorded["error_key"], "en", **recorded["error_params"]) == (
        "\"clip.mp4\" has no audio track, so there's nothing to transcribe."
    )


def _wav(seconds: float) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buf.getvalue()


def test_the_voices_endpoint_answers_in_the_request_language() -> None:
    """走一遍真实的路由:`detail=str(exc)` 不用改,错误自己按请求语言说话。"""
    from tests.util import fresh_client

    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]

    resp = client.post(
        "/api/voices/upload",
        data={"workspace_id": workspace_id, "name": "short", "reference_text": "hello"},
        files={"file": ("ref.wav", _wav(2.6), "audio/wav")},
        headers={"Accept-Language": "en"},
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"].startswith("The reference audio is too short (only 2.6 s)."), resp.text
