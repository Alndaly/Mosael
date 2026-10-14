---
name: minimax-h3-video-prompt
description: Create paste-ready MiniMax H3 video-generation prompts and coherent multi-shot AI-film production plans from a creative brief and supplied images, videos, or audio. Use for text-to-video (T2VA), first-frame (I2VA), first-and-last-frame (FL2VA), last-frame (L2VA), video editing/continuation, multi-asset reference generation (Ref2VA), trailers, fight scenes, and short-film shot lists; select the correct H3 schema and return prompts that can be used directly in MiniMax H3.
---

# MiniMax H3 Video Prompt

Turn the user's brief and supplied media into one paste-ready H3 prompt, or into a complete asset-to-shot package for a short film. The default for a simple creative idea is the asset-to-shot package. Do not claim that H3 accepts a custom JSON schema or a negative-prompt field.

## Required workflow

1. Identify every hard constraint: duration, aspect ratio, source media, reference roles, visual anchors, dialogue, lyrics, visible text, requested actions, audio, and exclusions.
2. Select one mode with the rules in [references/h3-schema.md](references/h3-schema.md): T2VA, I2VA, FL2VA, L2VA, or Ref2VA.
3. Infer only production details that do not change the user's intent. If a missing choice would materially change the result, ask one concise question; otherwise state the assumption in one short line before the prompt.
4. For a simple creative idea, trailer, short film, series, recurring character, or more than one H3 clip, read [references/film-project-workflow.md](references/film-project-workflow.md) and [references/asset-prompt-writing.md](references/asset-prompt-writing.md). Establish the world, asset plan, and shot plan before compiling any H3 prompt.
5. For a duel, fight, chase with combat, martial arts, wuxia, xianxia, weapon exchange, or action climax, read [references/combat-choreography.md](references/combat-choreography.md). Draft a causal beat card before writing the H3 prompt.
6. Read [references/combat-style-library.md](references/combat-style-library.md) to select exactly one primary combat type and its movement, scale, camera, sound, and consequence rules. Add a secondary accent only when the brief calls for a deliberate hybrid.
7. For Chinese traditional wuxia, jianghu, martial-arts weapon duel, or grounded qinggong, also read [references/traditional-wuxia.md](references/traditional-wuxia.md). Select a weapon/martial language, terrain interaction, and physical limitation before drafting the beat card.
8. Read the mode-specific template in [references/h3-schema.md](references/h3-schema.md), then write each final prompt exactly in its required field order.
9. Run the preflight checklist in [references/preflight.md](references/preflight.md). Output only the final prompt after any necessary assumption line.

## Mode selection

- No reference asset: **T2VA**.
- One image is the exact opening frame: **I2VA**.
- Two images are exact opening and ending frames: **FL2VA**; default to one physically continuous shot.
- One image is the exact ending frame: **L2VA**.
- A source video is edited or continued, or several assets must retain independently traceable roles: **Ref2VA**.

Do not select Ref2VA merely because an ordinary reference video happens to contain audio. Use an `<Audio N>` label only when that audio is copied or referenced.

## Project mode

Use project mode for a simple creative idea, multi-clip work, project plan, trailer, episode, or asset strategy. Simulate the production roles sequentially; do not claim actual multi-agent execution.

1. Define a compact project brief: format, audience, total runtime, per-clip duration, visual style, delivery ratio, and production strategy.
2. Create the world bible, then derive a minimal, production-relevant asset list.
3. Create the character bible and platform-agnostic image-generation prompts for every required character state; create scene-asset prompts for every reusable location or key environment state.
4. Create a story spine with setup, conflict, escalation, climax, and resolution. Omit beats that do not fit the runtime.
5. Build a storyboard table in chronological order. Every row must state clip ID, duration, narrative beat, opening state, closing state, key action, camera plan, sound plan, and required source assets.
6. For action clips, build the combat beat card first and retain its spatial, weapon, and damage consequences in the opening state of the next clip.
7. Compile each row as its own H3 prompt. Choose the H3 mode per clip, not per project; name which supplied pictures/videos/audio each prompt needs.
8. Run a continuity review across adjacent clips and provide only actionable revisions when a mismatch exists.

