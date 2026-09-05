"""Standalone ASR worker (ported from the predecessor project's pluggable ASR layer).

Runs inside the *ASR interpreter* — a Python that has funasr and/or whisperx
installed (configured via MOSAEL_ASR_PYTHON, autodetected from a sibling
a sibling checkout in dev). It must not import anything from this app at
module level besides the standard library, so the host backend can ship it to
a foreign interpreter.

stdin:  JSON {"audio_path": str, "provider": "funasr"|"whisperx", ...options}
argv:   [output_json_path] — results are written to a FILE because funasr and
        model downloads print progress bars straight to stdout.
output: JSON {"language": str, "segments": [
          {"start", "end", "text", "speaker"?, "words": [{"word","start","end"}]}
        ]}
Errors exit non-zero with the message on stderr.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import traceback
import unicodedata
from typing import Any

if __package__:
    from .asr_protocol import encode_event_line
else:
    # Executed directly by the ASR interpreter; its sys.path only contains this
    # directory, not the application package.
    from asr_protocol import encode_event_line


def _sec(value: Any) -> float:
    """FunASR timestamps are milliseconds → seconds."""
    try:
        return float(value) / 1000.0
    except (TypeError, ValueError):
        return 0.0


def _is_timed_char(ch: str) -> bool:
    """Characters that carry their own timestamp — not whitespace, not the
    punctuation the punc model inserts (those have no span)."""
    return not (ch.isspace() or unicodedata.category(ch).startswith("P"))


#: SenseVoice 把语种、情感、事件、是否 ITN 以特殊标记塞在文本开头:
#: `<|zh|><|NEUTRAL|><|Speech|><|withitn|>你真不错。`
_TAG = re.compile(r"<\|([^|]*)\|>")


def strip_funasr_tags(text: str) -> tuple[str, str]:
    """(正文, 语种)。**标记必须剥掉** —— 不剥的话字幕上会直接出现 `<|zh|><|NEUTRAL|>…`。

    第一个标记是 SenseVoice 检测到的语种,顺手取出来:它比"猜一个默认值"准得多,而下游
    (对齐、翻译、导出)都按这个语种走。
    """
    tags = _TAG.findall(text or "")
    language = ""
    for tag in tags:
        lowered = tag.strip().lower()
        if len(lowered) in (2, 3) and lowered.isalpha() and lowered not in ("nospeech",):
            language = lowered
            break
    return _TAG.sub("", text or "").strip(), language


def funasr_sentences_to_segments(sentences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map FunASR sentence_info (Paraformer spans + cam++ spk) to the segment
    contract. Per-char timestamps become word tokens; punctuation stays only in
    the sentence display text."""
    segments: list[dict[str, Any]] = []
    for sentence in sentences:
        # **两种模型的字段名不同**:Paraformer 给 "text",SenseVoice 给 "sentence"。
        # 只读前者的那段时间里,SenseVoice 的每一句都取到空串,于是整条转写产出 0 段 ——
        # 界面上报的是「转写结果为空」,看不出是字段名对不上。
        raw = sentence.get("sentence") or sentence.get("text") or ""
        text, _lang = strip_funasr_tags(raw)
        spans = sentence.get("timestamp") or []
        timed_chars = [ch for ch in text if _is_timed_char(ch)]
        words: list[dict[str, Any]] = []
        for ch, span in zip(timed_chars, spans):
            if not isinstance(span, (list, tuple)) or len(span) < 2:
                continue
            words.append({"word": ch, "start": _sec(span[0]), "end": _sec(span[1])})
        start = _sec(sentence["start"]) if sentence.get("start") is not None else (words[0]["start"] if words else 0.0)
        end = _sec(sentence["end"]) if sentence.get("end") is not None else (words[-1]["end"] if words else 0.0)
        if end <= start:
            end = start + 0.01
        spk = sentence.get("spk")
        try:
            speaker = f"SPEAKER_{int(spk):02d}" if spk is not None else None
        except (TypeError, ValueError):
            speaker = str(spk) if spk else None
        if not text and not words:
            continue
        segments.append({"start": start, "end": end, "text": text, "speaker": speaker, "words": words})
    return segments


#: FunASR 的默认识别模型。**多语种**:官方说明「支持超过 50 种语言,识别效果上优于 Whisper 模型」,
#: 标点与逆文本规整都在模型内部。与后端的 transcription.FUNASR_MODEL 是同一个值。
DEFAULT_FUNASR_MODEL = "iic/SenseVoiceSmall"


