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
import re
import struct
import sys
import traceback
import unicodedata
import wave
from pathlib import Path
from typing import Any

if __package__:
    from .asr_protocol import encode_event_line
    from .parent_watch import watch_parent
else:
    # Executed directly by the ASR interpreter; its sys.path only contains this
    # directory, not the application package.
    from asr_protocol import encode_event_line
    from parent_watch import watch_parent


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


def _tokens_per_sentence(sentences: list[dict[str, Any]], tokens: Any) -> list[list[str]] | None:
    """模型自己的 token(结果里的 `words`)按句切开,和各句的 timestamp 一一对应;对不上就 None。

    **SenseVoice 的时间是按它自己的 token 给的**:标点也是一个 token、也带一段时间;英文的 token
    是词。各句的 timestamp 首尾相接正好是整条的那一串,`words` 与它一一对应(本机实测,中英文、
    单句多句都是)。Paraformer 没有这一栏(它的标点由 ct-punc 事后插入、不带时间),走逐字那条老路。
    """
    if not isinstance(tokens, list) or not all(isinstance(one, str) for one in tokens):
        return None
    counts = [len(sentence.get("timestamp") or []) for sentence in sentences]
    if sum(counts) != len(tokens):
        return None
    per_sentence, at = [], 0
    for count in counts:
        per_sentence.append(tokens[at:at + count])
        at += count
    return per_sentence


def _is_spoken(token: str) -> bool:
    """一个 token 是不是念出来的东西 —— 空白和纯标点不是,它们只留在整句的显示文本里。"""
    return any(_is_timed_char(ch) for ch in token)


