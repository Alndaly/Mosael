from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.media.waveform import compute_peaks
from tests.util import fresh_client

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def make_tone(path: Path, seconds: float = 1.0) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", str(path)],
        check=True,
        timeout=30,
    )


def test_compute_peaks_normalizes_and_buckets() -> None:
    # 4 samples: silence, half, full, silence → 2 buckets
    pcm = (
        (0).to_bytes(2, "little", signed=True)
        + (16384).to_bytes(2, "little", signed=True)
        + (-32768).to_bytes(2, "little", signed=True)
        + (0).to_bytes(2, "little", signed=True)
    )
    peaks = compute_peaks(pcm, 2)
    assert peaks == [0.5, 1.0]
    assert compute_peaks(b"", 10) == []


def test_import_generates_waveform_and_endpoint_serves_it(tmp_path: Path) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()

    tone = tmp_path / "tone.wav"
    make_tone(tone)
    asset = client.post(
        "/api/assets/import",
        data={"workspace_id": ws["id"]},
        files={"file": ("tone.wav", tone.read_bytes(), "audio/wav")},
    ).json()
    assert asset["kind"] == "audio"
    assert asset["media_info"]["has_waveform"] is True

    res = client.get(f"/api/assets/{asset['id']}/waveform")
    assert res.status_code == 200
    payload = res.json()
    assert payload["version"] == 1
    assert abs(payload["duration"] - 1.0) < 0.1
    assert len(payload["peaks"]) > 100
    # ffmpeg's sine source generates around -18dB (~0.125 amplitude)
    assert max(payload["peaks"]) > 0.05
