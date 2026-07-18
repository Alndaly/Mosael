"""Standalone TTS / voice-clone worker (ported from mibu-video's tts engines).

Runs inside the *TTS interpreter* — a Python that has f5-tts and/or fish-speech
installed (configured via MIBU_TTS_PYTHON, autodetected from a sibling
mibu-video venv in dev). Must import nothing from this app at module level
besides the standard library, so the host backend can ship it to a foreign
interpreter.

Zero-shot cloning: synthesis conditions on (reference audio + its transcript)
to speak `text` in that voice. No training.

stdin:  JSON {action: "warmup"|"synthesize", engine, text?, reference_wav?,
              reference_text?, whisper_model?}
argv:   [output_path] — the synthesized WAV (results are files: engines print
        progress bars to stdout).
When the requested engine isn't importable, falls back to a placeholder tone of
the estimated duration so the whole pipeline (asset + timeline) works without
the heavy models installed. The result JSON reports which engine actually ran.
"""
from __future__ import annotations

import json
import math
import struct
import sys
import wave
from typing import Any


def _estimate_seconds(text: str) -> float:
    # ~4 chars/sec for CJK-ish pacing; clamp to a sane range.
    return max(1.0, min(30.0, len(text.strip()) * 0.22 + 0.6))


def write_placeholder_wav(path: str, text: str, sr: int = 24000) -> None:
    """A gentle fading tone of the estimated length — audible marker so the
    asset/waveform/timeline flow is testable before f5-tts is installed."""
    seconds = _estimate_seconds(text)
    total = int(seconds * sr)
    with wave.open(path, "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        frames = bytearray()
        for i in range(total):
            fade = 1.0 - i / total
            value = int(0.06 * fade * math.sin(2 * math.pi * 196.0 * i / sr) * 32767)
            frames += struct.pack("<h", value)
        handle.writeframes(bytes(frames))


def run_f5(request: dict[str, Any], output_path: str) -> str:
    from f5_tts.api import F5TTS  # heavy, only in the TTS interpreter

    device = "cpu"
    try:
        import torch

        if torch.cuda.is_available():
            device = "cuda"
        elif torch.backends.mps.is_available():
            device = "mps"
    except Exception:  # noqa: BLE001
        pass
    model = F5TTS(device=device)
    model.infer(
        ref_file=request["reference_wav"],
        ref_text=request.get("reference_text") or "",  # empty → F5 auto-transcribes the ref
        gen_text=request["text"],
        file_wave=output_path,
        remove_silence=False,
        seed=0,
    )
    return "f5-tts"


def run_fish(request: dict[str, Any], output_path: str) -> str:
    # Fish Speech S2 Pro runs from a source checkout (tools.server). Ported in a
    # later slice; until then fall back to the placeholder so the flow works.
    raise ModuleNotFoundError("fish-speech not wired yet")


def synthesize(request: dict[str, Any], output_path: str) -> str:
    engine = (request.get("engine") or "f5-tts").strip().lower()
    try:
        if engine == "fish-speech":
            return run_fish(request, output_path)
        return run_f5(request, output_path)
    except Exception:  # noqa: BLE001 — engine missing/failed → audible placeholder
        write_placeholder_wav(output_path, request.get("text", ""))
        return "placeholder"


def warmup(request: dict[str, Any], output_path: str) -> str:
    """Construct the engine so its weights download; write a tiny marker wav."""
    engine = (request.get("engine") or "f5-tts").strip().lower()
    try:
        if engine == "fish-speech":
            run_fish({**request, "text": "预热", "reference_wav": None}, output_path)
        else:
            from f5_tts.api import F5TTS

            F5TTS(device="cpu")
        write_placeholder_wav(output_path, "预热")
        return engine
    except Exception:  # noqa: BLE001
        write_placeholder_wav(output_path, "预热")
        return "placeholder"


def main() -> None:
    request = json.loads(sys.stdin.read())
    output_path = sys.argv[1]
    action = (request.get("action") or "synthesize").strip().lower()
    engine_used = warmup(request, output_path) if action == "warmup" else synthesize(request, output_path)
    # Sidecar result file so the host knows which engine actually ran.
    with open(output_path + ".json", "w", encoding="utf-8") as handle:
        json.dump({"engine": engine_used}, handle)


if __name__ == "__main__":
    main()
