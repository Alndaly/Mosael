# Preflight checklist

Before returning a prompt, verify all applicable items:

- Selected one correct mode and used its exact schema and alignment line.
- Preserved every hard constraint, exact dialogue/lyrics, visible text, asset role, duration, ratio, and exclusion.
- Used only later-defined Ref2VA labels and kept their meanings stable.
- Made shot numbers sequential; left Shot 1 untimed; made later cut timestamps strictly increasing and inside the total duration.
- Reached the requested last-frame anchor at the final moment; made FL2VA physically continuous unless cuts were explicitly requested.
- Kept speaker IDs stable, language tags correct, and voiceover lips closed.
- Placed sounds in the correct category: shot-specific dialogue/diegetic sound, global ambience/physical soundscape, audience-only score.
- Made camera, action, and audio descriptions concrete rather than metaphorical or plot-summary-only.
- Removed invented brands, logos, extra characters, unsupported claims, and unrequested scene text.

For combat scenes, also verify:

- Selected one primary type from `combat-style-library.md`; used a secondary accent only when the brief calls for a deliberate hybrid.
- Defined spatial geometry, attack path, defense/evasion, result, and the next actionable state for every exchange.
- Made each hit, parry, technique, or near-miss cause a visible physical or magical consequence.
- Used one coherent movement language; for xianxia, bounded flight, formations, talismans, and spiritual implements with a readable setup and limitation.
- Kept the decisive exchange visible instead of hiding it behind continuous camera orbit, random shake, or undifferentiated effects.

For Chinese traditional wuxia, also verify:

- Selected distinct human-scale fighting languages, tactical preferences, and limitations for both sides.
- Grounded each committed movement in range, footing, weight shift, weapon recovery, and breath.
- Gave every qinggong movement a takeoff, trajectory, landing, and recovery.
- Used terrain or props as a specific tactical factor and avoided unrequested mystical effects.
