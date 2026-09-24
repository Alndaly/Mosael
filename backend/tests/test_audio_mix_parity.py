"""The same audio contract runs against browser gain evaluation and real FFmpeg output."""
import array
import json
import math
from pathlib import Path
import shutil
import subprocess

import pytest
from app.media.render_executor import build_ffmpeg_command
from app.media.render_plan import build_render_plan

CASES = json.loads((Path(__file__).resolve().parents[2] / "contracts/audio-mix-cases.json").read_text())["cases"]

@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")
@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_export_audio_matches_shared_contract(case, tmp_path):
    # Low-level sine avoids clipping even at 4x gain. Integer frequency gives matching phase
    # when voice and music start at different whole seconds.
    tone = tmp_path / "tone.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=8:sample_rate=48000", "-af", "volume=0.2", str(tone)], check=True, capture_output=True, timeout=10)
    # 用例带 base 时,基底是一段**带声**视频,声音和 tone 同频同相(PCM,没有 AAC 的起始延迟,
    # 相位才对得上);不带时是无声黑场、基底整条静音,只量音频轨。
    base_case = case.get("base")
    base = tmp_path / ("base.mov" if base_case else "base.mp4")
    video = ["-f", "lavfi", "-i", "color=black:s=32x32:r=20:d=4"]
    sound = ["-f", "lavfi", "-i", "sine=frequency=440:duration=4:sample_rate=48000", "-af", "volume=0.2", "-c:a", "pcm_s16le", "-shortest"] if base_case else []
    subprocess.run(["ffmpeg", "-y", "-v", "error", *video, *sound, str(base)], check=True, capture_output=True, timeout=10)
    clips = [{"asset_id": "tone", "timeline_start": 0, "src_in": 0, **clip} for clip in case["clips"]]
    base_clip = {key: value for key, value in (base_case or {"src_out": 4}).items() if key not in ("duck", "solo")}
    solo_active = case.get("solo_active", False)
    plan = build_render_plan(sequence_id="s", revision=1, width=32, height=32, fps=20,
        clips=[{"id": "base", "asset_id": "base", "timeline_start": 0, "src_in": 0, "has_audio": bool(base_case), **base_clip}],
        assets={"base": {"file_key": base.name}, "tone": {"file_key": "tone.wav"}}, audio_clips=clips,
        solo_active=solo_active,
        mute_base_audio=not base_case or (solo_active and not base_case.get("solo")),
        duck_base_audio=bool(base_case and base_case.get("duck")))
    out = tmp_path / "out.mp4"
    subprocess.run(build_ffmpeg_command(plan, lambda key: tmp_path / key, out, force_software=True), check=True, capture_output=True, timeout=20)
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(out), "-vn", "-ac", "1", "-ar", "48000", "-f", "f32le", "pipe:1"], timeout=10)
    samples = array.array("f", raw)
    # Stereo conversion uses -3dB per channel for a mono source, restored by mono downmix.
    unity_rms = 0.125 * 0.2 / math.sqrt(2)
    for sample in case["samples"]:
        center = int(sample["t"] * 48000)
        window = samples[center-1200:center+1200]
        rms = math.sqrt(sum(x*x for x in window) / len(window))
        assert rms / unity_rms == pytest.approx(sum(sample["gains"].values()), abs=0.12)