def _is_sensevoice(model_name: object) -> bool:
    return "sensevoice" in str(model_name).lower()


def _funasr_kwargs(request: dict[str, Any], *, device: str) -> dict[str, Any]:
    """构建 AutoModel 的入参 —— **预热和转写共用这一份**。

    分成两份写过一次:目录换成 SenseVoice 之后,预热仍按老的中文四件套拉 paraformer + punc,
    于是"下载"下的是目录里根本没列的权重,进度停着不动、最后报失败。预热要预热的,必须正是
    转写要用的那些。

    SenseVoice 自带标点与逆文本规整,所以不挂 punc_model(重复处理);**说话人分离要留着** ——
    它是独立阶段(按 VAD 切段后聚类),与识别模型无关,而转写面板的说话人标签全靠它。
    """
    model_name = request.get("funasr_model") or DEFAULT_FUNASR_MODEL
    kwargs: dict[str, Any] = dict(
        model=model_name,
        vad_model=request.get("funasr_vad_model", "fsmn-vad"),
        hub=request.get("funasr_hub", "ms"),
        device=device,
        disable_update=True,
    )
    if not _is_sensevoice(model_name):
        kwargs["punc_model"] = request.get("funasr_punc_model", "ct-punc")
    spk_model = request.get("funasr_spk_model", "cam++")
    if spk_model:
        kwargs["spk_model"] = spk_model
    return kwargs


def run_funasr(request: dict[str, Any]) -> dict[str, Any]:
    from funasr import AutoModel  # heavy, only in the ASR interpreter

    device = "cpu"
    try:
        import torch

        if torch.cuda.is_available():
            device = "cuda"
        elif torch.backends.mps.is_available():
            device = "mps"
    except Exception:  # noqa: BLE001 — odd torch build → cpu
        pass

    kwargs = _funasr_kwargs(request, device=device)
    model = AutoModel(**kwargs)
    sensevoice = _is_sensevoice(kwargs["model"])
    generate_kwargs: dict[str, Any] = dict(input=request["audio_path"], batch_size_s=300, sentence_timestamp=True)
    if sensevoice:
        # SenseVoice 按语言取值:给了就按它转,没给用 "auto" 让它自己判(它支持 50+ 语种)。
        generate_kwargs["language"] = request.get("language") or "auto"
        generate_kwargs["use_itn"] = True
    result = model.generate(**generate_kwargs)
    item = result[0] if result else {}
    sentences = item.get("sentence_info") or []
    if not sentences:
        spans = item.get("timestamp") or []
        sentences = [{
            "text": item.get("text", ""),
            "timestamp": spans,
            "spk": None,
            "start": spans[0][0] if spans else None,
            "end": spans[-1][1] if spans else None,
        }]
    # **不硬写 "zh"**:此前无论请求什么语言,这里都把结果标成中文 —— 于是英文素材转出来的字幕
    # 带着 language=zh,下游(字幕对齐、翻译、导出)都按中文处理。我们装的预设确实是中文的
    # (paraformer-zh),但"用的是中文模型"和"这段音频是中文"是两件事;请求里说了什么就报什么,
    # 没说才回落到预设的语言。
    # 语种优先取**模型检测出来的那个**(SenseVoice 以 <|zh|> 这类标记给出),其次用请求指定的,
    # 最后才回落。此前这里硬写 "zh":英文素材转出来的字幕也标成中文,下游全按中文处理。
    detected = ""
    for sentence in sentences:
        _text, lang = strip_funasr_tags(sentence.get("sentence") or sentence.get("text") or "")
        if lang:
            detected = lang
            break
    return {
        "language": detected or request.get("language") or "zh",
        "segments": funasr_sentences_to_segments(sentences),
    }


def whisperx_segments(aligned: dict[str, Any]) -> list[dict[str, Any]]:
    segments = []
    for segment in aligned.get("segments") or []:
        words = [
            {"word": w.get("word", "").strip(), "start": float(w["start"]), "end": float(w["end"])}
            for w in (segment.get("words") or [])
            if w.get("start") is not None and w.get("end") is not None
        ]
        text = (segment.get("text") or "").strip()
        if not text:
            continue
        segments.append({
            "start": float(segment["start"]),
            "end": float(segment["end"]),
            "text": text,
            "speaker": segment.get("speaker"),
            "words": words,
        })
    return segments


