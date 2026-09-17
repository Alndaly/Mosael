# ADR 0017: Noise reduction is a capability, with a built-in engine that is always there

## Status

Accepted — 2026-09-17. Follows the shape ADR 0016 set for separation.

## Context

Mosael records screen and camera, imports phone footage and downloads web video. Hum, fan noise,
room tone and street noise are the most common defect in all of those, and the product had no
answer to any of them: not in the media library, not in the editor, not on the workflow canvas,
not for the agent.

Noise reduction has the same shape as separation — one audio in, one cleaner audio out, the source
untouched — and the same entry points. ADR 0016 already paid for the design of that shape, so this
record only covers what differs.

## Options considered

| | Examples | Quality | Cost | Blocked on |
| --- | --- | --- | --- | --- |
| **A. ffmpeg filters** | `afftdn` (spectral), `anlmdn` (non-local means), `highpass` | Good on stationary noise (hum, fans, hiss); weak on babble and music | None — ffmpeg is already bundled | Nothing |
| **B. Speech-enhancement model** | DeepFilterNet, RNNoise weights | Much better on non-stationary noise | Another torch in another managed venv | Install size; no verified install on the build machine yet |
| **C. Voice isolation** | The vocal stem from a separation engine (ADR 0016) | Removes everything that is not a voice — including music | Whatever separation costs | A separation engine being installed |
| **D. Hosted API** | Adobe Podcast, Dolby.io, Auphonic | Very good | Per-minute billing, upload, credentials | Privacy note and a credential; no verified request/response samples |

## Decision

1. **Contract** `ai/providers/contracts/denoise.py`: a request names the audio and a strength
   (`light` / `medium` / `strong`); an adapter writes one cleaned audio file. The contract names no
   engine. An adapter that has no notion of strength says so (`strengths = ()`), so callers never
   show a knob that does nothing.
2. **Two adapters now**, one per real need:
   - `ffmpeg` (A) — always runnable, so the capability never "disappears". It is what `auto` picks.
   - `voice-isolation` (C) — composes the *separation contract*, not a separation engine. It is
     ready exactly when some separation adapter is. It is never chosen by `auto`, because it also
     removes music; the user has to ask for it.
3. **B and D are left as slots**, not written. Same rule as ADR 0016: no adapter is written against
   a request shape nobody has observed.
4. **The domain** (`domain/denoise.py`) owns the asset side: extract audio at full quality, call the
   adapter, and — for a video — put the cleaned audio back into a **new** video with the picture
   stream copied. The source asset is never modified.
5. **One registry, four entry points**: the `denoise_audio` workflow node, the `denoise_audio` agent
   tool (confirmation card, render-cost tier, returns a job id), the media library, and the editor's
   clip menu. None of them names an engine.
6. **Audio extraction for processing is full quality.** The transcription helper downsamples to
   16 kHz mono, which is right for ASR and wrong for anything whose output is listened to. Both
   separation and noise reduction now use `media/audio_io.extract_audio`, which keeps the source's
   sample rate and channels.

## Consequences

- Adding DeepFilterNet later is one adapter, one managed runtime entry and one registry line; no
  entry point changes.
- `auto` is deterministic (the built-in engine) rather than "the best installed", because the only
  stronger engine today changes *what* is removed, not just *how well*.