def funasr_sentences_to_segments(sentences: list[dict[str, Any]], words: Any = None) -> list[dict[str, Any]]:
    """Map FunASR sentence_info (+ cam++ spk) to the segment contract.

    `words` 是 SenseVoice 结果里的 token 列表:给了而且对得上,每个 token 配它自己的那段时间
    (标点 token 跳过);没给或对不上,逐字配(Paraformer:时间只给字,标点不带时间)。
    标点只留在整句的显示文本里。"""
    tokens_per_sentence = _tokens_per_sentence(sentences, words)
    segments: list[dict[str, Any]] = []
    for index, sentence in enumerate(sentences):
        # **两种模型的字段名不同**:Paraformer 给 "text",SenseVoice 给 "sentence"。
        # 只读前者的那段时间里,SenseVoice 的每一句都取到空串,于是整条转写产出 0 段 ——
        # 界面上报的是「转写结果为空」,看不出是字段名对不上。
        raw = sentence.get("sentence") or sentence.get("text") or ""
        text, _lang = strip_funasr_tags(raw)
        spans = sentence.get("timestamp") or []
        if tokens_per_sentence is not None:
            pairs = [(token.strip(), span) for token, span in zip(tokens_per_sentence[index], spans) if _is_spoken(token)]
        else:
            pairs = list(zip([ch for ch in text if _is_timed_char(ch)], spans))
        timed: list[dict[str, Any]] = []
        for token, span in pairs:
            if not isinstance(span, (list, tuple)) or len(span) < 2:
                continue
            timed.append({"word": token, "start": _sec(span[0]), "end": _sec(span[1])})
        start = _sec(sentence["start"]) if sentence.get("start") is not None else (timed[0]["start"] if timed else 0.0)
        end = _sec(sentence["end"]) if sentence.get("end") is not None else (timed[-1]["end"] if timed else 0.0)
        if end <= start:
            end = start + 0.01
        spk = sentence.get("spk")
        try:
            speaker = f"SPEAKER_{int(spk):02d}" if spk is not None else None
        except (TypeError, ValueError):
            speaker = str(spk) if spk else None
        if not text and not timed:
            continue
        segments.append({"start": start, "end": end, "text": text, "speaker": speaker, "words": timed})
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
    # (paraformer-zh),但"用的是中文模型"和"这段音频是中文"是两件事。
    # 语种优先取**模型检测出来的那个**(SenseVoice 以 <|zh|> 这类标记给出),其次用请求指定的;
    # 两样都没有就报空(认不出),**不回落成 "zh"** —— 回落的 "zh" 和真检测出来的 "zh" 下游分不清:
    # 英文片子被记成中文,译成中文时被「原文已经是目标语言」拦下。空串下游一律当「不知道」,不比。
    detected = ""
    for sentence in sentences:
        _text, lang = strip_funasr_tags(sentence.get("sentence") or sentence.get("text") or "")
        if lang:
            detected = lang
            break
    return {
        "language": detected or request.get("language") or "",
        "segments": funasr_sentences_to_segments(sentences, words=item.get("words")),
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


# ---------------------------------------------------------------------------
# sherpa-onnx(SenseVoice 的 ONNX 运行时)
# ---------------------------------------------------------------------------
# 为什么同一个 SenseVoice 权重值得再有一条路:funasr 那条要 torch,而 torch 是"装一次 2GB、
# 起进程先读一遍、每次识别都在一个通用张量框架里跑一个小模型"的那一类开销。sherpa-onnx 只有
# onnxruntime(预编译轮子,约 12MB),同一个权重、同一套参数,拿掉的是那一层。
#
# 做法照 DSH 那个语音输入插件(同目录的 runtime/assets.json + lib/worker.js):同样的三个文件、
# 同样的 VAD 参数、同样"每 512 个样本喂一次 VAD 并取走成段语音"的循环。它那边只取文本,
# 这里还要时间轴,所以多用了 sherpa 结果里的 tokens/timestamps。
#
#: 采样率。SenseVoice 与 silero VAD 都按 16k;后端的 ffmpeg 提取也固定在 16k
#: (见 domain/voices/transcription._extract_audio)。
_SAMPLE_RATE = 16000
#: 一次喂给 VAD 的样本数,等于 silero 的 window_size(512)。
_VAD_CHUNK = 512
#: VAD 参数,与 DSH 的默认值一致(见它 lib/types/config.js 的默认档)。
_VAD_THRESHOLD = 0.5
_VAD_MIN_SILENCE = 0.5
_VAD_MIN_SPEECH = 0.25
_VAD_MAX_SPEECH = 30.0
#: onnxruntime 的线程数。DSH 默认 2 —— 识别是短任务,开满核只会和宿主抢 CPU。
_THREADS = 2
#: 取一段语音时**往回带**的这一小段。VAD 报的起点是"它确认这是语音"的那一刻,而那时第一个字
#: 已经念过去了 —— 实测(zh/en/long 三段)切掉的正是英文的 "The" 和中文的"大":识别结果少了
#: 一个词,而少掉的偏偏是句首那一个。往回带 0.3s 之后三段都与 funasr 逐字相同;再长的收益到此
#: 为止(0.2/0.3/0.5 都够,0.3 在三段上都干净),而带得越多,越容易把上一段的尾巴重复念一遍。
_VAD_PREROLL_SAMPLES = 4800  # 0.3s
#: sherpa-onnx 的 SenseVoice 构造参数只认这几个语种。
_SHERPA_LANGUAGES = ("auto", "zh", "en", "ja", "ko", "yue")

#: SenseVoice 的语种是**构造识别器时**给的(funasr 那条是每次 generate 传一个参数),所以按语种
#: 留一份。**只留最近的一个**:一个识别器抱着 239MB 权重,六个语种全留就是 1.4GB;而换语种重建
#: 实测约 0.35s,远小于一次识别本身,拿这个换掉那 1.4GB 是划算的。
_SHERPA_RECOGNIZER: dict[str, Any] = {}


def _sherpa_files(request: dict[str, Any]) -> dict[str, Path]:
    """权重在哪:`role → 路径`。

    **worker 不下载。** 出站检查装在宿主进程那一层(core/outbound_guard),而这里跑在一个外来的
    解释器里,够不到那道闸 —— 所以取文件是宿主的事(见 ai/runtime/asr_models.ensure_pinned_files),
    这里只负责"按 role 找到它、确认字节数和 pin 对得上"。缺了就说清楚,宿主下一次会补。

    报错是**英文**:worker 没有 i18n(它连 app 都 import 不了),而这句会作为 detail 挂在宿主那句
    翻好的话后面 —— 和别处透传上游的英文是同一种东西(见 core/i18n)。
    """
    # **用原始字符串判空**:`Path("")` 是 `Path(".")`(str 出来是 "."),拿它当判据的话
    # 一个没给目录的请求会被当成"放在当前目录"照跑下去。
    raw = str(request.get("sherpa_dir") or "")
    if not raw:
        raise RuntimeError("the request carries no sherpa_dir, so there is nowhere to look for the weights")
    directory = Path(raw)
    found: dict[str, Path] = {}
    for one in request.get("sherpa_files") or []:
        target = directory / str(one["name"])
        expected = int(one.get("bytes") or 0)
        if not target.is_file():
            raise RuntimeError(
                f"{one['name']} is not on disk; the host downloads the pinned weights"
                " (ai/runtime/asr_models.ensure_pinned_files)")
        if expected and target.stat().st_size != expected:
            raise RuntimeError(
                f"{one['name']} is {target.stat().st_size} bytes, expected {expected}")
        found[str(one.get("role") or "")] = target
    missing = [role for role in ("model", "tokens", "vad") if role not in found]
    if missing:
        raise RuntimeError(f"the weights are incomplete, missing: {', '.join(missing)}")
    return found


def _to_floats(raw: bytes, width: int) -> list[float]:
    """PCM 字节 → [-1, 1] 的浮点样本。"""
    if width == 2:
        return [one / 32768.0 for one in struct.unpack(f"<{len(raw) // 2}h", raw)]
    if width == 1:  # 8 位 wav 是无符号的
        return [(one - 128) / 128.0 for one in raw]
    if width == 4:
        return [one / 2147483648.0 for one in struct.unpack(f"<{len(raw) // 4}i", raw)]
    raise RuntimeError(f"unsupported wav sample width: {width * 8} bits")


def _resample(samples: list[float], source_rate: int, target_rate: int) -> list[float]:
    """线性插值重采样。够用:SenseVoice 自己也是按 16k 的帧取特征的。

    这条路的输入本来就是 ffmpeg 统一转好的 16k 单声道(见 transcription._extract_audio),这里
    只是别让一个意外的采样率把整条转写打死 —— VAD 不像识别器那样会自己重采样。
    """
    if source_rate == target_rate or not samples:
        return samples
    ratio = target_rate / source_rate
    last = len(samples) - 1
    return [samples[min(int(index / ratio), last)] for index in range(int(len(samples) * ratio))]


def _read_16k_mono(path: Path) -> list[float]:
    """读成 16k 单声道的浮点样本。

    **只用标准库。** worker 跑在**外来的**解释器里,那里的 sherpa-onnx 连 numpy 都不带
    (实测 1.13.8 只依赖 sherpa-onnx-core),所以 soundfile / librosa 那一类"顺手"的读法在这里
    是不能用的 —— 引进来就是给托管 venv 多加一个依赖,而"轻"正是这一家的理由。
    """
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())
    samples = _to_floats(raw, width)
    if channels > 1:
        samples = [sum(samples[at:at + channels]) / channels
                   for at in range(0, len(samples) - channels + 1, channels)]
    return _resample(samples, rate, _SAMPLE_RATE)