def run_whisperx(request: dict[str, Any]) -> dict[str, Any]:
    import whisperx  # heavy, only in the ASR interpreter

    device = "cpu"
    try:
        import torch

        if torch.cuda.is_available():
            device = "cuda"
    except Exception:  # noqa: BLE001
        pass
    compute_type = "float16" if device == "cuda" else "int8"
    model_name = request.get("whisper_model", "small")
    model = whisperx.load_model(model_name, device, compute_type=compute_type,
                                language=request.get("language") or None)
    audio = whisperx.load_audio(request["audio_path"])
    result = model.transcribe(audio, batch_size=int(request.get("batch_size", 8)))
    language = result.get("language", "zh")
    align_model, metadata = whisperx.load_align_model(language_code=language, device=device)
    aligned = whisperx.align(result["segments"], align_model, metadata, audio, device)
    return {"language": language, "segments": whisperx_segments(aligned)}


def warmup_funasr(request: dict[str, Any]) -> dict[str, Any]:
    """把 FunASR 的流水线构建一次,让权重落进 ModelScope 缓存,但不跑推理。

    **和转写用同一份构建逻辑**(_funasr_kwargs)—— 分成两份写过一次,代价很实在:目录已经换成
    SenseVoice,而预热还在按老的中文四件套拉 paraformer + punc,于是"下载"下的是一套目录里根本
    没列的权重,进度停在 33/972 MB 不动,最后报失败。预热要预热的,必须正是转写要用的那些。
    """
    from funasr import AutoModel

    AutoModel(**_funasr_kwargs(request, device="cpu"))
    return {"ok": True}


def warmup_whisperx(request: dict[str, Any]) -> dict[str, Any]:
    """Download the WhisperX (faster-whisper) model + the zh alignment model."""
    import whisperx

    model_name = request.get("whisper_model", "small")
    whisperx.load_model(model_name, "cpu", compute_type="int8", language=request.get("language") or None)
    try:
        whisperx.load_align_model(language_code=request.get("language") or "zh", device="cpu")
    except Exception:  # noqa: BLE001 — alignment model is optional for warmup
        pass
    return {"ok": True}


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(encode_event_line(payload))
    sys.stdout.flush()


def _watch_parent(parent_pid: int) -> None:
    """宿主没了就跟着退。

    常驻进程最坏的下场是变成孤儿:后端重启了,它还抱着几个 GB 的权重躺在那儿,而没有任何
    东西会去收它 —— 用户只会发现内存莫名其妙少了一块。
    """
    while True:
        time.sleep(5)
        try:
            os.kill(parent_pid, 0)
        except OSError:
            os._exit(0)


def execute_request(request: dict[str, Any]) -> dict[str, Any]:
    provider = (request.get("provider") or "funasr").strip().lower()
    action = (request.get("action") or "transcribe").strip().lower()
    if action == "warmup":
        return warmup_funasr(request) if provider == "funasr" else warmup_whisperx(request)
    return run_funasr(request) if provider == "funasr" else run_whisperx(request)


def serve() -> None:
    """按行收请求,权重留在内存里。

    常驻模式存在的全部理由就是**不要每次识别都重读一遍模型**:一次性模式下,一段十秒的
    音频里绝大部分时间花在加载上,而上一次识别刚把同一个模型读进内存、进程一退就全扔了。
    """
    threading.Thread(target=_watch_parent, args=(os.getppid(),), daemon=True).start()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            output = execute_request(json.loads(line))
            _emit({
                "event": "done",
                "language": str(output.get("language") or ""),
                "segments": output.get("segments") or [],
            })
        except Exception as exc:  # noqa: BLE001 — 常驻进程要**活下去**,把失败报回去就行
            traceback.print_exc(file=sys.stderr)
            _emit({"event": "error", "message": f"{type(exc).__name__}: {exc}"})


def main() -> None:
    # 一次性模式仍然在:预热/下载走它 —— 那是一次性的长任务,结果写文件、进度靠盘上字节数
    # 去看(见 ai/runtime/asr_models),不需要也不该占着一个常驻进程。
    if "--serve" in sys.argv[1:]:
        serve()
        return
    request = json.loads(sys.stdin.read())
    output = execute_request(request)
    with open(sys.argv[1], "w", encoding="utf-8") as handle:
        json.dump(output, handle, ensure_ascii=False)


if __name__ == "__main__":
    main()
