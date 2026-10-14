# Film project workflow

Use this workflow for any simple creative idea, trailer, short film, episodic sequence, or recurring-character project. It turns a short brief into world and image-asset prompts, a storyboard, and H3-ready single-shot prompts; it does not replace H3's prompt schema.

## Project brief

State: working title, format, audience, total runtime, target aspect ratio, visual treatment, per-clip duration, and production strategy. If a total runtime exceeds one H3 generation, split it into independently generated clips with explicit handoffs.

## Story spine

Use only the beats that fit: `setup → conflict → escalation → climax → resolution`. For an action sequence, structure visible cause and effect as `stance/read → attack → defense or evasion → counter → combination or signature move → impact → aftermath`. Avoid a list of disconnected cool shots.

## Asset handoff

After the world bible and before the storyboard, read `asset-prompt-writing.md` and output the required character and scene image-generation prompts. Assign every asset a stable ID. The storyboard must cite these IDs and explain whether each is a character reference, scene reference, start frame, or end frame.

## Character bible

For each recurring character, specify a stable identity anchor:

```text
Character ID:
visual identity: face, age range, physique, hair, skin tone, wardrobe, signature prop
movement: stance, gait, combat or gesture vocabulary
voice: language, timbre, pace; no dialogue if silent
states: baseline and named changes with visible triggers
constraints: characteristics that must not change between clips
```

Use supplied character images as the primary identity source. If no image is supplied, say that identity stability is an intended description, not a guaranteed asset lock.

## World bible

Fix reusable environment facts: location geometry, time/weather, color palette, lighting logic, materials, prop damage state, ambient sound, and forbidden visual additions. Assign a simple color/material cue to major narrative states only if it supports continuity.

## Storyboard

Create a compact table:

| Clip | Duration | Beat | Opening → closing state | Camera and action | Audio | Assets / H3 mode |
| --- | --- | --- | --- | --- | --- | --- |

Treat the closing state of a clip as the opening state of its successor. When a visual handoff must be exact, request or create a dedicated end-frame image and make the next clip an I2VA prompt using that image.

## H3 generation tasks

Compile every clip independently using the base or Ref2VA schema. Repeat only the continuity facts required by that clip: character identity, wardrobe/damage state, exact starting composition, environmental state, and the new action. Do not copy the project plan into a prompt.

## Continuity review

Check across the project: character identity and wardrobe, handedness, props and damage, time/weather/light direction, geography and screen direction, action cause/effect, dialogue and speaker IDs, audio transitions, and each clip's terminal-to-next-opening handoff. Report a mismatch with the affected clip IDs and a specific correction.