def _sherpa_language(requested: str) -> str:
    """请求里的语种 → 识别器认的那个值。不认识的交给它自己判(`auto`)。

    不抛错是有意的:语言的来源有工作流节点、听写、素材上的设置,而不认识一个语种(比如 "fr")
    时,让 SenseVoice 自己判比让整条转写失败有用得多 —— 它本来就是多语种模型。
    """
    wanted = (requested or "").strip().lower()
    return wanted if wanted in _SHERPA_LANGUAGES else "auto"


def _sherpa_build(files: dict[str, Path], language: str) -> Any:
    """建识别器(按语种缓存最近一个)。"""
    cached = _SHERPA_RECOGNIZER.get("recognizer")
    if cached is not None and _SHERPA_RECOGNIZER.get("language") == language:
        return cached
    import sherpa_onnx  # heavy-ish (onnxruntime), only in the ASR interpreter

    recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(files["model"]),
        tokens=str(files["tokens"]),
        num_threads=_THREADS,
        sample_rate=_SAMPLE_RATE,
        feature_dim=80,
        decoding_method="greedy_search",
        # 语种是构造参数(见 _SHERPA_RECOGNIZER)。ITN 打开,和 funasr 那条路一致:
        # SenseVoice 自带标点与逆文本规整,关掉的话"三点"不会写成"3点"、标点也会缺。
        language=language,
        use_itn=True,
        debug=False,
        provider="cpu",
    )
    _SHERPA_RECOGNIZER.clear()
    _SHERPA_RECOGNIZER.update(language=language, recognizer=recognizer)
    return recognizer


