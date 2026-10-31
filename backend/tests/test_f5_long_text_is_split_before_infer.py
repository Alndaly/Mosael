"""F5 长文本在 MPS 上会走多 batch 路径并段错误(exit 139)。

回归点：宿主先切段，再对每段单独调 `model.infer`，最后拼接 WAV。
这里不加载真实权重，只钉住「每段各调一次」和「拼接发生在宿主」这两个行为。
"""
from __future__ import annotations

import sys
import types
import wave
from pathlib import Path

from app.ai.runtime.workers import tts


class _FakeModel:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def infer(self, **kwargs) -> None:
        self.calls.append(kwargs["gen_text"])
        path = Path(kwargs["file_wave"])
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(24_000)
            handle.writeframes(b"\x01\x00" * 4_800)


def test_long_text_runs_one_infer_per_chunk_and_concatenates(tmp_path, monkeypatch):
    fake_module = types.ModuleType("f5_tts.api")
    fake_module.F5TTS = object
    package = types.ModuleType("f5_tts")
    package.api = fake_module
    monkeypatch.setitem(sys.modules, "f5_tts", package)
    monkeypatch.setitem(sys.modules, "f5_tts.api", fake_module)

    model = _FakeModel()
    # 缓存键必须和 run_f5 算出来的一致，避免它去加载真实权重。
    cache_key = f"f5-tts:{tts.F5_CHECKPOINT}"
    tts._LOADED[cache_key] = model
    monkeypatch.setattr(tts, "_f5_text_chunks", lambda *_: ["第一段。", "第二段。", "第三段。"])

    output = tmp_path / "speech.wav"
    try:
        engine = tts.run_f5(
            {
                "reference_wav": "unused.wav",
                "reference_text": "参考文本",
                "text": "第一段。第二段。第三段。",
                "checkpoint": tts.F5_CHECKPOINT,
                "output_path": str(output),
            },
            str(output),
        )
    finally:
        tts._LOADED.pop(cache_key, None)

    assert engine == "f5-tts"
    assert model.calls == ["第一段。", "第二段。", "第三段。"]
    assert output.is_file()
    with wave.open(str(output), "rb") as handle:
        assert handle.getnframes() == 9_600
