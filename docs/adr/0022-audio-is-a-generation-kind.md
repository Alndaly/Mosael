# ADR 0022: Audio is a generation kind; speech synthesis stays where it is

## Status

Accepted — 2026-09-26.

## Context

The owner asked for audio "at the bottom layer": several vendors already configured in Mosael sell music,
background music, sound effects and video-to-audio generation. The generation pipeline — catalog descriptors
(ADR 0012/0013), adapter-declared parameter surfaces (ADR 0015), resumable remote receipts (ADR 0019),
plugin providers (ADR 0020) and the board producer registry (ADR 0021) — only knew `("image", "video")`,
and that tuple was copied into seven places (resolution, custom profiles, plugin connections, settings routes,
provider models, schemas, the workflow node). Adding a medium meant remembering all seven; missing one made the
medium silently absent from one entry point.

Audio already existed in two other shapes: **speech** (`/voices`, `/tts`: an engine and a voice read a text) and
**podcast** (a two-speaker WebSocket protocol). Both have their own request contracts (text + voice + speed),
their own engines (local F5-TTS / Fish Speech, cloned voices) and their own UI.

Research of official docs (2026-09-25; details in docs/AUDIO_GENERATION_CAPABILITIES.md) found:

- Google Lyria 3 / 3.5 — Gemini API `generateContent`, synchronous, no structured controls.
- Evolink — Suno v4…v5.5 on `/v1/audios/generations`, asynchronous, two tracks per request.
- Kling — text-to-audio (sound effects) and video-to-audio, asynchronous, same task envelope as video.
- Alibaba Model Studio — Fun-Music and AudioGen (`qwen-audio-3.1-tts-next`), synchronous, Beijing only.
- MiniMax — music-3.0 / 2.6 / cover, synchronous; **closed to new users since 2026-08-20**. (Integrated at first,
  removed on 2026-09-26 — see the addendum.)
- Volcengine AI music — `GenSong*` / `GenBGM*`, asynchronous, **AK/SK-signed only**.
- OpenAI — no music or sound-effect endpoint (speech only).

## Decision

1. **`audio` is the third generation kind.** `catalog.GENERATION_KINDS = ("image", "video", "audio")` is the
   only list; resolution, custom-profile validation, plugin connections, settings routes, provider-model
   inference, the options route and usage checks read it. `audio` is also a provider capability id and a
   defaultable capability, next to `tts` and `podcast`, because a connection can have one without the other.