def _sherpa_vad(files: dict[str, Path]) -> Any:
    """建一个 VAD。**每次请求新建** —— 它带状态(缓冲、上一位),复用要记得 reset,
    而漏掉一次 reset 的症状是"这一段的结果里混着上一段的话",极难查。新建一个只读一遍
    1.8MB 的模型,便宜得多。"""
    import sherpa_onnx

    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = str(files["vad"])
    config.silero_vad.threshold = _VAD_THRESHOLD
    config.silero_vad.min_silence_duration = _VAD_MIN_SILENCE
    config.silero_vad.min_speech_duration = _VAD_MIN_SPEECH
    config.silero_vad.max_speech_duration = _VAD_MAX_SPEECH
    config.silero_vad.window_size = _VAD_CHUNK
    config.sample_rate = _SAMPLE_RATE
    config.num_threads = _THREADS
    config.provider = "cpu"
    config.debug = False
    # 缓冲秒数照 DSH 给的那个式子(最长一段 + 最小静默 + 1):小于最长一段的话,一段长语音
    # 还没被取走就把缓冲撑满了。
    return sherpa_onnx.VoiceActivityDetector(
        config, buffer_size_in_seconds=_VAD_MAX_SPEECH + _VAD_MIN_SILENCE + 1)


def _sherpa_pipeline(request: dict[str, Any]) -> tuple[Any, Any, str]:
    """(识别器, VAD, 实际用的语种)—— **预热和转写共用这一份**。

    funasr 那边为"两份构建逻辑各改各的"付过一次账(见 _funasr_kwargs 的说明):预热下的权重
    和转写要用的权重对不上。这里从一开始就只有一条路(取权重是宿主的事,见 _sherpa_files)。
    """
    files = _sherpa_files(request)
    language = _sherpa_language(str(request.get("language") or ""))
    return _sherpa_build(files, language), _sherpa_vad(files), language


def _sherpa_language_of(result: Any) -> str:
    """这一段是什么语种。**复用 funasr 那条口径**(strip_funasr_tags:同一个正则、同一条
    "2–3 个字母才算"的判据),只是要试两个地方:funasr 的 SenseVoice 把标记塞在正文开头,
    sherpa 把同样的标记抽出来放在结果的 `lang` 字段里。"""
    _text, tagged = strip_funasr_tags(getattr(result, "text", "") or "")
    if tagged:
        return tagged
    _nothing, from_field = strip_funasr_tags(str(getattr(result, "lang", "") or ""))
    return from_field


