# ADR 0016: Separating voice from background is a capability, not a step in the dubbing flow

## Status

Accepted — 2026-09-16, implemented in 1.4.0 (local Demucs adapter; the hosted-API slot is still
empty). Extends the adapter organisation of ADR 0010 with a third capability and reuses the
managed-runtime machinery that ASR and TTS already run on. ADR 0017 applies the same shape to noise
reduction and replaces the audio extraction this record originally borrowed from transcription.

## Context

Translated dubbing replaces speech in one language with speech in another. The original speech must
therefore leave the mix, and until now the flow had two settings for it, neither of which is right:

- **Duck.** `render_executor.DUCK_GAIN = 0.3` (≈ −10.5 dB) while the dub speaks. That number was
  chosen for narration over ambience, where the bed is meant to stay audible. Two people talking,
  one of them quieter, is what the owner reported from a real run: 「视频原本的文案对应的音频还在」.
- **Mute.** Added in the same session and now the template's default. It silences the original
  track, which is correct for a talking head and wrong the moment the video has music: the music
  goes with the voice, because both live in one mixed track.

The missing operation is separation: one mixed track in, two or more stems out. Once it exists,
`mute` applies to the *vocal stem* rather than to the whole original audio, and the music survives.

Separation is not private to dubbing. The same operation answers "make an instrumental", "keep only
the voice for a cleaner transcript", "extract the background music from this clip". A step buried
inside the dub executor would have to be re-implemented at each of those, and this repository has
already paid for that shape once: a hand-written second tool list drifted and silently cost the
agent nineteen tools.

Two pluggable mechanisms already exist and neither should be duplicated:

- **Capability contract → connection adapter → registry** (ADR 0010): `ai/providers/contracts/`
  holds `generation.py` and `speech.py`; `adapters/` holds implementations organised by platform and
  protocol; `registry.py` is the single assembly point and fails at startup on a duplicate key.
- **Managed local runtime** (`ai/runtime/`): a per-engine virtualenv under the user's data
  directory, a model catalogue that asks the source for real download sizes rather than trusting a
  constant, and a resident worker pool so weights load once instead of once per call.

The second one carries a warning written after it was violated:

> 托管的 ASR 运行环境。和 TTS 那个分开:两边的依赖会打架(不同的 torch 版本),而共用一个
> venv 意味着装一边可能弄坏另一边。

## Options considered

| | Examples | Quality | Cost | What it is blocked on |
| --- | --- | --- | --- | --- |
| **A. Local model** | Demucs (htdemucs), MDX-Net/UVR, Spleeter | The first two are the current state of the art; 2-stem or 4-stem | One-time weight download; slow on CPU, fast on MPS/CUDA | Another torch, which means another managed venv |
| **B. Hosted API** | LALAL.AI, Moises, AudioShake | Comparable or better | Billed per minute; the whole track is uploaded | Privacy — the user's footage leaves the machine — plus one more credential to hold |
| **C. ffmpeg approximation** | Centre-channel cancellation (`pan`, `stereotools`) | Only when the voice is centred in a stereo mix, and it damages the rest | None | Useless on mono and on most re-encoded web video |

C cannot be the answer, but it is worth keeping as the behaviour when no engine is installed: the
feature then exists in the interface and says what it is doing, instead of disappearing.

A is the first implementation because it needs no credential, no billing surface and no privacy
note. B follows for users who will not download a gigabyte or have no GPU.

## Decision

1. **Separation is a capability with its own contract**, `ai/providers/contracts/separation.py`:
   a request names the audio and the stems wanted; an adapter writes stem files and returns their
   paths. Adapters register under an engine id in `registry.py`, the same way speech engines do.
   The contract does not mention Demucs, torch, or HTTP.

2. **The local adapter runs out of process, in its own managed virtualenv.** It reuses
   `ai/runtime`'s model catalogue (sizes measured from the source, not hardcoded), its resident
   worker pool (weights load once), and its line protocol. It does **not** share the ASR or TTS
   venv: they pin different torch versions, and that collision is the reason those two were split.

3. **Separation produces new assets; it never edits the original in place.** The source asset stays
   exactly as it was, and the stems arrive as new audio assets that the timeline can use. This is
   the same rule dubbing already follows — nothing is deleted, so every step is reversible by
   removing what was added.

4. **The dubbing flow asks the domain whether separation is available; it never imports an
   adapter.** When no engine is installed the flow falls back to today's behaviour (mute the whole
   original) and says so. A missing optional engine must not fail a workflow that was working.

5. **One capability, one registry, several entry points.** The workflow node, the editor action and
   the MCP tool all read the same registry. Adding an engine is one adapter plus one registration;
   no entry point holds a list of engine names.

## Consequences

- Translated dubbing keeps the music: the flow separates, discards the vocal stem, and lays the dub
  over the accompaniment. The accompaniment goes onto an audio track through the editor's own
  "detach audio" operation (with the background stem as the detached audio), and the source clip is
  muted — the picture stays where it was and the step is undoable. Pointing a video clip at the audio
  stem instead, as the first version did, drops the clip from both the picture and the mix. `original_audio: mute` then means "mute the vocal stem", which is what the
  setting always claimed to mean.
- Users who install nothing are not worse off than today, and the reason the option is greyed out is
  visible rather than silent.
- A third managed virtualenv is a real cost: another multi-gigabyte install path to keep working,
  another set of "is it installed, how much is left to download" states in the interface. It is
  accepted because the alternative — sharing a venv with ASR or TTS — breaks an engine the user
  already depends on, and that failure appears far from its cause.
- Quality claims about a separation engine are the engine's, not ours. As with user-authored
  parameter sets (ADR 0015), the honest surface says who is asserting what: a stem is the engine's
  output, and if it leaves artefacts that is visible in the result rather than hidden behind a
  promise we cannot keep.
- The hosted adapter (option B) will need a credential, a billing surface and an explicit statement
  that audio leaves the machine. Nothing in this decision blocks it; it is simply not first.
