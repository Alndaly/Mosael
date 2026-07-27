from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.media.frame_encoder import EncodeCancelled, RawEncodeParams, encode_frames_to_mp4
from app.media.probe import probe_has_audio_many, probe_media


def _has_libx264() -> bool:
    if shutil.which("ffmpeg") is None:
        return False
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=20)
    except Exception:
        return False
    return "libx264" in out.stdout


pytestmark = pytest.mark.skipif(not _has_libx264(), reason="ffmpeg with libx264 not installed")


def _solid_rgba(width: int, height: int, rgba: tuple[int, int, int, int]) -> bytes:
    return bytes(rgba) * (width * height)


def test_encode_rawvideo_frames_to_mp4(tmp_path: Path) -> None:
    w, h, fps, n = 64, 48, 30, 15
    frame = _solid_rgba(w, h, (10, 150, 40, 255))
    out = tmp_path / "out.mp4"

    seen: list[int] = []
    count = encode_frames_to_mp4(
        (frame for _ in range(n)),
        RawEncodeParams(w, h, fps, crf=23, encode_preset="veryfast"),
        out,
        on_frame=seen.append,
    )

    assert count == n
    assert seen[-1] == n  # progress reported per frame
    assert out.is_file()
    info = probe_media(out)
    assert info["width"] == w
    assert info["height"] == h
    assert abs(info["fps"] - fps) < 0.01
    assert abs(info["duration"] - n / fps) < 0.15  # ~0.5s, allow container rounding
    assert not probe_has_audio_many([out])[out]  # -an: no audio track


def test_encode_muxes_audio_track(tmp_path: Path) -> None:
    w, h, fps, n = 64, 48, 30, 30  # 1.0s of video
    audio = tmp_path / "a.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1.0",
         "-ar", "48000", "-ac", "2", str(audio)],
        check=True, timeout=60,
    )
    out = tmp_path / "av.mp4"
    encode_frames_to_mp4(
        (_solid_rgba(w, h, (0, 0, 0, 255)) for _ in range(n)),
        RawEncodeParams(w, h, fps, crf=23, encode_preset="veryfast"),
        out,
        audio_path=audio,
    )
    assert out.is_file()
    assert probe_has_audio_many([out])[out]  # muxed audio present


def test_wrong_frame_size_raises(tmp_path: Path) -> None:
    w, h, fps = 64, 48, 30
    with pytest.raises(ValueError, match="expected"):
        encode_frames_to_mp4(
            iter([b"\x00\x00\x00\xff" * (w * h - 5)]),  # one short frame
            RawEncodeParams(w, h, fps),
            tmp_path / "bad.mp4",
        )


def test_cancel_midstream_raises(tmp_path: Path) -> None:
    w, h, fps = 64, 48, 30
    frame = _solid_rgba(w, h, (1, 2, 3, 255))

    def frames():
        for _ in range(10_000):
            yield frame

    calls = {"n": 0}

    def should_cancel() -> bool:
        calls["n"] += 1
        return calls["n"] > 5  # cancel after a few frames

    with pytest.raises(EncodeCancelled):
        encode_frames_to_mp4(frames(), RawEncodeParams(w, h, fps), tmp_path / "cancel.mp4", should_cancel=should_cancel)
