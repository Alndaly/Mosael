"""Mosael 怎么驱动 F5-TTS 念一段任意长的文字。**所有对 F5 内部函数的依赖都只在这一个文件里。**

为什么不直接用 `F5TTS.infer`:它内部是三步 ——

    ① preprocess_ref_audio_text   参考音频截到 12 秒内;参考文本为空就用 Whisper 听写
    ② infer_process               按①的结果算 max_chars,把要念的文字切成 N 批
    ③ infer_batch_process(批次)   把 N 批放进 ThreadPoolExecutor **并发**跑

N > 1 时多个线程同时调 MPS,进程直接段错误(exit 139,连 traceback 都没有)。切几批由②决定,
而②依赖①处理之后的音频和文本 —— 在 `infer` 外面只能拿原始输入去猜,空参考文本、长参考音频时
必然猜错。所以这里不猜:①自己做一次,文字自己切,③每次只交**一个元素的列表**,线程池里永远
只有一个任务。「会不会并发」由这段代码保证,不再取决于 F5 怎么分批。

代价是用了 F5 的内部函数。版本由引擎依赖表钉住(`tts_models` 里的 `f5-tts~=1.1.22`),
`check_contract()` 在运行环境探测时和每次合成前各核一遍:对不上就判成「运行环境不就绪」,
重装运行环境会把它装回兼容的版本 —— 而不是念到一半才报一句看不懂的 TypeError。

和 `tts.py` 一样只许 import 标准库和同目录的协议模块(见本目录 `__init__` 的硬规则);
F5、torch、numpy 都在函数里按需导入。
"""
from __future__ import annotations

import inspect
import re
import sys
from typing import Any, Callable

if __package__:
    from .line_protocol import KeyedWorkerError
else:
    from line_protocol import KeyedWorkerError

#: 依赖表里钉的那个范围,说给人听的写法(报错文案里用)。
SUPPORTED_VERSIONS = "1.1.x"

#: 跨段接缝的交叉淡化时长。和 F5 自己在批次之间用的一样(`infer_batch_process` 的默认值)。
CROSSFADE_SECONDS = 0.15

#: 每段文字的字节上限不低于这个数。上限只影响念得好不好(段越短韵律越碎),不影响会不会崩;
#: 参考音频说得极慢时公式能算出个位数,那样会一个字一段。
_MIN_SEGMENT_BYTES = 20

#: F5 一次能生成的总长约 22 秒(参考 + 新内容)。段长按参考音频的语速换算,这条公式和 F5 自己
#: 在 `infer_process` 里切批用的一样 —— 区别是这里喂的是①**处理之后**的音频和文本。
_CONTEXT_SECONDS = 22.0

#: 一层一层往下切:句子 → 分句 → 词 → 字。每层的分隔符留在前一块的末尾,拼回去就是原文。
_SENTENCE_END = re.compile(r"(?<=[。！？!?；;…\n])|(?<=\.)(?=\s)")
_CLAUSE_END = re.compile(r"(?<=[，,、：:—])")
_WORD_END = re.compile(r"(?<=\s)")


def _contract() -> dict[str, Callable[..., Any]]:
    """F5 里我们要用的那几个函数,以及每个要能接受的调用方式。"""
    from f5_tts.infer.utils_infer import infer_batch_process, preprocess_ref_audio_text
    from f5_tts.model.utils import seed_everything

    return {
        "preprocess_ref_audio_text": preprocess_ref_audio_text,
        "infer_batch_process": infer_batch_process,
        "seed_everything": seed_everything,
    }


def _installed_version() -> str:
    try:
        from importlib.metadata import version

        return version("f5-tts")
    except Exception:  # noqa: BLE001 — 只用来写进报错,读不到就说不知道
        return "unknown"


def check_contract() -> None:
    """核对装着的 F5 还是我们依赖的那个形状。不是就抛带文案 key 的错。

    只核签名,不跑模型:运行环境探测会调它,那里不能加载权重。
    """
    try:
        functions = _contract()
        inspect.signature(functions["preprocess_ref_audio_text"]).bind(None, "", show_info=print)
        inspect.signature(functions["infer_batch_process"]).bind(
            None, "", [""], None, None,
            mel_spec_type="vocos", progress=None, speed=1.0, device=None,
            cross_fade_duration=0.0,
        )
        inspect.signature(functions["seed_everything"]).bind(0)
    except (ImportError, AttributeError, TypeError) as exc:
        version = _installed_version()
        raise KeyedWorkerError(
            "runtimeErr_f5Incompatible",
            f"F5-TTS {version} does not match what Mosael drives (needs {SUPPORTED_VERSIONS}): {exc}",
            version=version,
            supported=SUPPORTED_VERSIONS,
        ) from exc