def _sherpa_words(result: Any, offset: float, span: float) -> list[dict[str, Any]]:
    """(词, 起, 止)—— 和 funasr 那条路同一个形状。

    sherpa 给的是**每个 token 的起点**(相对这一段),没有终点:一个 token 的终点就是下一个的
    起点,最后一个到这一段结束。这和 funasr 的 SenseVoice 分支同源(同一个模型),所以口径也照它:
    没念出来的 token(标点、纯空白)不进 words(见 _is_spoken)。

    留三位小数:SenseVoice 的时间戳本身是 60ms 一帧的,再细的位数只是 float32 的噪声。
    """
    timestamps = list(getattr(result, "timestamps", None) or [])
    tokens = list(getattr(result, "tokens", None) or [])
    if not timestamps or len(timestamps) != len(tokens):
        return []
    words: list[dict[str, Any]] = []
    for index, token in enumerate(tokens):
        if not _is_spoken(token):
            continue
        word = token.strip()
        if not word:
            continue
        start = offset + float(timestamps[index])
        end = offset + float(timestamps[index + 1]) if index + 1 < len(timestamps) else offset + span
        if end <= start:
            end = start + 0.01
        words.append({"word": word, "start": round(start, 3), "end": round(end, 3)})
    return words


def _sherpa_take(vad: Any, recognizer: Any, samples: list[float], previous_end: int,
                 duration: float, segments: list[dict[str, Any]]) -> tuple[str, int]:
    """取走 VAD 队首那一段并识别它。

    返回(这一段判出的语种, 这一段的结束样本号)—— 结束样本号给下一段当前奏的上界。

    **先取样本、再 pop**:`vad.front` 给的是缓冲里的一个视图,pop 之后就空了(实测:先收集
    一堆 front 再统一 pop,拿到的每一段 samples 长度都是 0)。
    """
    segment = vad.front
    start_sample = int(segment.start)
    chunk = segment.samples
    end_sample = start_sample + len(chunk)
    # 往回带一小段前奏(见 _VAD_PREROLL_SAMPLES)。下界取**上一段的结束**,不然前奏会把上一段的
    # 尾巴再念一遍 —— 多出来的字会出现在这一段的开头,而它是"凭空多出来的"。
    begin_sample = max(0, start_sample - _VAD_PREROLL_SAMPLES, previous_end)
    try:
        stream = recognizer.create_stream()
        stream.accept_waveform(_SAMPLE_RATE, samples[begin_sample:end_sample])
        recognizer.decode_stream(stream)
        result = stream.result
    finally:
        vad.pop()
    text, _tagged = strip_funasr_tags(result.text or "")
    if not text:
        return "", end_sample
    # **VAD 的起点是"喂进去的第几个样本"**,所以这一段的绝对起点就是它除以采样率;识别时多带了
    # 前奏,起点就跟着前移。整段没带前奏时它和 VAD 的起点相同。
    start = begin_sample / _SAMPLE_RATE
    end = min(end_sample / _SAMPLE_RATE, duration)
    if end <= start:
        end = start + 0.01
    detected = _sherpa_language_of(result)
    segments.append({
        "start": round(start, 3),
        "end": round(end, 3),
        "text": text,
        # 说话人分离是 funasr 那边 cam++ 的独立阶段,这条路上没有 —— 报 None(funasr 的
        # 单段无 spk 时也是 None),界面按"没有说话人信息"处理。
        "speaker": None,
        "words": _sherpa_words(result, start, end - start),
    })
    return detected, end_sample


def _sherpa_transcribe(recognizer: Any, vad: Any, samples: list[float]) -> tuple[list[dict[str, Any]], str]:
    """(segments, 识别到的语种)。"""
    segments: list[dict[str, Any]] = []
    duration = len(samples) / _SAMPLE_RATE
    detected = ""
    previous_end = 0

    def drain() -> None:
        nonlocal detected, previous_end
        while not vad.empty():
            heard, previous_end = _sherpa_take(vad, recognizer, samples, previous_end, duration, segments)
            detected = heard or detected

    # **边喂边取**:VAD 的缓冲是有界的(见 _sherpa_vad),队首不 pop 掉,后面那些语音段就会被丢弃。
    # DSH 那个 worker 同样是每 512 个样本 drain 一次。
    for at in range(0, len(samples), _VAD_CHUNK):
        vad.accept_waveform(samples[at:at + _VAD_CHUNK])
        drain()
    vad.flush()
    drain()

    if not segments and samples:
        # VAD 一个语音段都没给出(短到 0.25s 的一句话、或整段被判成非语音)时退化成整段识别。
        # 听写本来就是"说一句话",而在这里空手而归的代价是一条转写直接失败 —— 不如让识别器
        # 自己看一眼:它没有 VAD 那两道门槛,短音频照样能出字。
        stream = recognizer.create_stream()
        stream.accept_waveform(_SAMPLE_RATE, samples)
        recognizer.decode_stream(stream)
        result = stream.result
        text, _tagged = strip_funasr_tags(result.text or "")
        if text:
            segments.append({
                "start": 0.0,
                "end": round(duration, 3) or 0.01,
                "text": text,
                "speaker": None,
                "words": _sherpa_words(result, 0.0, duration),
            })
            detected = detected or _sherpa_language_of(result)
    return segments, detected


