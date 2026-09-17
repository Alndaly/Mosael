# ADR 0017: Noise reduction is a capability, with a built-in engine that is always there

## Status

Accepted — 2026-09-17. Follows the shape ADR 0016 set for separation. Amended twice the same day:
the two speech models (option B) are implemented, and voice isolation (option C) was withdrawn from
this capability — see the amendments at the end.

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

## Amendment — speech models (2026-09-17)

Option B turned out to be unblocked, just not through Python:

- **DeepFilterNet via its release binary, not its Python package.** `deepfilternet` 0.5.6 imports
  `torchaudio.backend.common`, which current torchaudio no longer has, and no old-enough torch
  installs on Python 3.13 — measured, the import fails. The same release ships `deep-filter`, a Rust
  executable with the model compiled in: no torch, no virtualenv, 27–36 MB per platform.
  `runtime/denoise_models` downloads it on an explicit settings action and **pins its SHA-256** per
  platform (macOS arm64 / x86_64, Windows x64, Linux x86_64 — hashes computed from the release
  files, which publish none). A mismatch discards the file and fails the install.
- **RNNoise via ffmpeg's `arnndn`.** The filter is built into ffmpeg; the only missing piece is a
  model file. `somnolent-hogwash` (trained on speech with fan / AC / computer noise, about 300 KB)
  ships inside the app; its source, licence note and checksum sit next to it.

Measured on synthetic speech (macOS `say`) with steady and intermittent noise, noise level in the
clean track's pauses and log-spectral distance on speech frames (SI-SDR was rejected as a metric:
the built-in engine's 70 Hz high-pass alone scores 13 dB on it through phase shift, not damage):

| | Steady noise, −41 dB | Intermittent noise, −35 dB | Speech distortion | Music |
| --- | --- | --- | --- | --- |
| Built-in (afftdn, strong) | −10 dB | −0.4 dB | low | untouched |
| RNNoise (full) | −16 dB | −19 dB | medium | −8 dB |
| DeepFilterNet (full) | −12 dB (−15 at −24 dB limit) | −34 dB | lowest | removed (−44 dB) |

Both models treat music as noise, so both declare `removes_music` and `auto` still means the
built-in engine. Each adapter now also declares a `description_key` and a `setup_hint_key`: the
interface lists engines without knowing any of them, so those sentences have to come from the
engine. The install-progress state that separation kept privately moved to
`runtime/install_state.InstallStore`, now shared by both.

## Amendment 2 — voice isolation is not noise reduction (2026-09-17)

Decision 2 listed a `voice-isolation` adapter that took the vocal stem from a separation engine. It
is withdrawn. "Keep only the voice" is exactly what separation already produces (its voice stem),
so offering it again under noise reduction gave one operation two entry points with two names, and
put a choice that removes all music and ambience next to choices that clean up a recording. The two
speech models above cover the case it was meant for (crowds, clatter) while keeping the sound of the
room. Users who want the bare voice take separation's voice stem; the guides and the denoise node's
description say so. The contract keeps `strengths = ()` for engines without levels.