def split_for_synthesis(text: str, max_bytes: int) -> list[str]:
    """把文字切成每段不超过 `max_bytes` 个 UTF-8 字节的若干段,尽量在句子边界上切。

    先按句子切;单句超长再按逗号顿号切;还超长按空白切(英文不会从单词中间断开);
    仍超长(一长串没有空格的字)才逐字切。切完把相邻的小块尽量装满一段。
    """
    limit = max(1, max_bytes)
    pieces = _split_to_fit(text, limit, (_SENTENCE_END, _CLAUSE_END, _WORD_END))
    segments: list[str] = []
    current = ""
    for piece in pieces:
        if current and _size(current + piece) > limit:
            segments.append(current)
            current = piece
        else:
            current += piece
    if current:
        segments.append(current)
    return [segment.strip() for segment in segments if segment.strip()]


def _size(text: str) -> int:
    return len(text.encode("utf-8"))


def _split_to_fit(text: str, limit: int, levels: tuple[re.Pattern[str], ...]) -> list[str]:
    if _size(text) <= limit:
        return [text]
    if not levels:
        return list(text)
    pieces: list[str] = []
    for part in levels[0].split(text):
        if part:
            pieces.extend(_split_to_fit(part, limit, levels[1:]))
    return pieces


def segment_budget(ref_seconds: float, ref_text: str, speed: float) -> int:
    """一段文字最多多少字节,F5 才念得进它一次生成的长度里。"""
    if ref_seconds <= 0 or not ref_text:
        return _MIN_SEGMENT_BYTES
    rate = _size(ref_text) / ref_seconds
    return max(_MIN_SEGMENT_BYTES, int(rate * (_CONTEXT_SECONDS - ref_seconds) * speed))


def crossfade_join(waves: list[Any], sample_rate: int, seconds: float = CROSSFADE_SECONDS) -> Any:
    """把逐段生成的波形接成一条,接缝处线性交叉淡化(和 F5 跨批次的做法相同)。"""
    import numpy as np

    if not waves:
        raise ValueError("no audio to join")
    joined = np.asarray(waves[0], dtype=np.float32)
    for wave in waves[1:]:
        following = np.asarray(wave, dtype=np.float32)
        overlap = min(int(seconds * sample_rate), len(joined), len(following))
        if overlap <= 0:
            joined = np.concatenate([joined, following])
            continue
        ramp = np.linspace(0.0, 1.0, overlap, dtype=np.float32)
        blended = joined[-overlap:] * (1.0 - ramp) + following[:overlap] * ramp
        joined = np.concatenate([joined[:-overlap], blended, following[overlap:]])
    return joined


def synthesize(
    model: Any,
    *,
    reference_wav: str,
    reference_text: str,
    text: str,
    speed: float,
    on_segment: Callable[[int, int], None],
) -> Any:
    """念 `text`,返回整条波形(采样率是 `model.target_sample_rate`)。

    `model` 是加载好的 `F5TTS`:只用它的权重、声码器和设备,不调它的 `infer`。
    `on_segment(i, n)` 在第 i 段(从 0 数)开始前调,给进度用。
    """
    import torchaudio

    check_contract()
    f5 = _contract()
    f5["seed_everything"](0)

    # ①只做一次:截短、听写都在这里。之后的段长和推理用的都是这一份,和 F5 自己看到的一致。
    ref_file, ref_text = f5["preprocess_ref_audio_text"](reference_wav, reference_text, show_info=_log)
    ref_audio, ref_rate = torchaudio.load(ref_file)
    budget = segment_budget(ref_audio.shape[-1] / ref_rate, ref_text, speed)
    segments = split_for_synthesis(text, budget)
    if not segments:
        raise ValueError("nothing to synthesize: the text is empty")

    waves = []
    for index, segment in enumerate(segments):
        on_segment(index, len(segments))
        # ③每次只交一段:线程池里只有一个任务,不会多线程并发调 MPS。
        wave, _rate, _spec = next(
            f5["infer_batch_process"](
                (ref_audio, ref_rate),
                ref_text,
                [segment],
                model.ema_model,
                model.vocoder,
                mel_spec_type=model.mel_spec_type,
                progress=None,
                speed=speed,
                device=model.device,
                cross_fade_duration=0.0,
            )
        )
        if wave is None:
            raise RuntimeError(f"F5 produced no audio for segment {index + 1}/{len(segments)}")
        waves.append(wave)
    return crossfade_join(waves, model.target_sample_rate)


def _log(message: str) -> None:
    # F5 默认把这些话 print 到 stdout,而 stdout 是 worker 的事件通道。
    print(message, file=sys.stderr, flush=True)