def run_sherpa_onnx(request: dict[str, Any]) -> dict[str, Any]:
    recognizer, vad, _language = _sherpa_pipeline(request)
    samples = _read_16k_mono(Path(request["audio_path"]))
    segments, detected = _sherpa_transcribe(recognizer, vad, samples)
    # 语种优先用**模型判出来的那个**,其次用请求指定的;两样都没有就报空(认不出)—— 和
    # run_funasr 同一条规矩:回落的 "zh" 和真检测出来的 "zh" 下游分不清。
    # 注意回落的是**请求原文**而不是解析后的 "auto":把 "auto" 当成一个语种写进逐字稿,
    # 下游(对齐、翻译)会拿着它去比对一个不存在的语言。
    return {"language": detected or str(request.get("language") or ""), "segments": segments}


def warmup_sherpa_onnx(request: dict[str, Any]) -> dict[str, Any]:
    """按 pin 把权重取下来(校验 sha256)并把识别器构建一次 —— 不跑推理。

    构建那一下是有用的:一个下坏了、或形状不对的 ONNX 在这一刻就报出来,而不是等用户说完一句话
    才发现自己下的是一个坏文件。和转写走同一个入口(_sherpa_pipeline)—— 那是 funasr 那边
    付过学费的规矩。权重本身由宿主按 pin 取(见 ai/runtime/asr_models.ensure_pinned_files)。
    """
    _sherpa_pipeline(request)
    return {"ok": True}


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(encode_event_line(payload))
    sys.stdout.flush()


#: 引擎 → 干什么。**只有这一份名单**:转写、预热各一张,加引擎时改这里就够,
#: 不会出现"装上了但分发里没有它"。
_RUNNERS = {
    "funasr": run_funasr,
    "sherpa-onnx": run_sherpa_onnx,
    "whisperx": run_whisperx,
}
_WARMUPS = {
    "funasr": warmup_funasr,
    "sherpa-onnx": warmup_sherpa_onnx,
    "whisperx": warmup_whisperx,
}


def execute_request(request: dict[str, Any]) -> dict[str, Any]:
    """按引擎分发。**认不出的引擎当场说**,不再默默当成 whisperx 跑。

    此前是一个二选一的三元式(funasr 否则 whisperx),于是第三个引擎无处可放,而一个写错的引擎名
    会被悄悄按 whisperx 跑起来 —— 那种错误的表现是"转出来的是别的引擎的结果",比报错难查得多。
    """
    provider = (request.get("provider") or "funasr").strip().lower()
    action = (request.get("action") or "transcribe").strip().lower()
    table = _WARMUPS if action == "warmup" else _RUNNERS
    runner = table.get(provider)
    if runner is None:
        raise ValueError(f"no such transcription engine: {provider}")
    return runner(request)


def serve() -> None:
    """按行收请求,权重留在内存里。

    常驻模式存在的全部理由就是**不要每次识别都重读一遍模型**:一次性模式下,一段十秒的
    音频里绝大部分时间花在加载上,而上一次识别刚把同一个模型读进内存、进程一退就全扔了。
    """
    watch_parent()  # 宿主没了就跟着退(见 workers/parent_watch)
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