2. **Speech stays a separate capability.** A TTS request is "these words in this voice at this speed"; a music
   request is "a piece that sounds like this, maybe with these lyrics". Folding TTS into generation would give
   every speech engine a descriptor it cannot use (voices are a per-engine list with cloning, not a parameter) and
   would break the dubbing path, which synthesizes many lines per job. What they share is the output — an audio
   asset — and that already goes through the same importer. A vendor model that *does* generate speech from a
   prompt as part of general audio (Alibaba's AudioGen) is catalogued as `audio`; the catalog, not the name,
   decides (the `tts` name hint loses to the catalog entry). The agent keeps `generate_audio` for speech and gets
   `generate_sound` for music / sound; each description says what the other is for.

3. **Host vocabulary for audio.** The prompt describes the sound (style, genre, mood, tempo — vendors' separate
   "style" fields are fed from it). `lyrics` is a separate long-text input with `max_lyrics_chars`.
   `instrumental` is a boolean with its own control. `duration_seconds` is **optional** for audio (most music
   models size the track to the lyrics). Roles keep their meaning across kinds: `source_video` is the video being
   processed (scored, for audio), `reference_audio` a style/cover reference, `first_clip` what the output
   continues (an audio clip when generating audio), `reference_image` an image to turn into music. Vendor extras
   (`vocal_gender`, `title`, `bgm_prompt`, `model_version`) are declared per model through `parameter_schema` /
   `parameter_choices`, labelled by the host when it knows the key.

4. **Text rules live in one validator** (`operations.validate_text_inputs`): image/video need a prompt; audio
   needs a prompt or lyrics unless the model says `prompt_optional` (video-to-audio); instrumental excludes lyrics
   and needs a prompt; `requires_prompt`, `requires_lyrics`, `lyrics_excludes_prompt` and `max_lyrics_chars` come
   from the descriptor. The API no longer requires a non-empty `prompt` at the schema level; the domain answers
   with a localized 422 instead.

5. **Registration and metering.** Every returned file is registered (Suno's two tracks are two assets). Audio
   suffixes follow the response Content-Type first, and audio in an MP4 container is stored as `.m4a`, so the
   library files it as audio. Usage records `audios` (tracks produced), `lyrics_characters`, and `audio_seconds`
   — the provider's billed seconds when it reports them (Volcengine, Alibaba), otherwise the probed duration of
   the registered assets. The requested duration is never recorded as billed seconds. A new billing unit `audio`
   (per track) joins `audio_second`; list prices are added only where an official page gives a per-song or
   per-second price (Lyria, Fun-Music, Volcengine postpaid).

6. **Adapters follow the existing seams.** Asynchronous vendors (Suno via Evolink, Kling, Volcengine) go through
   `poll_until_ready`, so the receipt is persisted before waiting and `resume` collects it after a restart
   (ADR 0019); Volcengine's signed-POST query is wrapped in a tiny client whose `get(poll_path)` issues the signed
   call. Synchronous vendors (Lyria, Alibaba) disable HTTP retries on the paid POST — a retried read
   timeout would pay twice — and have no receipt to persist. Vendor error codes are mapped to categories
   (`auth`, `balance`, `rate_limited`, `content_blocked`, `invalid_params`, `not_entitled`, `unavailable`) with
   localized messages; the vendor's own text stays in `detail`.

7. **Volcengine music is its own connection** (`volcano-music`): AK + SK, service `imagination`. The AK/SK
   signature moved from `integrations/volc_openapi` into `ai/providers/adapters/bytedance/volcano/openapi_sign`
   so both the voice list and music generation use one implementation.

## Consequences

- AI Studio lists audio models in the same picker, with a lyrics editor, a vocals/instrumental switch, an optional
  duration, audio source slots and audio players for results. The workflow `ai_generate` node, scheduled
  generation, the agent (`generate_sound`, `list_generation_models(kind="audio")`) and generation history take
  `kind: "audio"` without new paths.
- Board: the `generate` producer's hosts are derived from `KINDS`, so audio slots can run generation as soon as
  this lands. The board UI still needs an audio-slot form (model picker filtered to audio, lyrics, instrumental)
  — that work belongs to the board producers track.
- Plugins can declare `kind: "audio"` models; `lyrics` and `instrumental` map onto host controls.
- None of the vendors has been run with a real key; every descriptor says so and cites its doc page. The first
  real run of each should re-check limits the way `test_capabilities_match_reality` does for video.
- TTS could later become an audio-generation mode if a vendor ships prompt-driven speech that fits the descriptor
  model; that would be a new ADR, not a flag.

## Addendum (2026-09-26): MiniMax music removed

MiniMax stopped selling music generation to new accounts on 2026-08-20; a new user could configure the model and
only learn at the first paid call that the vendor refuses them. The adapter, its three catalog entries
(`music-3.0`, `music-2.6`, `music-cover`) and the `minimax-music*` capability profiles are gone, and MiniMax no
longer offers the `audio` capability. The one-time migration `remove-minimax-music-models` deletes those model
rows (with their declarations, defaults and price rules), clears pointers to the removed profiles, and clears the
model choice wherever it was saved — AI Studio sessions, board generation cells, workflow `ai_generate` nodes (a new
revision) and scheduled generations (disabled, so a schedule never silently spends on another model). Generation
history and usage keep their records. MiniMax chat and Hailuo video are unaffected.

## Addendum (2026-09-26): the prompt requirement is one descriptor field

Decision 4's `requires_prompt` / `prompt_optional` booleans and the hard-coded "image and video need a prompt" are
replaced by one field for every kind: `prompt` = `required` (default; lyrics count for models that take lyrics) /
`optional` / `none` (takes no prompt; sending one is rejected). The rule set stays in `validate_text_inputs`; see
the ADR 0020 addendum of the same date. Saved custom profiles are rewritten by
`migrate-prompt-requirement-becomes-one-field`.
