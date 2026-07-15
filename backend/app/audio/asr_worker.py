"""Standalone ASR worker (ported from mibu-video's pluggable ASR layer).

Runs inside the *ASR interpreter* — a Python that has funasr and/or whisperx
installed (configured via MIBU_ASR_PYTHON, autodetected from a sibling
mibu-video checkout in dev). It must not import anything from this app at
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
import sys
import unicodedata
from typing import Any


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


def funasr_sentences_to_segments(sentences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map FunASR sentence_info (Paraformer spans + cam++ spk) to the segment
    contract. Per-char timestamps become word tokens; punctuation stays only in
    the sentence display text."""
    segments: list[dict[str, Any]] = []
    for sentence in sentences:
        text = (sentence.get("text") or "").strip()
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

    kwargs: dict[str, Any] = dict(
        model=request.get("funasr_model", "paraformer-zh"),
        vad_model=request.get("funasr_vad_model", "fsmn-vad"),
        punc_model=request.get("funasr_punc_model", "ct-punc"),
        hub=request.get("funasr_hub", "ms"),
        device=device,
        disable_update=True,
    )
    spk_model = request.get("funasr_spk_model", "cam++")
    if spk_model:
        kwargs["spk_model"] = spk_model
    model = AutoModel(**kwargs)
    result = model.generate(input=request["audio_path"], batch_size_s=300, sentence_timestamp=True)
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
    return {"language": "zh", "segments": funasr_sentences_to_segments(sentences)}


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


def main() -> None:
    request = json.loads(sys.stdin.read())
    provider = (request.get("provider") or "funasr").strip().lower()
    output = run_funasr(request) if provider == "funasr" else run_whisperx(request)
    with open(sys.argv[1], "w", encoding="utf-8") as handle:
        json.dump(output, handle, ensure_ascii=False)


if __name__ == "__main__":
    main()
