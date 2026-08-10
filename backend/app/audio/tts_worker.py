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


# ---------------------------------------------------------------------------
# 常驻模式
# ---------------------------------------------------------------------------
#: 和宿主约定的协议前缀(见 audio/tts_daemon)。引擎自己会往这个通道打 tqdm 和 loguru,
#: 所以只有带前缀的行才是协议。
EVENT_PREFIX = "@@OPEN-STUDIO-TTS "

#: 已经加载好的引擎。**常驻模式存在的全部理由就是这个字典** —— 实测一次 Fish Speech 的
#: 权重加载要 511.9 秒,而解码本身只有几十秒。
_LOADED: dict[str, Any] = {}


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(EVENT_PREFIX + json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _progress(phase: str, fraction: float, message: str = "") -> None:
    """报**在做哪一步**,以及一个粗粒度的比例。

    不编细粒度的百分比:LLM 解码的 token 数事先不知道(上限 1023,通常远早于此停),
    拿"当前 token / 上限"当进度,会画出一条永远走不到头的条 —— 那是另一种说谎。
    """
    _emit({"event": "progress", "phase": phase, "fraction": round(fraction, 3), "message": message})


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

    # 和 fish 一样只加载一次 —— F5 的权重比 fish 小,但加载同样以分钟计。
    model = _LOADED.get("f5-tts")
    if model is None:
        device = _pick_device()
        _progress("load", 0.1, f"首次加载权重({device})")
        model = F5TTS(device=device)
        _LOADED["f5-tts"] = model
    _progress("generate", 0.35, "生成中")
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

    # **加载一次**。实测这一步 511.9 秒(18 GB 权重),而解码本身只有几十秒 ——
    # 每次合成重建一个 ModelManager,等于把用户的十分钟花在读同一份文件上。
    manager = _LOADED.get("fish-speech")
    if manager is None:
        device = _pick_device()
        _progress("load", 0.1, f"首次加载权重({device},约几分钟)")
        manager = ModelManager(
            mode="tts",
            device=device,
            half=device.startswith("cuda"),
            compile=False,
            llama_checkpoint_path=str(model_dir),
            decoder_checkpoint_path=str(model_dir / "codec.pth"),
            decoder_config_name="modded_dac_vq",
        )
        _LOADED["fish-speech"] = manager

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
    _progress("generate", 0.35, "生成中")
    audio = next(inference_wrapper(payload, manager.tts_inference_engine))
    _progress("encode", 0.9, "写出音频")
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


#: fishaudio/s2-pro 在两边的仓库 id 恰好同名,但别把它当成规律 —— 分开写着。
FISH_HF_REPO = "fishaudio/s2-pro"
FISH_MODELSCOPE_REPO = "fishaudio/s2-pro"


def _modelscope_snapshot(model_id: str, local_dir: str) -> str:
    from modelscope import snapshot_download  # type: ignore

    return snapshot_download(model_id, local_dir=local_dir)


def _hf_snapshot(**kwargs: Any) -> str:
    from huggingface_hub import snapshot_download  # type: ignore

    return snapshot_download(**kwargs)


def fetch_fish_weights() -> None:
    """把 Fish Speech 的权重拉到托管目录。

    走哪条路由宿主通过 `OPEN_STUDIO_MODEL_SOURCE` 告诉这里。ModelScope **不是** HF 兼容端点,
    `HF_ENDPOINT` 那一套对它无效,得换一个客户端 —— 此前"选 ModelScope"只是把 HF_ENDPOINT
    设成了 huggingface.co,于是那个选项列在那里、选得中、却什么都不改变。

    这条路值多少:用户机器上实测 ModelScope ~9 MB/s,而 HuggingFace 和 hf-mirror 都是
    46 KB/s —— 9 GB 是 14 分钟和 55 小时的区别。
    """
    # 落成扁平目录(codec.pth + config 在根上,run_fish 就是这么读的);没给目标目录就退到各自的缓存。
    target = os.environ.get("OPEN_STUDIO_FISH_MODEL_DIR", "").strip()
    if os.environ.get("OPEN_STUDIO_MODEL_SOURCE", "").strip() == "modelscope":
        _modelscope_snapshot(FISH_MODELSCOPE_REPO, local_dir=target)
        return
    if target:
        _hf_snapshot(repo_id=FISH_HF_REPO, local_dir=target)
    else:
        _hf_snapshot(repo_id=FISH_HF_REPO)  # → HF cache;进度由宿主轮询目录


def warmup(request: dict[str, Any], output_path: str) -> str:
    """Construct the engine so its weights download; write a tiny marker wav."""
    engine = (request.get("engine") or "f5-tts").strip().lower()
    try:
        if engine == "fish-speech":
            fetch_fish_weights()
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


def serve() -> None:
    """按行收请求,权重留在内存里。一个进程只服务一个引擎(两套权重同时挂是 30 GB)。"""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            output_path = request["output_path"]
            engine = (request.get("engine") or "f5-tts").strip().lower()
            _progress("load", 0.05, "准备引擎")
            engine_used = synthesize(request, output_path)
            _emit({"event": "done", "engine": engine_used, "output": output_path})
        except Exception as exc:  # noqa: BLE001 — 常驻进程要**活下去**,把失败报回去就行
            traceback.print_exc(file=sys.stderr)
            _emit({"event": "error", "message": f"{type(exc).__name__}: {exc}"})


def main() -> None:
    if "--serve" in sys.argv[1:]:
        serve()
        return
    request = json.loads(sys.stdin.read())
    output_path = sys.argv[1]
    action = (request.get("action") or "synthesize").strip().lower()
    engine_used = warmup(request, output_path) if action == "warmup" else synthesize(request, output_path)
    # Sidecar result file so the host knows which engine actually ran.
    with open(output_path + ".json", "w", encoding="utf-8") as handle:
        json.dump({"engine": engine_used}, handle)


if __name__ == "__main__":
    main()
