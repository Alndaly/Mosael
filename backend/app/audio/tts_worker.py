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
import threading
import time
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
    # 缓存键带上权重路径:不带的话,切到日语模型时会命中上一次加载的中英模型 ——
    # 一切正常、只是念出来还是听不懂,而这正是这一整轮要修的那种失败。
    cache_key = f"f5-tts:{request.get('checkpoint') or F5_CHECKPOINT}"
    model = _LOADED.get(cache_key)
    if model is None:
        device = _pick_device()
        _progress("load", 0.1, f"首次加载权重({device})")
        # 走 ModelScope 下下来的那份在我们自己的目录里,F5TTS 不会自己去找 —— 显式指过去。
        # 声码器仍由它自己从 HF 拉(ModelScope 上没有 vocos)。
        announce_f5_fetch(request.get("reference_text") or "")
        managed = os.environ.get("OPEN_STUDIO_F5_MODEL_DIR", "").strip()
        # 用**这次请求指定的**那份权重。语言支持是模型的属性,不是引擎的(见 audio/f5_models);
        # 没指定就还是基础模型 —— 老请求、以及从别处直接调 worker 的路径原样能跑。
        ckpt = Path(managed) / (request.get("checkpoint") or F5_CHECKPOINT) if managed else None
        vocab = Path(managed) / (request.get("vocab") or F5_VOCAB) if managed else None
        if ckpt and ckpt.is_file():
            model = F5TTS(device=device, ckpt_file=str(ckpt),
                          vocab_file=str(vocab) if vocab and vocab.is_file() else "")
        else:
            model = F5TTS(device=device)
        _LOADED[cache_key] = model
    _progress("generate", 0.35, "生成中")
    model.infer(
        ref_file=request["reference_wav"],
        ref_text=request.get("reference_text") or "",  # empty → F5 auto-transcribes the ref
        gen_text=request["text"],
        speed=float(request.get("speed") or 1.0),
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
    except Exception as exc:  # noqa: BLE001
        # 掉回 CPU 的代价是十倍速度,不是一个细节。此前这里 `pass`,于是"为什么这么慢"
        # 在日志里没有任何线索 —— 而这正是今天查了半天的那类问题。
        print(f"挑选计算设备失败,回落到 CPU(会慢很多):{type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
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

#: F5 在 ModelScope 上的仓库和要取的那两个文件。整仓有五个 1.35 GB 的检查点(不同版本),
#: 只取当前 f5_tts 默认用的那一个 —— 整仓拉是 6.7 GB,而我们只需要其中一份。
F5_MODELSCOPE_REPO = "AI-ModelScope/F5-TTS"
F5_CHECKPOINT = "F5TTS_v1_Base/model_1250000.safetensors"
F5_VOCAB = "F5TTS_v1_Base/vocab.txt"


def _modelscope_file(repo: str, path: str, local_dir: str) -> str:
    from modelscope import snapshot_download  # type: ignore

    root = snapshot_download(repo, local_dir=local_dir, allow_patterns=[path])
    return str(Path(root) / path)


#: F5 还要的声码器。它只在 HuggingFace 上(ModelScope 三个命名空间都是 404)。
F5_VOCODER_CACHE = "models--charactr--vocos-mel-24khz"
#: 参考文本留空时,F5 用它来"自动识别"参考音频 —— 约 1.6 GB,也只在 HuggingFace 上。
F5_ASR_CACHE = "models--openai--whisper-large-v3-turbo"


def _hf_cache_roots() -> list[Path]:
    roots = []
    for env in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        if os.environ.get(env):
            roots.append(Path(os.environ[env]))
    if os.environ.get("HF_HOME"):
        roots.append(Path(os.environ["HF_HOME"]) / "hub")
    roots.append(Path.home() / ".cache" / "huggingface" / "hub")
    return [r for r in roots if r.is_dir()]


def _hf_cached(cache_dir_name: str) -> bool:
    """这个仓库**真的**在缓存里(有字节,不只是一个空目录)。

    只判目录在不在会被下载失败的残骸骗过去:fish 那次就是目录在、里面只有一个空的 refs/main。
    """
    for root in _hf_cache_roots():
        blobs = root / cache_dir_name / "blobs"
        if blobs.is_dir() and any(f.stat().st_size > 1_000_000 for f in blobs.glob("*") if f.is_file()):
            return True
    return False


def announce_f5_fetch(reference_text: str = "") -> None:
    """要下东西就说在**下**,别说成"加载"。

    用户选了 F5,界面十几分钟停在「首次加载权重」,而那段时间进程 CPU 0.1% —— 它在下载
    声码器(约 55 MB;这台机器上 HuggingFace 是 46 KB/s)。两件事的等待理由完全不同:
    加载是本地的、只能等;下载慢是网络问题,用户可以换源、可以先去干别的、可以判断
    "这不正常"。**说成"加载"就把一个可判断的处境变成了不可判断的处境。**
    """
    if not _hf_cached(F5_VOCODER_CACHE):
        _progress("download", 0.08,
                  "正在从 HuggingFace 下载声码器(约 55 MB);网络慢时这一步要十几分钟,只下这一次")
    # "自动识别"听起来是免费的,实际是再下一个 1.6 GB 的模型。**代价要在付出之前说**,
    # 而且要说清怎么绕开 —— 填上参考文本就完全不走这条路。
    if not (reference_text or "").strip() and not _hf_cached(F5_ASR_CACHE):
        _progress("download", 0.08,
                  "参考文本留空,F5 要先下载识别模型(Whisper,约 1.6 GB)来听参考音频说了什么;"
                  "给音色填上参考文本可以完全跳过这一步")


def fetch_f5_weights() -> None:
    """F5 的大文件走 ModelScope,小的(vocos 声码器)仍然走 HF。

    实测这台机器上 HF 和 hf-mirror 都是 46 KB/s,ModelScope ~9 MB/s:1.35 GB 的检查点
    是八小时和三分钟的区别。而 vocos(约 55 MB)在 ModelScope 上没有(AI-ModelScope /
    charactr / iic 三个命名空间都是 404),就算慢也只有二十分钟 —— 留给 f5_tts 自己去拉。

    选 HF 时这里什么都不做:F5TTS 构造时自己会拉,抢着下一份只会下两遍。
    """
    if os.environ.get("OPEN_STUDIO_MODEL_SOURCE", "").strip() != "modelscope":
        return
    target = os.environ.get("OPEN_STUDIO_F5_MODEL_DIR", "").strip()
    if not target:
        return
    for path in (F5_CHECKPOINT, F5_VOCAB):
        _modelscope_file(F5_MODELSCOPE_REPO, path, target)


def _hf_file(repo: str, path: str, local_dir: str) -> str:
    from huggingface_hub import hf_hub_download  # type: ignore

    return hf_hub_download(repo_id=repo, filename=path, local_dir=local_dir)


def fetch_named_model(request: dict[str, Any]) -> str:
    """按名字拉一份 F5 权重(检查点 + vocab)到托管目录。

    走哪条源由**这一次的请求**说了算:ModelScope 上有就走它(实测比 HF 快两个数量级),
    没有的社区微调只能走 HF。两个文件逐个拉,不拉整仓 —— `Jmica/F5TTS` 整仓有四份检查点,
    而我们只要其中一份。
    """
    target = request.get("target") or os.environ.get("OPEN_STUDIO_F5_MODEL_DIR", "").strip()
    if not target:
        raise RuntimeError("没有指定权重目录")
    # 每个模型落进自己的子目录:这些社区权重的 vocab **全叫 vocab.txt**,共用一个目录会互相覆盖。
    subdir = (request.get("subdir") or "").strip()
    if subdir:
        target = str(Path(target) / subdir)
    files = [path for path in (request.get("checkpoint"), request.get("vocab")) if path]
    modelscope_repo = (request.get("modelscope_repo") or "").strip()
    use_modelscope = bool(modelscope_repo) and os.environ.get("OPEN_STUDIO_MODEL_SOURCE", "").strip() == "modelscope"
    for index, path in enumerate(files):
        _progress("download", 0.1 + 0.8 * index / max(1, len(files)), f"下载 {path}")
        if use_modelscope:
            _modelscope_file(modelscope_repo, path, target)
        else:
            _hf_file(str(request.get("hf_repo") or ""), path, target)
    _progress("download", 1.0, "下载完成")
    return "f5-tts"


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
            fetch_f5_weights()  # ModelScope 那条路先把大文件拿下来
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


def _watch_parent(original_ppid: int) -> None:
    """父进程没了就自己走。

    现场抓到过一个 PPID=1、抱着 2.2 GB 跑了 35 分钟的孤儿:后端热重载把池子连同 kill()
    一起带走了,而子进程没人管。**不能指望父进程记得清理** —— 它被 SIGKILL 时不会执行
    任何清理代码。stdin 关闭是常规信号,但一个正卡在下载里的 worker 要等下载结束才读得到
    EOF,所以另加这条:被过继给 init 就退出。
    """
    while True:
        try:
            time.sleep(1.0)
            if os.getppid() != original_ppid:
                os._exit(0)  # 不做清理:权重还挂在内存里,越快还给系统越好
        except Exception:  # noqa: BLE001 — 它一死,孤儿进程就回来了,而没人会发现
            time.sleep(5.0)


def serve() -> None:
    """按行收请求,权重留在内存里。一个进程只服务一个引擎(两套权重同时挂是 30 GB)。"""
    threading.Thread(target=_watch_parent, args=(os.getppid(),), daemon=True).start()
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
    if action == "fetch_model":
        engine_used = fetch_named_model(request)
    elif action == "warmup":
        engine_used = warmup(request, output_path)
    else:
        engine_used = synthesize(request, output_path)
    # Sidecar result file so the host knows which engine actually ran.
    with open(output_path + ".json", "w", encoding="utf-8") as handle:
        json.dump({"engine": engine_used}, handle)


if __name__ == "__main__":
    main()
