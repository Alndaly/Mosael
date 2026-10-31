"""F5 一次只跑一批:长文本不再交给 `F5TTS.infer` 去分批(它把多批放进线程池并发跑,MPS 上段错误)。

钉住的是 workers/f5_driver 的几条承诺,不加载真实权重:

- 参考音频只预处理一次,段长按**预处理之后**的参考文本算 —— 参考文本为空(F5 自己听写)时也一样;
- 每次调 `infer_batch_process` 只交一个元素的列表;
- 逐段波形按顺序交叉淡化拼成一条;
- 装着的 F5 对不上我们用的内部函数时,报带文案 key 的错,而不是念到一半 TypeError。
"""
from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from app.ai.runtime.workers import f5_driver, tts
from app.ai.runtime.workers.line_protocol import KeyedWorkerError

RATE = 24_000
#: 预处理之后的参考:5 秒,说了这么多字。段长上限由它换算(约 12 字节/秒 × 17 秒 ≈ 205 字节)。
REF_SECONDS = 5
TRANSCRIBED = "这是听写出来的参考文本。共二十个字左右。"


class FakeF5:
    """假的 f5_tts 内部函数:记下怎么被调用的。"""

    def __init__(self) -> None:
        self.preprocessed: list[tuple[str, str]] = []
        self.batches: list[list[str]] = []
        self.seeds: list[int] = []

    def preprocess_ref_audio_text(self, ref_audio_orig, ref_text, show_info=print):
        self.preprocessed.append((ref_audio_orig, ref_text))
        return "/tmp/clipped-ref.wav", ref_text or TRANSCRIBED

    def infer_batch_process(
        self, ref_audio, ref_text, gen_text_batches, model_obj, vocoder, mel_spec_type="vocos",
        progress=None, target_rms=0.1, cross_fade_duration=0.15, nfe_step=32, cfg_strength=2.0,
        sway_sampling_coef=-1, speed=1, fix_duration=None, device=None, streaming=False, chunk_size=2048,
    ):
        self.batches.append(list(gen_text_batches))
        # 每段生成 0.5 秒,值等于第几段,方便看拼接顺序。
        yield np.full(RATE // 2, float(len(self.batches)), dtype=np.float32), RATE, None

    def seed_everything(self, seed=0):
        self.seeds.append(seed)


class FakeModel:
    ema_model = object()
    vocoder = object()
    mel_spec_type = "vocos"
    device = "mps"
    target_sample_rate = RATE

    def __init__(self) -> None:
        self.exported: list[tuple[np.ndarray, str]] = []

    def export_wav(self, wav, file_wave, remove_silence=False):
        self.exported.append((wav, file_wave))


@pytest.fixture
def f5(monkeypatch: pytest.MonkeyPatch) -> FakeF5:
    fake = FakeF5()
    utils_infer = types.ModuleType("f5_tts.infer.utils_infer")
    utils_infer.preprocess_ref_audio_text = fake.preprocess_ref_audio_text
    utils_infer.infer_batch_process = fake.infer_batch_process
    model_utils = types.ModuleType("f5_tts.model.utils")
    model_utils.seed_everything = fake.seed_everything
    torchaudio = types.ModuleType("torchaudio")
    torchaudio.load = lambda path: (np.zeros((1, REF_SECONDS * RATE), dtype=np.float32), RATE)
    for name, module in {
        "f5_tts": types.ModuleType("f5_tts"),
        "f5_tts.infer": types.ModuleType("f5_tts.infer"),
        "f5_tts.infer.utils_infer": utils_infer,
        "f5_tts.model": types.ModuleType("f5_tts.model"),
        "f5_tts.model.utils": model_utils,
        "torchaudio": torchaudio,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    return fake


LONG_TEXT = "第一句话说的是开场白，内容比较长一些。" * 12


def _synthesize(text: str, reference_text: str = "参考文本") -> tuple[np.ndarray, list[tuple[int, int]]]:
    progress: list[tuple[int, int]] = []
    audio = f5_driver.synthesize(
        FakeModel(),
        reference_wav="/tmp/ref.wav",
        reference_text=reference_text,
        text=text,
        speed=1.0,
        on_segment=lambda index, total: progress.append((index, total)),
    )
    return audio, progress


def test_every_inference_call_carries_exactly_one_segment(f5: FakeF5) -> None:
    audio, progress = _synthesize(LONG_TEXT)

    assert len(f5.batches) > 1, "这段文字应当长到要分好几段"
    assert all(len(batch) == 1 for batch in f5.batches), f5.batches
    assert "".join(batch[0] for batch in f5.batches) == LONG_TEXT
    assert progress == [(index, len(f5.batches)) for index in range(len(f5.batches))]
    assert f5.seeds == [0]


def test_the_reference_is_preprocessed_once_and_its_transcript_sizes_the_segments(f5: FakeF5) -> None:
    """参考文本为空时 F5 自己听写 —— 段长必须按听写出来的那句算,不能退回一个猜的常数。"""
    _synthesize(LONG_TEXT, reference_text="")

    assert f5.preprocessed == [("/tmp/ref.wav", "")]
    budget = f5_driver.segment_budget(REF_SECONDS, TRANSCRIBED, 1.0)
    assert all(len(batch[0].encode("utf-8")) <= budget for batch in f5.batches)
    assert budget != f5_driver.segment_budget(REF_SECONDS, "", 1.0)


def test_segments_are_joined_in_order_with_a_crossfade(f5: FakeF5) -> None:
    audio, _ = _synthesize(LONG_TEXT)

    segments = len(f5.batches)
    overlap = int(f5_driver.CROSSFADE_SECONDS * RATE)
    assert len(audio) == segments * (RATE // 2) - (segments - 1) * overlap
    assert audio[0] == 1.0 and audio[-1] == float(segments)


def test_run_f5_writes_the_joined_audio_through_the_model(f5: FakeF5, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    model = FakeModel()
    api = types.ModuleType("f5_tts.api")
    api.F5TTS = object
    monkeypatch.setitem(sys.modules, "f5_tts.api", api)
    cache_key = f"f5-tts:{tts.F5_CHECKPOINT}"
    monkeypatch.setitem(tts._LOADED, cache_key, model)
    events: list[tuple[str, str]] = []
    monkeypatch.setattr(tts, "_progress", lambda phase, fraction, message="": events.append((phase, message)))

    output = str(tmp_path / "speech.wav")
    engine = tts.run_f5(
        {"reference_wav": "/tmp/ref.wav", "reference_text": "参考文本", "text": LONG_TEXT, "checkpoint": tts.F5_CHECKPOINT},
        output,
    )

    assert engine == "f5-tts"
    assert [path for _, path in model.exported] == [output]
    assert events[-1] == ("generate", f"生成中 {len(f5.batches)}/{len(f5.batches)}")


def test_an_incompatible_f5_is_reported_with_a_message_key(f5: FakeF5) -> None:
    def renamed_parameters(ref, text, batches, model, vocoder, *, mel_type="vocos"):
        yield None

    sys.modules["f5_tts.infer.utils_infer"].infer_batch_process = renamed_parameters

    with pytest.raises(KeyedWorkerError) as caught:
        f5_driver.check_contract()

    assert caught.value.key == "runtimeErr_f5Incompatible"
    assert caught.value.params["supported"] == f5_driver.SUPPORTED_VERSIONS
    with pytest.raises(KeyedWorkerError):
        _synthesize(LONG_TEXT)
    assert f5.batches == [], "对不上时一段都不该开始念"
