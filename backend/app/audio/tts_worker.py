"""Standalone TTS / voice-clone worker (ported from the predecessor project's tts engines).

Runs inside the *TTS interpreter* — a Python that has f5-tts and/or fish-speech
installed (configured via OPEN_STUDIO_TTS_PYTHON, autodetected from a sibling
a sibling venv in dev). Must import nothing from this app at module level
besides the standard library, so the host backend can ship it to a foreign
interpreter.

Zero-shot cloning: synthesis conditions on (reference audio + its transcript)
to speak `text` in that voice. No training.

stdin:  JSON {action: "warmup"|"synthesize", engine, text?, reference_wav?,
              reference_text?, whisper_model?}
argv:   [output_path] — the synthesized WAV (results are files: engines print
        progress bars to stdout).
When the requested engine isn't importable, synthesis raises — it never invents
audio. (Warmup still writes a tiny marker wav; nobody listens to that one.)
The result JSON reports which engine actually ran.
"""
from __future__ import annotations

import json
import math
import os
import struct
import sys
import traceback
import wave
from pathlib import Path
from typing import Any


def _estimate_seconds(text: str) -> float:
    # ~4 chars/sec for CJK-ish pacing; clamp to a sane range.
    return max(1.0, min(30.0, len(text.strip()) * 0.22 + 0.6))


def write_marker_wav(path: str, text: str, sr: int = 24000) -> None:
    """预热用的占位输出。**只给预热用** —— 预热要的是"权重下下来了没有",它的 wav 没人会听。

    合成不再用它:合成的输出会被注册成素材、拖上时间线、导进成片,那里不能出现一段不是
    用户声音的东西。
    """
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


_FISH_HINT = (
    "Fish Speech S2 不可用:需要 fishaudio/s2-pro 权重 + 官方 fish-speech 源码检出。"
    "在设置→声音克隆填『源码目录』『模型目录』,或设置 OPEN_STUDIO_FISH_REPO_DIR / OPEN_STUDIO_FISH_MODEL_DIR。"
)


def _pick_device() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
    except Exception:  # noqa: BLE001
        pass
    return "cpu"


def _fish_repo_dir() -> Path:
    """The official fish-speech source checkout — its ``tools.server.*`` modules live at
    the repo root (not in the pip ``fish_speech`` package), so it must go on sys.path."""
    configured = os.environ.get("OPEN_STUDIO_FISH_REPO_DIR", "").strip()
    if configured and Path(configured).expanduser().is_dir():
        return Path(configured).expanduser()
    raise RuntimeError(_FISH_HINT + "(源码目录未找到)")


def _fish_model_dir() -> Path:
    """The weights directory: config.json + model safetensors + codec.pth at its root."""
    configured = os.environ.get("OPEN_STUDIO_FISH_MODEL_DIR", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if (path / "codec.pth").is_file():
            return path
    raise RuntimeError(_FISH_HINT + "(模型目录缺少 codec.pth)")


def run_fish(request: dict[str, Any], output_path: str) -> str:
    """Zero-shot clone via Fish Speech S2 Pro's official inference API. Runs the LLM +
    codec locally from a source checkout; conditions on (reference audio + its transcript)."""
    repo = _fish_repo_dir()
    model_dir = _fish_model_dir()
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))

    from fish_speech.utils.schema import ServeReferenceAudio, ServeTTSRequest  # type: ignore
    from tools.server.inference import inference_wrapper  # type: ignore
    from tools.server.model_manager import ModelManager  # type: ignore

    device = _pick_device()
    manager = ModelManager(
        mode="tts",
        device=device,
        half=device.startswith("cuda"),
        compile=False,
        llama_checkpoint_path=str(model_dir),
        decoder_checkpoint_path=str(model_dir / "codec.pth"),
        decoder_config_name="modded_dac_vq",
    )

    reference_wav = request.get("reference_wav")
    if not reference_wav:
        raise RuntimeError("Fish Speech 需要参考音频")
    references = [
        ServeReferenceAudio(
            audio=Path(reference_wav).read_bytes(),
            # The ref transcript keeps the clone intelligible — a wrong/empty one garbles output.
            text=request.get("reference_text") or "",
        )
    ]
    payload = ServeTTSRequest(text=request["text"], references=references, format="wav", streaming=False)
    audio = next(inference_wrapper(payload, manager.tts_inference_engine))
    sample_rate = int(manager.tts_inference_engine.decoder_model.sample_rate)

    import soundfile as sf  # type: ignore

    sf.write(output_path, audio, sample_rate, format="WAV")
    return "fish-speech"


def synthesize(request: dict[str, Any], output_path: str) -> str:
    """引擎跑不起来就**报错**,不写一段正弦音冒充结果。

    此前这里 catch 一切、写占位音、返回 "placeholder",宿主照样把任务标成成功并把它注册成音频
    素材 —— 用户拖到时间线上听到的是"嘟——"。一段听起来像结果的东西比一条错误难查得多:
    错误会停在任务上,而假结果会一路走到成片里。
    """
    engine = (request.get("engine") or "f5-tts").strip().lower()
    if engine == "fish-speech":
        return run_fish(request, output_path)
    return run_f5(request, output_path)


def warmup(request: dict[str, Any], output_path: str) -> str:
    """Construct the engine so its weights download; write a tiny marker wav."""
    engine = (request.get("engine") or "f5-tts").strip().lower()
    try:
        if engine == "fish-speech":
            from huggingface_hub import snapshot_download  # type: ignore

            # Managed install: land weights flat in OPEN_STUDIO_FISH_MODEL_DIR (codec.pth + config
            # at its root, which run_fish reads). Without a target, fall back to the HF cache.
            target = os.environ.get("OPEN_STUDIO_FISH_MODEL_DIR", "").strip()
            if target:
                snapshot_download(repo_id="fishaudio/s2-pro", local_dir=target)
            else:
                snapshot_download(repo_id="fishaudio/s2-pro")  # → HF cache; progress polled by host
        else:
            from f5_tts.api import F5TTS

            F5TTS(device="cpu")
        write_marker_wav(output_path, "预热")
        return engine
    except Exception:
        # **不吞**。此前这里 `except Exception: return "placeholder"` —— 退出码 0、stderr 空,
        # 宿主手里两样东西同时为空,只好在界面上猜一句「下载未完成,可能引擎未安装」。
        # 而被扔掉的那句话恰好是唯一有用的:
        #     LocalEntryNotFoundError: ... Please check your connection
        # (实测就是「模型下载源」选的镜像在这台机器上下不动。)
        # 一个吞掉的异常就是一次删掉的证据。
        traceback.print_exc(file=sys.stderr)
        raise


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
