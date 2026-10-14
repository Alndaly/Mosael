# H3 schemas

Use these literal field names, punctuation, and order.

## Base modes: T2VA / I2VA / FL2VA / L2VA

T2VA has no alignment line:

```text
integrated_multimodal_description: [Shot 1] ...

overall_soundscape: ...

non_diegetic_music: ...
```

I2VA begins with this literal first line, followed by one blank line:

```text
For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.
```

FL2VA begins with this literal first line. Replace `N` with the actual final-shot number and `S.SS` with the requested effective duration to exactly two decimals:

```text
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot N) aligns with the S.SS-second mark of the target video.
```

L2VA begins with this literal first line. Picture 1 belongs to the actual final shot, not necessarily Shot 1:

```text
How the reference pictures align with the target video — <Picture 1> (from [Shot N]) aligns with the S.SS-second mark of the target video.
```

Then use the three base fields shown under T2VA. Do not timestamp `[Shot 1]`. Format later cuts as `[Shot 2] At 00:03.500, the camera cuts to...`.

## Full-reference mode: Ref2VA

Write every field in English, using exactly this order:

```text
subject_definitions:
<Subject 1> is ...
<Picture 1> is ...
<Video 1> is ...
<Audio 1> is ...

summary:
[reference generation] ...

retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - ...
<Audio 1>: reference - ...

detailed_description:
The target video is in a ... style.
[Shot 1] ...
[Shot 2] At 00:03.500, the shot cuts to ...

overall_soundscape:
...

non_diegetic_music:
...
```

### Labels

- `<Subject N>`: reusable visible person, animal, object, environment, costume, prop, style, action, expression, or effect.
- `<Picture N>`: a concrete keyframe, composition anchor, or storyboard reference.
- `<Video N>`: an editing source, continuation source, or source of temporal/camera/cut structure.
- `<Audio N>`: a copied or referenced audio signal.

Number each label category independently and define only labels used later. A source asset can define several subjects; one subject can draw from several source assets.

### Summary task-type prefix

Use one or more of these, joined by ` + `: `keyframe completion`, `reference generation`, `video editing`, `video continuation`, `audio reuse`, `audio reference`. Use `video editing` or `video continuation` only when the source video itself is modified or extended.

### Retention markers

For `<Subject N>`, `<Picture N>`, and `<Video N>`, use exactly one of: `fully_preserved`, `partially_preserved`, `attribute_transfer`, `weak_reference`.

For `<Audio N>`, use exactly one of: `fully_copy`, `partially_copy`, `reference`, `weak_reference`.

Write one line for every defined label. In Ref2VA, establish a visual style sentence before `[Shot 1]`; for generation tasks, make `detailed_description` normally 350–500 English words unless the duration or dialogue density makes that unsuitable.