Do not promise automatic image generation, ComfyUI workflows, H3 batch submission, rendered-video scoring, or publishing unless the user asks for those deliverables and the required tools are available.

## Writing rules

- Write every H3 field in English. Preserve dialogue, lyrics, and on-screen text in their original language.
- For T2VA/I2VA/FL2VA/L2VA, use only the required alignment line (if applicable), then `integrated_multimodal_description`, `overall_soundscape`, and `non_diegetic_music`.
- For Ref2VA, use exactly `subject_definitions`, `summary`, `retention_analysis`, `detailed_description`, `overall_soundscape`, and `non_diegetic_music`, in that order.
- Make the timeline observable. Each shot must establish composition, subject position and appearance, environment/lighting, action or state change, camera behavior, and synchronous sound where relevant. Start `[Shot 1]` without a timestamp. Later cuts use strictly increasing `MM:SS.mmm` timestamps.
- Prefer continuous camera movement to cuts that introduce no new information. Express camera motion naturally as motion type plus meaningful amplitude and speed.
- For combat, express a sequence of causal exchanges: position and intent → specific attack path → specific defense/evasion → contact or near-miss → physical consequence → newly available counter. Never substitute a stack of generic verbs such as “fights fiercely,” “rapid attacks,” “spins,” or “energy explodes.”
- Make the selected combat type change the shot's movement grammar, scale, weapon/ability limits, camera language, sound, and aftermath. Keywords alone are never a combat design.
- For traditional wuxia, retain weight, reach, footing, breath, weapon recovery, and terrain friction. Treat qinggong as a brief, terrain-supported displacement with a landing or recovery, not unlimited flight.
- Do not place the internal combat beat card or its headings inside the final H3 prompt; convert it to fluent shot description in the selected official schema.
- Maintain image continuity: identity, wardrobe, objects, colors, spatial relations, lighting logic, and the intended frame anchor.
- Give each vocal source a stable `(S1)`, `(S2)` ID. Put only exact spoken content in `<d>[Language] ...</d>`. For voiceover, write `says in an off-screen voiceover` and explicitly say the on-screen speaker's lips remain completely closed.
- Quote visible on-screen text in English double quotation marks. Do not translate it.
- Keep dialogue and lyrics within the available duration. Use `<scenetrans>` for a line crossing a cut and `<cutoff>` for speech cut off by the end.
- Put dialogue, singing, and diegetic music in the shot description, not in `overall_soundscape`. Put audience-only score in `non_diegetic_music`; use `N/A` when absent.

## Anchor behavior

- **I2VA:** begin from `<Picture 1>` at 0.00 seconds; explicitly retain the image's key visual facts before action begins.
- **FL2VA:** describe a causal, continuous route from Picture 1 to Picture 2. End in the exact final composition; do not describe two disconnected static states.
- **L2VA:** invent a compatible preceding state and explicitly converge on the reference image in the final shot.
- **Ref2VA:** define only reference labels used later. Keep each label's meaning fixed across all six fields. In `retention_analysis`, use only the allowed relationship markers in the reference schema.

## Output contract

For single-clip work, return a clean prompt in a single fenced `text` block unless the user asks for plain text. Do not include headings such as “final prompt”, commentary, JSON, markdown tables, or unsupported negative-prompt fields inside that block.

For project mode, return this order: `PROJECT BRIEF`, `WORLD BIBLE`, `CHARACTER ASSET PROMPTS`, `SCENE ASSET PROMPTS`, `STORY SPINE`, `STORYBOARD`, `H3 GENERATION TASKS`, and `CONTINUITY REVIEW`. Put every asset-generation prompt and every individual H3 prompt in its own fenced `text` block. Keep planning prose concise; only these blocks are directly reusable inputs.
